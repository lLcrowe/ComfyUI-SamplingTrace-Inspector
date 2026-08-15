from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


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
