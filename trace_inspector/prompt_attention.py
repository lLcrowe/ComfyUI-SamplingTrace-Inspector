from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import torch


ROLE_NAMES = {0: "positive", 1: "negative"}


def observe_cross_attention(
    q: Any,
    k: Any,
    heads: Any,
    cond_or_uncond: Any,
    *,
    max_query_samples: int = 16,
    scale: float | None = None,
) -> list[dict[str, Any]]:
    """Return detached per-role token attention without changing q or k.

    The observer samples spatial query positions but keeps every text key. It
    intentionally returns small device tensors so the sampling callback can
    aggregate and transfer them once per step instead of synchronizing every
    attention layer.
    """
    if not isinstance(q, torch.Tensor) or not isinstance(k, torch.Tensor):
        return []
    if q.ndim != 3 or k.ndim != 3 or q.shape[0] != k.shape[0]:
        return []
    if q.shape[1] == k.shape[1] or not 1 < int(k.shape[1]) <= 512:
        return []
    try:
        head_count = int(heads)
    except (TypeError, ValueError):
        return []
    if head_count < 1 or q.shape[-1] % head_count or k.shape[-1] % head_count:
        return []

    role_indexes = list(cond_or_uncond) if isinstance(cond_or_uncond, (list, tuple)) else []
    if not role_indexes:
        role_indexes = [None]
    batch = int(q.shape[0])
    if batch % len(role_indexes):
        return []
    batch_per_role = batch // len(role_indexes)
    dim_head = int(q.shape[-1]) // head_count
    if int(k.shape[-1]) // head_count != dim_head:
        return []

    query_count = int(q.shape[1])
    sample_limit = max(1, int(max_query_samples))
    stride = max(1, math.ceil(query_count / sample_limit))
    sample_count = min(sample_limit, math.ceil(query_count / stride))
    attention_scale = float(scale) if scale is not None else dim_head**-0.5
    events: list[dict[str, Any]] = []

    with torch.inference_mode():
        q_heads = q.detach().reshape(batch, query_count, head_count, dim_head).permute(0, 2, 1, 3)
        k_heads = k.detach().reshape(batch, int(k.shape[1]), head_count, dim_head).permute(0, 2, 1, 3)
        q_heads = q_heads[:, :, ::stride, :][:, :, :sample_count, :]
        for chunk_index, role_index in enumerate(role_indexes):
            start = chunk_index * batch_per_role
            end = start + batch_per_role
            scores = torch.matmul(
                q_heads[start:end].float(),
                k_heads[start:end].float().transpose(-1, -2),
            ) * attention_scale
            weights = scores.softmax(dim=-1).mean(dim=(0, 1, 2)).detach()
            events.append(
                {
                    "roleIndex": int(role_index) if role_index is not None else None,
                    "weights": weights,
                    "tokenCount": int(weights.shape[0]),
                    "querySamples": sample_count * batch_per_role,
                }
            )
    return events


def aggregate_attention_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Serialize one step's observed attention as equal-weight layer means."""
    grouped: dict[int | None, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        weights = event.get("weights")
        if isinstance(weights, torch.Tensor) and weights.ndim == 1 and weights.numel():
            grouped[event.get("roleIndex")].append(event)

    roles: dict[str, Any] = {}
    total_layers = 0
    total_query_samples = 0
    for role_index, role_events in grouped.items():
        token_counts = [int(event["weights"].shape[0]) for event in role_events]
        token_count = max(set(token_counts), key=token_counts.count)
        matching = [event for event in role_events if int(event["weights"].shape[0]) == token_count]
        if not matching:
            continue
        mean_weights = torch.stack([event["weights"].float() for event in matching]).mean(dim=0)
        values = [round(float(value), 8) for value in mean_weights.cpu().tolist()]
        role_name = ROLE_NAMES.get(role_index, "unknown")
        query_samples = sum(int(event.get("querySamples") or 0) for event in matching)
        roles[role_name] = {
            "tokenCount": token_count,
            "layerCount": len(matching),
            "querySamples": query_samples,
            "weights": values,
        }
        total_layers += len(matching)
        total_query_samples += query_samples

    return {
        "method": "sampled_cross_attention",
        "approximate": True,
        "layerCount": total_layers,
        "querySamples": total_query_samples,
        "roles": roles,
    }
