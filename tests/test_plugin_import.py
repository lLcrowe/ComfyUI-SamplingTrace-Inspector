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
        "ComfyTraceOneNode",
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

    one_node = node_defs["ComfyTraceOneNode"]
    clip = node_defs["ComfyTraceClip"]
    model = node_defs["ComfyTraceModel"]
    assert "단일 노드" in one_node["display_name"]
    assert one_node["inputs"]["final_model"]["name"].startswith("①")
    assert one_node["inputs"]["checkpoint_clip"]["name"].startswith("②")
    assert one_node["outputs"]["0"]["name"].startswith("③")
    assert one_node["outputs"]["1"]["name"].startswith("④")
    assert "긍정/부정 양쪽 연결" in clip["display_name"]
    assert clip["inputs"]["clip"]["name"].startswith("①")
    assert clip["outputs"]["0"]["name"].startswith("②")
    assert clip["outputs"]["1"]["name"] == "③ CLIP 프롬프트 추적 보내기"
    assert clip["outputs"]["0"]["name"] == "② 긍정·부정 Text Encode"
    assert model["inputs"]["prompt_trace"]["name"].startswith("③")
    assert "새 연결 금지" in model["inputs"]["clip"]["name"]


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
    assert "function promptWordGroups(run, prompts, role" in panel_script
    assert "promptWordValues(words, role)" in panel_script
    assert "단일 노드 설정의 CLIP 출력을 긍정·부정 Text Encode 양쪽에 연결" in panel_script
    assert 'localeText("입력 프롬프트·CLIP 토큰 상세"' not in panel_script
    assert "selectedBatchIndex: 0" in panel_script
    assert "function batchItemsForStep(step)" in panel_script
    assert "function batchCountForRun(run)" in panel_script
    assert "segment?.latentInput?.shape?.[0]" in panel_script
    assert "function createBatchSelector(run)" in panel_script
    assert 'localeText("배치별 추적", "Batch trace")' in panel_script
    assert "selectedBatchStep(frame)" in panel_script


def test_trace_socket_names_follow_comfy_locale_without_changing_input_keys():
    plugin_root = Path(__file__).resolve().parents[1]
    localization_script = (plugin_root / "web" / "slot_localization.js").read_text(encoding="utf-8")

    assert "function applyLocalizedTraceSlotNames(node)" in localization_script
    assert "function traceNodeClass(node)" in localization_script
    assert "node?.comfyClass || node?.type || node?.constructor?.nodeData?.name" in localization_script
    assert 'nodeClass === "ComfyTraceOneNode"' in localization_script
    assert 'localeText("① 최종 MODEL", "① Final MODEL")' in localization_script
    assert 'localeText("② 체크포인트 CLIP", "② Checkpoint CLIP")' in localization_script
    assert 'localeText("③ 샘플러로", "③ To Sampler")' in localization_script
    assert 'localeText("④ 긍정·부정 Text Encode로", "④ To Positive + Negative Text Encode")' in localization_script
    assert 'nodeClass === "ComfyTraceClip"' in localization_script
    assert 'localeText("① 체크포인트 CLIP", "① Checkpoint CLIP")' in localization_script
    assert 'localeText("② 긍정·부정 Text Encode", "② Positive + Negative Text Encode")' in localization_script
    assert 'localeText("③ CLIP 프롬프트 추적 보내기", "③ Send CLIP Prompt Trace")' in localization_script
    assert 'setSlotDisplayName(output, outputNames[index], { rename: true })' in localization_script
    assert 'prompt_trace: localeText("③ CLIP 프롬프트 추적 받기", "③ Receive CLIP Prompt Trace")' in localization_script
    assert "function installLocalizedTraceSlotLifecycle(nodeType)" in localization_script
    assert 'for (const methodName of ["onAdded", "onConfigure"])' in localization_script
    assert "async beforeRegisterNodeDef(nodeType, nodeData)" in localization_script
    assert "afterConfigureGraph()" in localization_script
    assert "async nodeCreated(node)" in localization_script
    assert "loadedGraphNode(node)" in localization_script


def test_one_node_settings_popup_keeps_capture_widget_hidden_and_serialized():
    plugin_root = Path(__file__).resolve().parents[1]
    settings_script = (plugin_root / "web" / "one_node_settings.js").read_text(encoding="utf-8")

    assert 'const PRESET_WIDGET = "trace_preset"' in settings_script
    assert 'widget.type = "hidden"' in settings_script
    assert "widget.computeSize = () => [0, -4]" in settings_script
    assert "widget.serializeValue" not in settings_script
    assert 'button.__ctiSettingsButton = SETTINGS_BUTTON' in settings_script
    assert '"button",\n      buttonLabel(node)' in settings_script
    assert '"basic"' in settings_script
    assert '"advanced"' in settings_script
    assert 'dialog.setAttribute("aria-modal", "true")' in settings_script
    assert 'if (event.key === "Escape") closePopup()' in settings_script
    assert "markWorkflowChanged(node)" in settings_script
    assert 'localeText("배치별 추적 · 자동", "Per-item batch trace · Automatic")' in settings_script
    assert "추적 패널의 1/N 선택기" in settings_script

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
        assert "ComfyTraceOneNode" in module.NODE_CLASS_MAPPINGS
        assert "ComfyTraceModel" in module.NODE_CLASS_MAPPINGS
        assert len(module.NODE_CLASS_MAPPINGS) == 10
        assert getattr(module.NODE_CLASS_MAPPINGS["ComfyTraceOneNode"], "DEPRECATED", False) is False
        visible_nodes = [
            name
            for name, node_class in module.NODE_CLASS_MAPPINGS.items()
            if not getattr(node_class, "DEPRECATED", False)
        ]
        assert visible_nodes == ["ComfyTraceOneNode"]
        assert module.NODE_CLASS_MAPPINGS["ComfyTraceOneNode"].RETURN_TYPES == (
            "MODEL",
            "CLIP",
            "TRACE_SESSION",
        )
        assert module.NODE_CLASS_MAPPINGS["ComfyTraceOneNode"].RETURN_NAMES == (
            "③ 샘플러로",
            "④ 긍정·부정 Text Encode로",
            "선택 · 고급 연동",
        )
        one_inputs = module.NODE_CLASS_MAPPINGS["ComfyTraceOneNode"].INPUT_TYPES()
        assert one_inputs["required"]["final_model"][1]["display_name"] == "① 최종 MODEL"
        assert one_inputs["required"]["checkpoint_clip"][1]["display_name"] == "② 체크포인트 CLIP"
        assert set(one_inputs["required"]) == {"final_model", "checkpoint_clip"}
        assert one_inputs["optional"]["trace_preset"] == (
            ("basic", "advanced"),
            {"default": "basic"},
        )
        assert module.NODE_CLASS_MAPPINGS["ComfyTraceClip"].RETURN_NAMES == (
            "② 긍정·부정 Text Encode",
            "③ CLIP 프롬프트 추적 보내기",
        )
        assert module.NODE_CLASS_MAPPINGS["ComfyTraceClip"].INPUT_TYPES()["required"]["clip"][1][
            "display_name"
        ] == "① 체크포인트 CLIP"
        assert module.NODE_CLASS_MAPPINGS["ComfyTraceModel"].INPUT_TYPES()["optional"]["prompt_trace"][1][
            "display_name"
        ] == "③ CLIP 프롬프트 추적 받기"

        delegated = {}
        one_node_class = module.NODE_CLASS_MAPPINGS["ComfyTraceOneNode"]
        model_node_class = module.NODE_CLASS_MAPPINGS["ComfyTraceModel"]
        original_model_attach = model_node_class.attach

        def fake_model_attach(_self, **kwargs):
            delegated.update(kwargs)
            return "traced-model", "shared-session"

        model_node_class.attach = fake_model_attach
        try:
            original_clip = object()
            one_result = one_node_class().attach(
                final_model="final-model",
                checkpoint_clip=original_clip,
                unique_id="42",
                prompt={"7": {"class_type": "CLIPTextEncode", "inputs": {"text": "hello"}}},
            )
            delegated_basic = delegated.copy()
            delegated.clear()
            one_node_class().attach(
                final_model="final-model",
                checkpoint_clip=original_clip,
                unique_id="43",
                trace_preset="advanced",
            )
            delegated_advanced = delegated.copy()
        finally:
            model_node_class.attach = original_model_attach

        assert one_result[0] == "traced-model"
        assert type(one_result[1]).__name__ == "TracingClipProxy"
        assert one_result[1]._clip is original_clip
        assert one_result[2] == "shared-session"
        assert delegated_basic["model"] == "final-model"
        assert delegated_basic["mode"] == "basic"
        assert delegated_basic["preview_every"] == 1
        assert delegated_basic["preview_max_side"] == 768
        assert delegated_basic["preview_quality"] == 85
        assert delegated_basic["persist_previews"] is True
        assert delegated_basic["persist_tensor_stats"] is False
        assert delegated_basic["preview_decoder"] == "clear"
        assert delegated_basic["prompt_trace"] is one_result[1]._capture
        assert delegated_basic["prompt_trace"].trace_node_id == "42"
        assert delegated_advanced["mode"] == "advanced"
        assert delegated_advanced["persist_tensor_stats"] is True
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
