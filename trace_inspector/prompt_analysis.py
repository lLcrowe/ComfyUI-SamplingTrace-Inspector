from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


INTERESTING_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sampler", ("ksampler", "sampler", "scheduler", "guider")),
    ("controlnet", ("controlnet", "control net", "t2iadapter", "t2i adapter")),
    ("lora", ("lora", "lycoris", "locon")),
    ("ipadapter", ("ipadapter", "ip adapter", "pulid", "instantid")),
    ("vae", ("vae",)),
    ("clip", ("cliptext", "clip text", "textencode", "text encode")),
    ("preview", ("preview", "saveimage", "save image")),
)


def _classify(class_type: str) -> str:
    lowered = class_type.lower()
    for group, tokens in INTERESTING_GROUPS:
        if any(token in lowered for token in tokens):
            return group
    return "other"


def _is_link(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and isinstance(value[1], int)
    )


def _sanitize_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        # Long prompts are useful for reproducibility but can overwhelm the trace UI.
        return value if len(value) <= 1000 else value[:997] + "..."
    return None


def _sanitize_inputs(inputs: Any) -> dict[str, Any]:
    if not isinstance(inputs, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key, value in inputs.items():
        key = str(key)
        if _is_link(value):
            result[key] = {"link": [str(value[0]), int(value[1])]}
            continue
        scalar = _sanitize_scalar(value)
        if scalar is not None or value is None:
            result[key] = scalar
            continue
        if isinstance(value, Mapping):
            nested: dict[str, Any] = {}
            for nested_key, nested_value in value.items():
                scalar = _sanitize_scalar(nested_value)
                if scalar is not None or nested_value is None:
                    nested[str(nested_key)] = scalar
            if nested:
                result[key] = nested
    return result


def workflow_hash(prompt: Any) -> str:
    try:
        normalized = json.dumps(prompt, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        normalized = repr(prompt)
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()


def analyze_prompt(prompt: Any) -> dict[str, Any]:
    """Extract reproducible scalar settings without serializing model/image objects."""
    if not isinstance(prompt, Mapping):
        return {"workflowHash": workflow_hash(prompt), "nodes": [], "groups": {}}

    nodes: list[dict[str, Any]] = []
    groups: dict[str, list[str]] = {}
    for node_id, raw in prompt.items():
        if not isinstance(raw, Mapping):
            continue
        class_type = str(raw.get("class_type", "Unknown"))
        group = _classify(class_type)
        node = {
            "id": str(node_id),
            "classType": class_type,
            "group": group,
            "inputs": _sanitize_inputs(raw.get("inputs", {})),
        }
        try:
            from .adapters import ADAPTER_REGISTRY

            semantic = ADAPTER_REGISTRY.summarize(node)
            if semantic is not None:
                node["semantic"] = semantic
        except Exception:
            pass
        nodes.append(node)
        groups.setdefault(group, []).append(str(node_id))

    nodes.sort(key=lambda item: item["id"])
    return {
        "workflowHash": workflow_hash(prompt),
        "nodeCount": len(nodes),
        "nodes": nodes,
        "groups": groups,
    }


def extract_generation_settings(prompt_analysis: Mapping[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for node in prompt_analysis.get("nodes", []):
        if not isinstance(node, Mapping):
            continue
        group = node.get("group")
        inputs = node.get("inputs", {})
        if group == "sampler" and isinstance(inputs, Mapping):
            for key in (
                "seed",
                "noise_seed",
                "steps",
                "cfg",
                "sampler_name",
                "scheduler",
                "denoise",
                "start_at_step",
                "end_at_step",
            ):
                if key in inputs:
                    settings[key] = inputs[key]
        elif group in {"controlnet", "lora", "ipadapter"}:
            settings.setdefault(group, []).append(
                {
                    "nodeId": node.get("id"),
                    "classType": node.get("classType"),
                    "inputs": inputs,
                }
            )
    return settings
