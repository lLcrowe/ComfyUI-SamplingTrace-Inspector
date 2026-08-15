from __future__ import annotations

from trace_inspector.adapters import ADAPTER_REGISTRY


def test_controlnet_adapter_explains_graph_vs_runtime():
    summary = ADAPTER_REGISTRY.summarize(
        {
            "classType": "ControlNetApplyAdvanced",
            "inputs": {"strength": 0.8, "start_percent": 0.0, "end_percent": 0.7},
        }
    )
    assert summary is not None
    assert summary["adapterId"] == "controlnet"
    assert summary["role"] == "conditioning_patch"
    assert summary["parameters"]["end_percent"] == 0.7


def test_ipadapter_is_classified_as_attention_patch():
    summary = ADAPTER_REGISTRY.summarize(
        {"classType": "IPAdapterAdvanced", "inputs": {"weight": 0.75, "start_at": 0.0}}
    )
    assert summary is not None
    assert summary["adapterId"] == "ipadapter"
    assert summary["role"] == "attention_patch"
