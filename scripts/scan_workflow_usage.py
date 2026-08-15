from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trace_inspector.workflow_usage import scan_workflow_usage, write_usage_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only ComfyUI workflow usage inventory")
    parser.add_argument("--comfy-root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, default=Path("docs/CUSTOM_NODE_INVENTORY.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("docs"))
    parser.add_argument("--history-url")
    parser.add_argument("--recent-days", type=int, default=30)
    args = parser.parse_args()

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    result = scan_workflow_usage(args.comfy_root, inventory, history_url=args.history_url, recent_days=args.recent_days)
    outputs = write_usage_reports(result, args.output_dir)
    print(json.dumps({"summary": result["summary"], "outputs": outputs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
