from __future__ import annotations

from trace_inspector.diagnostics import diagnose_run


def test_late_instability_produces_hypothesis_not_causal_claim():
    steps = []
    for i in range(10):
        steps.append(
            {
                "step": i,
                "previewChange": 0.01 if i < 7 else 0.08,
                "cfg": {"deltaMeanAbs": 0.2 + i * 0.01},
                "control": {"active": False},
                "previewFile": f"{i}.jpg",
            }
        )
    diagnostics = diagnose_run({"steps": steps, "generationSettings": {}})
    item = next(value for value in diagnostics if value["id"] == "late-visual-instability")
    assert "가능성" in item["hypothesis"]
    assert item["experiments"]


def test_control_configured_but_not_observed_is_reported():
    run = {
        "generationSettings": {
            "controlnet": [
                {"inputs": {"strength": 1.0, "end_percent": 1.0}}
            ]
        },
        "steps": [
            {
                "step": 0,
                "previewChange": 0.01,
                "control": {"active": False},
                "previewFile": "0.jpg",
            }
        ],
    }
    diagnostics = diagnose_run(run)
    assert any(item["id"] == "control-configured-but-not-observed" for item in diagnostics)
