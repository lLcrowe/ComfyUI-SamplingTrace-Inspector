from __future__ import annotations

import compileall
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "__init__.py",
    "nodes.py",
    "web/trace_inspector.js",
    "trace_inspector/runtime_hooks.py",
    "trace_inspector/server_routes.py",
    "docs/CODEX_HANDOFF.md",
    "scripts/scan_custom_nodes.py",
    "trace_inspector/custom_node_inventory.py",
    "docs/CUSTOM_NODE_SCAN_GUIDE.md",
    "scripts/scan_workflow_usage.py",
    "trace_inspector/workflow_usage.py",
]


def main() -> int:
    missing = [path for path in REQUIRED if not (ROOT / path).exists()]
    if missing:
        print(json.dumps({"ok": False, "missing": missing}, indent=2))
        return 1

    python_ok = compileall.compile_dir(ROOT, quiet=1)
    js_ok = True
    try:
        subprocess.run(
            ["node", "--check", str(ROOT / "web/trace_inspector.js")],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("node is unavailable; JavaScript syntax check skipped")
    except subprocess.CalledProcessError as exc:
        js_ok = False
        print(exc.stderr)

    print(json.dumps({"ok": python_ok and js_ok, "python": python_ok, "javascript": js_ok}, indent=2))
    return 0 if python_ok and js_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
