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

STANDARD_PROMPT_NODES = {
    "CLIPTextEncode",
    "CLIPTextEncodeSDXL",
    "CLIPTextEncodeSDXLRefiner",
}
MAX_PROMPT_TEXT_LENGTH = 8000


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


def _prompt_role_map(prompt: Mapping[str, Any]) -> dict[str, set[str]]:
    """Map every upstream node to positive/negative roles by socket semantics."""
    roles: dict[str, set[str]] = {}

    def visit(value: Any, role: str, visited: set[str]) -> None:
        if not _is_link(value):
            return
        node_id = str(value[0])
        if node_id in visited:
            return
        visited.add(node_id)
        node = prompt.get(node_id) or prompt.get(int(node_id)) if node_id.isdigit() else prompt.get(node_id)
        if not isinstance(node, Mapping):
            return
        roles.setdefault(node_id, set()).add(role)
        for upstream in (node.get("inputs") or {}).values():
            if _is_link(upstream):
                visit(upstream, role, visited)

    for raw in prompt.values():
        if not isinstance(raw, Mapping):
            continue
        inputs = raw.get("inputs") or {}
        if not isinstance(inputs, Mapping):
            continue
        for role in ("positive", "negative"):
            visit(inputs.get(role), role, set())
    return roles


def _prompt_texts(class_type: str, inputs: Mapping[str, Any]) -> dict[str, str]:
    if class_type == "CLIPTextEncodeSDXL":
        values = {"g": inputs.get("text_g", ""), "l": inputs.get("text_l", "")}
    else:
        values = {"default": inputs.get("text", "")}
    return {
        key: (str(value)[:MAX_PROMPT_TEXT_LENGTH] if value is not None else "")
        for key, value in values.items()
    }


def _tokenizer_for_lane(clip: Any, lane: str) -> Any:
    tokenizer = getattr(clip, "tokenizer", None)
    if tokenizer is None:
        return None
    for name in (f"clip_{lane}", lane):
        candidate = getattr(tokenizer, name, None)
        if candidate is not None:
            return candidate
    return tokenizer


def _token_value(value: Any) -> tuple[Any, str]:
    if isinstance(value, bool):
        return int(value), "token"
    if isinstance(value, int):
        return value, "token"
    try:
        # NumPy integer scalars are safe to persist, while tensors/embeddings are not.
        converted = int(value)
        if not hasattr(value, "shape") or getattr(value, "ndim", 0) == 0:
            return converted, "token"
    except (TypeError, ValueError, OverflowError):
        pass
    return None, "embedding"


def _display_piece(tokenizer: Any, token_id: int | None) -> tuple[str, str]:
    if tokenizer is None or token_id is None:
        return "", ""
    piece = str(getattr(tokenizer, "inv_vocab", {}).get(token_id, ""))
    decoded = ""
    try:
        decoded = str(tokenizer.decode([token_id], skip_special_tokens=False))
    except Exception:
        decoded = piece
    return piece.replace("\x00", ""), decoded.replace("\x00", "")


def _serialize_lane(clip: Any, lane: str, chunks: Any) -> dict[str, Any]:
    tokenizer = _tokenizer_for_lane(clip, lane)
    start_id = getattr(tokenizer, "start_token", None)
    end_id = getattr(tokenizer, "end_token", None)
    pad_id = getattr(tokenizer, "pad_token", None)
    serialized_chunks: list[list[dict[str, Any]]] = []
    content_count = 0
    padding_count = 0

    for chunk_index, chunk in enumerate(chunks if isinstance(chunks, Sequence) else []):
        output_chunk: list[dict[str, Any]] = []
        seen_end = False
        for token_index, item in enumerate(chunk if isinstance(chunk, Sequence) else []):
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes, bytearray)) or len(item) < 2:
                continue
            token_id, token_type = _token_value(item[0])
            weight = float(item[1]) if isinstance(item[1], (int, float)) else 1.0
            word_id = int(item[2]) if len(item) > 2 and isinstance(item[2], int) else None
            special = None
            if token_type == "embedding":
                special = "embedding"
                content_count += 1
            elif token_id == start_id and token_index == 0:
                special = "start"
            elif token_id == end_id and not seen_end:
                special = "end"
                seen_end = True
            elif token_id == pad_id or (seen_end and pad_id == end_id and token_id == end_id):
                special = "padding"
                padding_count += 1
            else:
                content_count += 1
            piece, decoded = _display_piece(tokenizer, token_id)
            output_chunk.append(
                {
                    "index": token_index,
                    "tokenId": token_id,
                    "tokenType": token_type,
                    "piece": piece,
                    "decoded": decoded,
                    "weight": weight,
                    "wordId": word_id,
                    "special": special,
                }
            )
        serialized_chunks.append(output_chunk)

    return {
        "name": str(lane),
        "chunkCount": len(serialized_chunks),
        "tokenCount": sum(len(chunk) for chunk in serialized_chunks),
        "contentTokenCount": content_count,
        "paddingTokenCount": padding_count,
        "chunks": serialized_chunks,
    }


def serialize_clip_tokens(clip: Any, tokenized: Any) -> list[dict[str, Any]]:
    """Serialize a CLIP tokenize result without changing or retaining its tensors."""
    if isinstance(tokenized, Mapping):
        return [_serialize_lane(clip, str(lane), chunks) for lane, chunks in tokenized.items()]
    return [_serialize_lane(clip, "clip", tokenized)]


def _tokenize_prompt(clip: Any, class_type: str, texts: Mapping[str, str]) -> Any:
    if class_type == "CLIPTextEncodeSDXL":
        tokens = clip.tokenize(texts.get("g", ""), return_word_ids=True)
        local_tokens = clip.tokenize(texts.get("l", ""), return_word_ids=True)
        if not isinstance(tokens, Mapping) or not isinstance(local_tokens, Mapping) or "l" not in local_tokens:
            return tokens
        tokens = {key: list(value) for key, value in tokens.items()}
        tokens["l"] = list(local_tokens["l"])
        empty = clip.tokenize("", return_word_ids=True)
        if "g" in tokens and "l" in tokens and isinstance(empty, Mapping):
            while len(tokens["l"]) < len(tokens["g"]):
                tokens["l"] += empty.get("l", [])
            while len(tokens["l"]) > len(tokens["g"]):
                tokens["g"] += empty.get("g", [])
        return tokens
    return clip.tokenize(texts.get("default", ""), return_word_ids=True)


def extract_standard_prompt_tokenization(prompt: Any, clip: Any = None) -> dict[str, Any]:
    """Capture standard prompt text and the connected CLIP's actual tokenization."""
    result: dict[str, Any] = {
        "status": "no_standard_prompt",
        "source": "connected_clip" if clip is not None else None,
        "prompts": [],
        "messages": [],
    }
    if not isinstance(prompt, Mapping):
        result["messages"].append("The API prompt graph is unavailable.")
        return result

    roles = _prompt_role_map(prompt)
    prompt_nodes: list[tuple[str, Mapping[str, Any]]] = []
    for node_id, raw in prompt.items():
        if isinstance(raw, Mapping) and str(raw.get("class_type", "")) in STANDARD_PROMPT_NODES:
            prompt_nodes.append((str(node_id), raw))
    prompt_nodes.sort(key=lambda item: (int(item[0]) if item[0].isdigit() else 10**12, item[0]))
    if not prompt_nodes:
        result["messages"].append("No supported standard text prompt node was found.")
        return result

    if clip is None:
        result["status"] = "clip_not_connected"
        result["messages"].append("Connect the prompt CLIP to the Sampling Trace Model to capture actual tokens.")

    failures = 0
    for node_id, raw in prompt_nodes:
        class_type = str(raw.get("class_type"))
        inputs = raw.get("inputs") if isinstance(raw.get("inputs"), Mapping) else {}
        texts = _prompt_texts(class_type, inputs)
        entry: dict[str, Any] = {
            "nodeId": node_id,
            "classType": class_type,
            "roles": sorted(roles.get(node_id, {"unknown"})),
            "texts": texts,
            "encoders": [],
        }
        if clip is not None:
            try:
                tokenized = _tokenize_prompt(clip, class_type, texts)
                if isinstance(tokenized, Mapping):
                    entry["encoders"] = [
                        _serialize_lane(clip, str(lane), chunks)
                        for lane, chunks in tokenized.items()
                    ]
                else:
                    entry["encoders"] = [_serialize_lane(clip, "clip", tokenized)]
            except Exception as exc:
                failures += 1
                entry["error"] = f"{type(exc).__name__}: {exc}"[:1000]
        result["prompts"].append(entry)

    if clip is not None:
        result["status"] = "captured" if failures == 0 else "partial" if failures < len(prompt_nodes) else "error"
        if failures:
            result["messages"].append(f"Tokenization failed for {failures} prompt node(s).")
    lanes = {
        encoder.get("name")
        for entry in result["prompts"]
        for encoder in entry.get("encoders", [])
    }
    result["modelFamily"] = "sdxl" if {"g", "l"}.issubset(lanes) else "single_encoder" if lanes else None
    return result
