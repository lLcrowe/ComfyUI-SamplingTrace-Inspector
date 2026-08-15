"""Run this from ComfyUI's Python environment after installing the plugin."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    comfy_root = plugin_root.parents[1]
    sys.path.insert(0, str(comfy_root))

    checks = {}
    for module in ("server", "folder_paths", "comfy.patcher_extension", "latent_preview"):
        try:
            __import__(module)
            checks[module] = "ok"
        except Exception as exc:
            checks[module] = f"error: {type(exc).__name__}: {exc}"

    init_path = plugin_root / "__init__.py"
    try:
        spec = importlib.util.spec_from_file_location(
            "comfyui_trace_inspector",
            init_path,
            submodule_search_locations=[str(plugin_root)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to create plugin module spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        checks["plugin_import"] = "ok"
        checks["nodes"] = sorted(module.NODE_CLASS_MAPPINGS)
        checks["web_directory"] = module.WEB_DIRECTORY
    except Exception as exc:
        checks["plugin_import"] = f"error: {type(exc).__name__}: {exc}"

    ok = all(value == "ok" for key, value in checks.items() if key in {"server", "folder_paths", "comfy.patcher_extension", "latent_preview", "plugin_import"})
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
