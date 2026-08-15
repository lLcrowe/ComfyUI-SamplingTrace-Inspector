from __future__ import annotations

import json
from pathlib import Path

from trace_inspector.report import render_html, render_markdown
from trace_inspector.server_routes import (
    _parse_optional_note_segment_index,
    _parse_optional_note_step,
    _run_contains_step,
)
from trace_inspector.store import TraceStore, normalize_workflow_name


def run_payload(run_id: str):
    return {
        "runId": run_id,
        "promptId": f"prompt-{run_id}",
        "workflowName": "portrait-study.json",
        "label": "test",
        "status": "success",
        "createdAt": "2026-08-12T00:00:00+00:00",
        "startedAt": "2026-08-12T00:00:01+00:00",
        "finishedAt": "2026-08-12T00:00:02+00:00",
        "workflowHash": "abc",
        "options": {"mode": "advanced"},
        "generationSettings": {"seed": 42, "cfg": 6.5},
        "promptAnalysis": {"nodes": [{"id": "1"}]},
        "promptTokenization": {
            "status": "captured",
            "prompts": [
                {
                    "nodeId": "2",
                    "classType": "CLIPTextEncode",
                    "roles": ["positive"],
                    "texts": {"default": "red cat"},
                    "encoders": [
                        {
                            "name": "l",
                            "chunkCount": 1,
                            "contentTokenCount": 2,
                            "paddingTokenCount": 72,
                        }
                    ],
                }
            ],
        },
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
    assert store.list_runs()[0]["workflowName"] == "portrait-study.json"


def test_workflow_name_keeps_filename_only_and_refreshes_report(tmp_path: Path):
    store = TraceStore(tmp_path)
    run_id = "workflow-name-run"
    store.persist_run(run_payload(run_id))
    store.append_step(run_id, step_payload(run_id))
    store.generate_reports(run_id)

    stored = store.set_workflow_name(run_id, r"C:\Private\character sheet.json")

    assert stored == "character sheet.json"
    assert normalize_workflow_name("folder/subfolder/test.json") == "test.json"
    assert store.get_run(run_id, include_steps=False)["workflowName"] == "character sheet.json"
    assert "Workflow: character sheet.json" in (tmp_path / run_id / "report.md").read_text(encoding="utf-8")


def test_report_renderers_do_not_raise():
    run = run_payload("r")
    steps = [step_payload("r")]
    markdown = render_markdown(run, steps)
    html = render_html(run, steps)
    assert "Step timeline" in markdown
    assert "Workflow: portrait-study.json" in markdown
    assert "Text prompt tokens" in markdown
    assert "red cat" in markdown
    assert "causal percentages are not measured" in markdown
    assert "Text prompt tokens" in html
    assert "red cat" in html


def test_reports_render_actual_traced_clip_calls():
    run = run_payload("actual-call")
    run["promptTokenization"] = {
        "status": "captured",
        "source": "traced_clip",
        "prompts": [
            {
                "nodeId": "12",
                "classType": "CLIPTextEncode",
                "roles": ["negative"],
                "calls": [
                    {
                        "sourceField": "text",
                        "text": "bad hands",
                        "usedEncoders": ["l"],
                        "encoders": [
                            {"name": "l", "chunkCount": 1, "contentTokenCount": 2, "paddingTokenCount": 72},
                            {"name": "g", "chunkCount": 1, "contentTokenCount": 2, "paddingTokenCount": 72},
                        ],
                    }
                ],
            }
        ],
    }

    markdown = render_markdown(run, [])
    html = render_html(run, [])

    assert "negative" in markdown
    assert "bad hands" in markdown
    assert "`l`: 1 chunk" in markdown
    assert "`g`:" not in markdown
    assert "bad hands" in html
    assert "<table>" in html


def test_store_preserves_deep_prompt_token_chunks(tmp_path: Path):
    store = TraceStore(tmp_path)
    run = run_payload("deep-tokens")
    run["promptTokenization"]["prompts"][0]["encoders"][0]["chunks"] = [
        [
            {
                "tokenId": 49406,
                "piece": "<start>",
                "weight": 1.0,
                "wordId": 0,
                "special": True,
                "padding": False,
            }
        ]
    ]

    store.persist_run(run)
    persisted = store.get_run("deep-tokens", include_steps=False)

    assert persisted is not None
    encoder = persisted["promptTokenization"]["prompts"][0]["encoders"][0]
    assert encoder["name"] == "l"
    assert encoder["chunks"][0][0]["tokenId"] == 49406
    assert "<max-depth>" not in json.dumps(persisted)


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
        step=0,
        segment_index=0,
    )
    assert updated["summary"]["text"] == "Edited note"
    assert updated["label"] == "decision"
    assert updated["step"] == 0
    assert updated["segmentIndex"] == 0
    assert store.refresh_reports_if_present(run_id) is True
    markdown = (tmp_path / run_id / "report.md").read_text(encoding="utf-8")
    html = (tmp_path / run_id / "report.html").read_text(encoding="utf-8")
    assert "Edited note" in markdown
    assert "Edited note" in html
    assert "segment 1 · step 1" in markdown
    assert "segment 1 · step 1" in html

    preserved = store.update_note(
        run_id,
        "note-1",
        text="Edited note",
        category="decision",
        updated_at="2026-08-14T00:02:00+00:00",
    )
    assert preserved["step"] == 0
    assert preserved["segmentIndex"] == 0

    run_wide = store.update_note(
        run_id,
        "note-1",
        text="Edited note",
        category="decision",
        updated_at="2026-08-14T00:03:00+00:00",
        step=None,
    )
    assert "step" not in run_wide
    assert "segmentIndex" not in run_wide

    assert store.delete_note(run_id, "note-1") is True
    assert store.refresh_reports_if_present(run_id) is True
    loaded = store.get_run(run_id, include_steps=True)
    assert loaded is not None
    assert not [probe for probe in loaded["probes"] if probe.get("probeType") == "note"]
    assert "Edited note" not in (tmp_path / run_id / "report.md").read_text(encoding="utf-8")


def test_note_step_parsing_and_run_validation():
    run = {
        "steps": [
            {"segmentIndex": 0, "step": 0},
            {"segmentIndex": 1, "step": 0},
            {"segmentIndex": 1, "step": 3},
        ]
    }

    assert _parse_optional_note_step({}) == (False, None)
    assert _parse_optional_note_step({"step": None}) == (True, None)
    assert _parse_optional_note_step({"step": "3"}) == (True, 3)
    assert _parse_optional_note_segment_index({}) == (False, None)
    assert _parse_optional_note_segment_index({"segmentIndex": None}) == (True, None)
    assert _parse_optional_note_segment_index({"segmentIndex": "1"}) == (True, 1)
    assert _run_contains_step(run, None) is True
    assert _run_contains_step(run, 3) is True
    assert _run_contains_step(run, 2) is False
    assert _run_contains_step(run, 0, 0) is True
    assert _run_contains_step(run, 0, 1) is True
    assert _run_contains_step(run, 3, 0) is False
    assert _run_contains_step(run, None, 1) is False
