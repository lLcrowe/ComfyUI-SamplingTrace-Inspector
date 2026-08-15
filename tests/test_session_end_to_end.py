from __future__ import annotations

from pathlib import Path

import torch
from PIL import Image

from trace_inspector import PLUGIN_VERSION
from trace_inspector.config import TraceOptions
from trace_inspector.session import TraceSession
from trace_inspector.store import TraceStore


class FakePreviewer:
    def decode_latent_to_preview(self, x0):
        level = int(max(0, min(255, float(x0.mean().item()) * 127 + 128)))
        return Image.new("RGB", (64, 64), (level, 64, 255 - level))


def test_session_persists_complete_run(monkeypatch, tmp_path: Path):
    import trace_inspector.session as session_module

    store = TraceStore(tmp_path / "runs")
    monkeypatch.setattr(session_module, "STORE", store)

    options = TraceOptions(
        mode="advanced",
        label="e2e",
        preview_every=1,
        preview_max_side=128,
        preview_format="JPEG",
        preview_quality=80,
        persist_previews=True,
        persist_tensor_stats=True,
        max_tensor_samples=128,
    )
    session = TraceSession.create(
        node_id="100",
        options=options,
        prompt={
            "1": {
                "class_type": "KSampler",
                "inputs": {"seed": 42, "steps": 2, "cfg": 6.0, "sampler_name": "euler"},
            },
            "2": {
                "class_type": "ControlNetApplyAdvanced",
                "inputs": {"strength": 0.8, "start_percent": 0.0, "end_percent": 1.0},
            },
        },
        extra_pnginfo={},
        prompt_id="prompt-e2e",
    )
    session.begin_sampling(
        noise=torch.randn(1, 4, 8, 8),
        latent_image=torch.zeros(1, 4, 8, 8),
        sampler=object(),
        sigmas=torch.tensor([1.0, 0.5, 0.0]),
        seed=42,
    )

    for step in range(2):
        cond = torch.full((1, 4, 8, 8), 0.5 + step)
        uncond = torch.zeros_like(cond)
        session.record_cfg({"conds_out": [cond, uncond], "sigma": 1.0 - step * 0.5, "cond_scale": 6.0})
        session.record_control(
            timestep=torch.tensor([1.0 - step * 0.5]),
            control={"input": [torch.ones(1, 4, 8, 8) * (step + 1)]},
            transformer_options={"cond_or_uncond": [0, 1], "patches": {"attn2_patch": []}},
        )
        session.capture_step(
            step=step,
            x0=torch.full((1, 4, 8, 8), step * 0.2),
            x=torch.randn(1, 4, 8, 8),
            total_steps=2,
            previewer=FakePreviewer(),
        )

    session.end_sampling(status="success")
    session.finalize(status="success")

    run = store.get_run(session.run_id, include_steps=True)
    assert run is not None
    assert run["status"] == "success"
    assert run["pluginVersion"] == PLUGIN_VERSION
    assert run["promptId"] == "prompt-e2e"
    assert run["stepCount"] == 2
    assert len(run["steps"]) == 2
    assert run["steps"][0]["cfg"]["deltaMeanAbs"] > 0
    assert run["steps"][0]["control"]["active"] is True
    assert (store.run_directory(session.run_id) / "report.md").exists()
    assert (store.run_directory(session.run_id) / "report.html").exists()
    assert len(list((store.run_directory(session.run_id) / "artifacts").glob("*.jpg"))) == 2
