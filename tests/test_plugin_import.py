from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
import types
from pathlib import Path

from trace_inspector import PLUGIN_VERSION


class FakeRoutes:
    def __init__(self):
        self.registered = []

    def _decorator(self, method, path):
        def decorate(fn):
            self.registered.append((method, path, fn.__name__))
            return fn
        return decorate

    def get(self, path):
        return self._decorator("GET", path)

    def post(self, path):
        return self._decorator("POST", path)

    def patch(self, path):
        return self._decorator("PATCH", path)

    def delete(self, path):
        return self._decorator("DELETE", path)


class FakePromptServerInstance:
    def __init__(self):
        self.routes = FakeRoutes()
        self.messages = []

    def send_sync(self, event_type, payload):
        self.messages.append((event_type, payload))


def test_plugin_version_matches_project_metadata():
    plugin_root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((plugin_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert PLUGIN_VERSION == project["project"]["version"]


def test_korean_locale_covers_every_custom_node():
    plugin_root = Path(__file__).resolve().parents[1]
    main = json.loads((plugin_root / "locales" / "ko" / "main.json").read_text(encoding="utf-8"))
    node_defs = json.loads((plugin_root / "locales" / "ko" / "nodeDefs.json").read_text(encoding="utf-8"))
    expected_nodes = {
        "ComfyTraceClip",
        "ComfyTraceModel",
        "ComfyTraceExport",
        "ComfyTraceNote",
        "ComfyTraceImage",
        "ComfyTraceLatent",
        "ComfyTraceMask",
        "ComfyTraceConditioning",
        "ComfyTraceModelSnapshot",
    }

    assert main["nodeCategories"]["Sampling Trace Inspector"] == "샘플링 추적 분석기"
    assert set(node_defs) == expected_nodes
    for definition in node_defs.values():
        assert definition["display_name"].startswith("샘플링 추적")
        assert definition["description"].strip()
        assert definition["inputs"]
        assert definition["outputs"]


def test_panel_uses_comfy_locale_and_hides_uncaptured_preview_steps():
    plugin_root = Path(__file__).resolve().parents[1]
    panel_script = (plugin_root / "web" / "trace_inspector.js").read_text(encoding="utf-8")

    assert 'getSettingValue?.("Comfy.Locale")' in panel_script
    assert 'localeText("샘플링 추적 분석기", "Sampling Trace Inspector")' in panel_script
    assert "function previewStepIndexes(steps)" in panel_script
    assert 'cti-frame-skipped' not in panel_script
    assert "function createNoteStepSelect(run, selectedTarget = null)" in panel_script
    assert "function selectedNoteTarget(select, run)" in panel_script
    assert "segmentIndex: stepSegmentIndex(item)" in panel_script
    assert '"가장 최근에 생성된 실행 기록을 엽니다."' in panel_script
    assert 'const note = document.createElement("textarea");' in panel_script
    assert 'const note = document.createElement("input");' not in panel_script
    assert "function setupNoteTextarea(textarea, submit)" in panel_script
    assert 'event.key === "Enter" && (event.ctrlKey || event.metaKey)' in panel_script
    assert "function focusNoteStep(run, step, segmentIndex = null)" in panel_script
    assert 'button(localeText("스텝 보기", "View step")' in panel_script
    assert "center.scrollTo" not in panel_script
    assert "function samplingPathNodes(run)" in panel_script
    assert "matchingCanvasNodes(run, capturedPath)" in panel_script
    assert 'localeText("캔버스에서 샘플링 경로 선택", "Select sampling path on canvas")' in panel_script
    assert "function clearCanvasSelection(canvas)" in panel_script
    assert 'typeof canvas.deselectAll === "function"' in panel_script
    assert "function replaceCanvasSelection(canvas, items)" in panel_script
    assert "replaceCanvasSelection(canvas, [node])" in panel_script
    assert "replaceCanvasSelection(canvas, liveNodes)" in panel_script
    assert "canvas.selectNode(items[0], false)" in panel_script
    assert "liveEventsExpanded: false" in panel_script
    assert "eventDetails.open = state.liveEventsExpanded" in panel_script
    assert "state.liveEventsExpanded = eventDetails.open" in panel_script
    assert "selectedPromptCallIndex: 0" in panel_script
    assert "prompt.calls || []" in panel_script
    assert "Sampling Trace CLIP의 CLIP 출력을 긍정·부정 Text Encode에 연결" in panel_script
    assert 'localeText("실제 프롬프트 원문", "Actual prompt source")' in panel_script


def test_custom_node_package_imports_with_comfy_server_stubs(monkeypatch, tmp_path: Path):
    plugin_root = Path(__file__).resolve().parents[1]
    fake_server = types.ModuleType("server")
    instance = FakePromptServerInstance()
    fake_server.PromptServer = type("PromptServer", (), {"instance": instance})
    fake_folder_paths = types.ModuleType("folder_paths")
    fake_folder_paths.get_user_directory = lambda: str(tmp_path)
    monkeypatch.setitem(sys.modules, "server", fake_server)
    monkeypatch.setitem(sys.modules, "folder_paths", fake_folder_paths)

    module_name = "trace_inspector_plugin_test"
    spec = importlib.util.spec_from_file_location(
        module_name,
        plugin_root / "__init__.py",
        submodule_search_locations=[str(plugin_root)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        assert "ComfyTraceModel" in module.NODE_CLASS_MAPPINGS
        assert len(module.NODE_CLASS_MAPPINGS) == 9
        assert all(
            getattr(node_class, "DESCRIPTION", "").strip()
            for node_class in module.NODE_CLASS_MAPPINGS.values()
        )
        assert all(
            display_name.startswith("Sampling Trace ")
            for display_name in module.NODE_DISPLAY_NAME_MAPPINGS.values()
        )
        assert module.WEB_DIRECTORY == "./web"
        paths = {path for _method, path, _name in instance.routes.registered}
        assert "/trace-inspector/runs" in paths
        assert "/trace-inspector/compare" in paths
        assert "/trace-inspector/compare/report" in paths
        assert "/trace-inspector/runs/{run_id}/notes/{note_id}" in paths
    finally:
        for key in list(sys.modules):
            if key == module_name or key.startswith(module_name + "."):
                sys.modules.pop(key, None)
