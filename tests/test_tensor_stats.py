from __future__ import annotations

import pytest
import torch

from trace_inspector.tensor_stats import (
    recursive_tensor_summary,
    tensor_difference_summary,
    tensor_summary,
)


def test_tensor_summary_basic_statistics():
    value = torch.tensor([[1.0, -2.0], [3.0, 0.0]])
    summary = tensor_summary(value, include_statistics=True)
    assert summary["shape"] == [2, 2]
    assert summary["numel"] == 4
    assert summary["mean"] == 0.5
    assert summary["maxAbs"] == 3.0


def test_difference_summary_uses_aligned_samples():
    left = torch.tensor([1.0, 4.0, 9.0])
    right = torch.tensor([0.0, 1.0, 3.0])
    summary = tensor_difference_summary(left, right)
    assert summary["sampled"] == 3
    assert summary["meanAbs"] == pytest.approx((1.0 + 3.0 + 6.0) / 3.0)


def test_recursive_summary_finds_nested_tensors():
    nested = {"input": [torch.ones(2), {"middle": torch.zeros(3)}]}
    summary = recursive_tensor_summary(nested)
    assert summary["tensorCount"] == 2
    assert summary["totalElements"] == 5


def test_recursive_summary_stops_at_tensor_budget():
    nested = [torch.tensor([float(i)]) for i in range(10)]
    summary = recursive_tensor_summary(nested, max_tensors=3)
    assert summary["tensorCount"] == 3
    assert summary["truncated"] is True
