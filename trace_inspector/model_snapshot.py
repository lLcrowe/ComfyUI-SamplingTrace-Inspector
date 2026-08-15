from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _count_nested_callables(value: Any, depth: int = 0) -> int:
    if depth > 8:
        return 0
    if callable(value):
        return 1
    if isinstance(value, Mapping):
        return sum(_count_nested_callables(v, depth + 1) for v in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_count_nested_callables(v, depth + 1) for v in value)
    return 0


def _nested_keys(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "<max-depth>"
    if isinstance(value, Mapping):
        return {str(k): _nested_keys(v, depth + 1) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [f"<{type(v).__name__}>" for v in list(value)[:32]]
    return f"<{type(value).__name__}>"


def snapshot_model_patcher(model: Any) -> dict[str, Any]:
    model_options = getattr(model, "model_options", {}) or {}
    transformer_options = model_options.get("transformer_options", {}) if isinstance(model_options, Mapping) else {}
    wrappers = getattr(model, "wrappers", {}) or {}
    callbacks = getattr(model, "callbacks", {}) or {}
    patches = getattr(model, "patches", {}) or {}
    object_patches = getattr(model, "object_patches", {}) or {}
    attachments = getattr(model, "attachments", {}) or {}

    return {
        "type": f"{type(model).__module__}.{type(model).__name__}",
        "loadDevice": str(getattr(model, "load_device", "unknown")),
        "offloadDevice": str(getattr(model, "offload_device", "unknown")),
        "weightPatchKeyCount": len(patches) if isinstance(patches, Mapping) else None,
        "weightPatchEntryCount": (
            sum(len(v) if isinstance(v, Sequence) else 1 for v in patches.values())
            if isinstance(patches, Mapping)
            else None
        ),
        "objectPatchCount": len(object_patches) if isinstance(object_patches, Mapping) else None,
        "attachmentKeys": sorted(str(key) for key in attachments.keys()) if isinstance(attachments, Mapping) else [],
        "modelOptionKeys": sorted(str(key) for key in model_options.keys()) if isinstance(model_options, Mapping) else [],
        "transformerOptionShape": _nested_keys(transformer_options),
        "transformerPatchCallableCount": _count_nested_callables(transformer_options),
        "wrapperCounts": {
            str(wrapper_type): sum(len(items) for items in keyed.values())
            if isinstance(keyed, Mapping)
            else 0
            for wrapper_type, keyed in wrappers.items()
        }
        if isinstance(wrappers, Mapping)
        else {},
        "callbackCounts": {
            str(callback_type): sum(len(items) for items in keyed.values())
            if isinstance(keyed, Mapping)
            else 0
            for callback_type, keyed in callbacks.items()
        }
        if isinstance(callbacks, Mapping)
        else {},
    }
