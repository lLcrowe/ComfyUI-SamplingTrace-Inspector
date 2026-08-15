from __future__ import annotations

from pathlib import Path

from trace_inspector.report import render_html, render_markdown
from trace_inspector.store import TraceStore


def run_payload(run_id: str):
    return {
        "runId": run_id,
        "promptId": f"prompt-{run_id}",
        "label": "test",
        "status": "success",
        "createdAt": "2026-08-12T00:00:00+00:00",
        "startedAt": "2026-08-12T00:00:01+00:00",
        "finishedAt": "2026-08-12T00:00:02+00:00",
        "workflowHash": "abc",
        "options": {"mode": "advanced"},
        "generationSettings": {"seed": 42, "cfg": 6.5},
        "promptAnalysis": {"nodes": [{"id": "1"}]},
        "modelSnapshot": {"transformerPatchCallableCount": 0, "transformerOptionShape": {}},
        "segments": [{"sampler": "sample_euler"}],
        "stepCount": 1,
    }


def step_payload(run_id: str):
    return {
        "runId": run_id,
        "segmentIndex": 0,
        "step": 0,
        "totalSteps": 1,
        "sigma": 1.0,
        "previewFile": "segment_00_step_0000.jpg",
        "previewUrl": f"/trace-inspector/runs/{run_id}/artifact/segment_00_step_0000.jpg",
        "x0": {"mean": 0.0, "std": 1.0},
        "cfg": {"deltaMeanAbs": 0.5},
        "control": {"weightedMeanAbs": 0.2},
    }


def test_store_round_trip_and_reports(tmp_path: Path):
    store = TraceStore(tmp_path)
    run_id = "test-run"
    store.persist_run(run_payload(run_id))
    store.append_step(run_id, step_payload(run_id))
    loaded = store.get_run(run_id, include_steps=True)
    assert loaded is not None
    assert loaded["steps"][0]["sigma"] == 1.0
    files = store.generate_reports(run_id)
    assert (tmp_path / run_id / files["markdown"]).exists()
    assert (tmp_path / run_id / files["html"]).exists()


def test_report_renderers_do_not_raise():
    run = run_payload("r")
    steps = [step_payload("r")]
    markdown = render_markdown(run, steps)
    html = render_html(run, steps)
    assert "Step timeline" in markdown
    assert "<table>" in html


def test_compare_includes_x_and_x0_summaries(tmp_path: Path):
    store = TraceStore(tmp_path)
    for run_id, x0_mean in (("left", 0.1), ("right", 0.4)):
        store.persist_run(run_payload(run_id))
        step = step_payload(run_id)
        step["x"] = {"mean": -0.2, "std": 1.1}
        step["x0"] = {"mean": x0_mean, "std": 0.9}
        store.append_step(run_id, step)

    comparison = store.compare_runs("left", "right")

    assert comparison["stepPairs"][0]["left"]["x"]["mean"] == -0.2
    assert comparison["stepPairs"][0]["left"]["x0"]["mean"] == 0.1
    assert comparison["stepPairs"][0]["right"]["x0"]["mean"] == 0.4
    assert comparison["stepPairs"][0]["difference"]["x0MeanAbsolute"] == 0.30000000000000004
    assert comparison["workflow"]["hashMatch"] is True
    assert comparison["runtime"]["left"]["requestedSampler"] is None
    assert comparison["runtime"]["left"]["actualSampler"] == "sample_euler"
    assert "not causal percentages" in comparison["disclaimer"]


def test_comparison_reports_include_runtime_workflow_and_evidence(tmp_path: Path):
    store = TraceStore(tmp_path)
    left = run_payload("left")
    right = run_payload("right")
    left["generationSettings"]["sampler_name"] = "euler"
    right["generationSettings"]["sampler_name"] = "euler"
    right["segments"][0]["sampler"] = "sample_euler_ancestral"
    right["workflowHash"] = "different"
    right["modelSnapshot"]["transformerPatchCallableCount"] = 70
    right["modelSnapshot"]["transformerOptionShape"] = {"patches_replace": {"attn2": 70}}
    store.persist_run(left)
    store.persist_run(right)
    store.append_step("left", step_payload("left"))
    changed = step_payload("right")
    changed["x0"]["mean"] = 0.25
    changed["control"]["weightedMeanAbs"] = 0.7
    store.append_step("right", changed)

    result = store.generate_comparison_reports("left", "right")
    markdown = (tmp_path / "left" / result["reportFiles"]["markdown"]).read_text(encoding="utf-8")
    html = (tmp_path / "left" / result["reportFiles"]["html"]).read_text(encoding="utf-8")

    assert "Exact workflow hash match: `False`" in markdown
    assert "prompt-left" in markdown and "prompt-right" in markdown
    assert "sample_euler_ancestral" in markdown
    assert "not causal percentages" in markdown
    assert "Model patch snapshots" in html
    assert "compare_right.html" == result["reportFiles"]["html"]
    assert store.resolve_report("left", "compare_right.html").is_file()


def test_note_update_delete_and_report_refresh(tmp_path: Path):
    store = TraceStore(tmp_path)
    run_id = "note-run"
    store.persist_run(run_payload(run_id))
    store.append_step(run_id, step_payload(run_id))
    store.append_probe(
        run_id,
        {
            "noteId": "note-1",
            "probeType": "note",
            "label": "observation",
            "summary": {"text": "Initial note"},
            "timestamp": "2026-08-14T00:00:00+00:00",
        },
    )

    store.generate_reports(run_id)
    assert "Initial note" in (tmp_path / run_id / "report.md").read_text(encoding="utf-8")

    updated = store.update_note(
        run_id,
        "note-1",
        text="Edited note",
        category="decision",
        updated_at="2026-08-14T00:01:00+00:00",
    )
    assert updated["summary"]["text"] == "Edited note"
    assert updated["label"] == "decision"
    assert store.refresh_reports_if_present(run_id) is True
    markdown = (tmp_path / run_id / "report.md").read_text(encoding="utf-8")
    html = (tmp_path / run_id / "report.html").read_text(encoding="utf-8")
    assert "Edited note" in markdown
    assert "Edited note" in html

    assert store.delete_note(run_id, "note-1") is True
    assert store.refresh_reports_if_present(run_id) is True
    loaded = store.get_run(run_id, include_steps=True)
    assert loaded is not None
    assert not [probe for probe in loaded["probes"] if probe.get("probeType") == "note"]
    assert "Edited note" not in (tmp_path / run_id / "report.md").read_text(encoding="utf-8")
