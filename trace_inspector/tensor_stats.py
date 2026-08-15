from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

try:
    import torch
except ImportError:  # Enables pure-Python tooling/tests outside ComfyUI.
    torch = None  # type: ignore[assignment]


def _is_tensor(value: Any) -> bool:
    return torch is not None and isinstance(value, torch.Tensor)


def _unwrap_nested_tensor(value: Any) -> Any:
    if getattr(value, "is_nested", False):
        tensors = getattr(value, "tensors", None)
        if tensors:
            return tensors[0]
    return value


def _bounded_sample(tensor: Any, max_samples: int) -> Any:
    flat = tensor.detach().reshape(-1)
    count = int(flat.numel())
    if count <= max_samples:
        return flat
    stride = max(1, math.ceil(count / max_samples))
    return flat[::stride][:max_samples]


def tensor_summary(
    value: Any,
    *,
    include_statistics: bool = True,
    max_samples: int = 65_536,
) -> dict[str, Any]:
    """Summarize a Tensor without retaining or exporting its raw values."""
    value = _unwrap_nested_tensor(value)
    if not _is_tensor(value):
        return {"kind": "non_tensor", "type": type(value).__name__}

    result: dict[str, Any] = {
        "kind": "tensor",
        "shape": [int(v) for v in value.shape],
        "ndim": int(value.ndim),
        "numel": int(value.numel()),
        "dtype": str(value.dtype).replace("torch.", ""),
        "device": str(value.device),
        "requiresGrad": bool(value.requires_grad),
    }
    if not include_statistics or value.numel() == 0:
        return result

    try:
        sampled = _bounded_sample(value, max_samples)
        # Converting only a bounded sample reduces synchronization and transfer cost.
        if not sampled.is_floating_point() and not sampled.is_complex():
            sampled = sampled.to(device="cpu", dtype=torch.float32)
        elif sampled.is_complex():
            sampled = sampled.abs().to(device="cpu", dtype=torch.float32)
        else:
            sampled = sampled.to(device="cpu", dtype=torch.float32)

        finite_mask = torch.isfinite(sampled)
        finite = sampled[finite_mask]
        result["sampled"] = int(sampled.numel())
        result["finite"] = int(finite.numel())
        result["nonFinite"] = int(sampled.numel() - finite.numel())
        if finite.numel() == 0:
            return result

        result.update(
            {
                "min": float(finite.min().item()),
                "max": float(finite.max().item()),
                "mean": float(finite.mean().item()),
                "std": float(finite.std(unbiased=False).item()),
                "meanAbs": float(finite.abs().mean().item()),
                "maxAbs": float(finite.abs().max().item()),
                "rms": float(torch.sqrt(torch.mean(finite * finite)).item()),
            }
        )
    except Exception as exc:  # Tracing must not stop generation.
        result["statisticsError"] = f"{type(exc).__name__}: {exc}"
    return result


def _collect_tensor_summaries(
    value: Any,
    *,
    include_statistics: bool,
    max_samples: int,
    path: str,
    out: list[dict[str, Any]],
    depth: int,
    max_depth: int,
    max_tensors: int,
) -> bool:
    """Collect bounded Tensor summaries. Return True when the Tensor budget truncates traversal."""
    if len(out) >= max_tensors:
        return True
    if depth > max_depth:
        return False
    value = _unwrap_nested_tensor(value)
    if _is_tensor(value):
        summary = tensor_summary(
            value,
            include_statistics=include_statistics,
            max_samples=max_samples,
        )
        summary["path"] = path
        out.append(summary)
        return False
    if isinstance(value, Mapping):
        for key, child in value.items():
            if len(out) >= max_tensors:
                return True
            if _collect_tensor_summaries(
                child,
                include_statistics=include_statistics,
                max_samples=max_samples,
                path=f"{path}.{key}" if path else str(key),
                out=out,
                depth=depth + 1,
                max_depth=max_depth,
                max_tensors=max_tensors,
            ):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            if len(out) >= max_tensors:
                return True
            if _collect_tensor_summaries(
                child,
                include_statistics=include_statistics,
                max_samples=max_samples,
                path=f"{path}[{index}]",
                out=out,
                depth=depth + 1,
                max_depth=max_depth,
                max_tensors=max_tensors,
            ):
                return True
    return False


def recursive_tensor_summary(
    value: Any,
    *,
    include_statistics: bool = True,
    max_samples: int = 16_384,
    max_depth: int = 8,
    max_tensors: int = 256,
) -> dict[str, Any]:
    tensors: list[dict[str, Any]] = []
    truncated = _collect_tensor_summaries(
        value,
        include_statistics=include_statistics,
        max_samples=max_samples,
        path="",
        out=tensors,
        depth=0,
        max_depth=max_depth,
        max_tensors=max(1, int(max_tensors)),
    )

    result: dict[str, Any] = {
        "tensorCount": len(tensors),
        "truncated": truncated,
        "tensors": tensors,
    }
    if not tensors:
        return result

    result["totalElements"] = sum(int(x.get("numel", 0)) for x in tensors)
    valid = [x for x in tensors if isinstance(x.get("meanAbs"), (int, float))]
    if valid:
        weights = [max(1, int(x.get("sampled", x.get("numel", 1)))) for x in valid]
        total_weight = sum(weights)
        result["weightedMeanAbs"] = sum(
            float(x["meanAbs"]) * w for x, w in zip(valid, weights, strict=False)
        ) / total_weight
        result["weightedRms"] = math.sqrt(
            sum(float(x.get("rms", 0.0)) ** 2 * w for x, w in zip(valid, weights, strict=False))
            / total_weight
        )
        result["maxAbs"] = max(float(x.get("maxAbs", 0.0)) for x in valid)
    return result


def conditioning_summary(
    conditioning: Any,
    *,
    include_statistics: bool,
    max_samples: int,
) -> dict[str, Any]:
    """Summarize ComfyUI CONDITIONING's common list[(Tensor, dict)] shape."""
    result: dict[str, Any] = {
        "kind": "conditioning",
        "entryCount": len(conditioning) if isinstance(conditioning, Sequence) else None,
    }
    result["tensors"] = recursive_tensor_summary(
        conditioning,
        include_statistics=include_statistics,
        max_samples=max_samples,
        max_tensors=64,
    )
    metadata_keys: set[str] = set()
    if isinstance(conditioning, Sequence):
        for entry in conditioning:
            if isinstance(entry, Sequence) and len(entry) > 1 and isinstance(entry[1], Mapping):
                metadata_keys.update(str(key) for key in entry[1].keys())
    result["metadataKeys"] = sorted(metadata_keys)
    return result


def tensor_difference_summary(
    left: Any,
    right: Any,
    *,
    max_samples: int = 65_536,
) -> dict[str, Any]:
    """Summarize left-right using aligned bounded samples, avoiding a full-size delta Tensor."""
    left = _unwrap_nested_tensor(left)
    right = _unwrap_nested_tensor(right)
    if not _is_tensor(left) or not _is_tensor(right):
        return {"kind": "unavailable", "reason": "non_tensor"}
    if list(left.shape) != list(right.shape):
        return {
            "kind": "unavailable",
            "reason": "shape_mismatch",
            "leftShape": [int(v) for v in left.shape],
            "rightShape": [int(v) for v in right.shape],
        }
    try:
        left_sample = _bounded_sample(left, max_samples).to(device="cpu", dtype=torch.float32)
        right_sample = _bounded_sample(right, max_samples).to(device="cpu", dtype=torch.float32)
        count = min(int(left_sample.numel()), int(right_sample.numel()))
        delta = left_sample[:count] - right_sample[:count]
        finite = delta[torch.isfinite(delta)]
        result: dict[str, Any] = {
            "kind": "tensor_difference",
            "shape": [int(v) for v in left.shape],
            "sampled": count,
            "finite": int(finite.numel()),
        }
        if finite.numel() > 0:
            result.update(
                {
                    "mean": float(finite.mean().item()),
                    "std": float(finite.std(unbiased=False).item()),
                    "meanAbs": float(finite.abs().mean().item()),
                    "maxAbs": float(finite.abs().max().item()),
                    "rms": float(torch.sqrt(torch.mean(finite * finite)).item()),
                }
            )
        return result
    except Exception as exc:
        return {"kind": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}
