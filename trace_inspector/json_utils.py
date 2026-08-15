from __future__ import annotations

import json
import math
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def json_safe(value: Any, *, max_depth: int = 8, _depth: int = 0) -> Any:
    """Convert common runtime objects to bounded JSON-safe data.

    Raw Tensor data is intentionally not serialized here. Tensor summaries must
    be produced explicitly by tensor_stats.py.
    """
    if _depth >= max_depth:
        return "<max-depth>"
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return json_safe(asdict(value), max_depth=max_depth, _depth=_depth + 1)
    if isinstance(value, dict):
        return {
            str(k): json_safe(v, max_depth=max_depth, _depth=_depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v, max_depth=max_depth, _depth=_depth + 1) for v in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item(), max_depth=max_depth, _depth=_depth + 1)
        except Exception:
            pass
    return f"<{type(value).__module__}.{type(value).__name__}>"


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(json_safe(payload), ensure_ascii=False))
        stream.write("\n")


def atomic_write_jsonl(path: Path, payloads: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        for payload in payloads:
            stream.write(json.dumps(json_safe(payload), ensure_ascii=False))
            stream.write("\n")
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[Any]:
    if not path.exists():
        return []
    result: list[Any] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    result.append({"corruptLine": line[:300]})
    except OSError:
        return []
    return result
