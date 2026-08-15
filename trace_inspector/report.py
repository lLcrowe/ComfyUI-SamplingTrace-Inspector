from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def _fmt(value: Any, digits: int = 4) -> str:
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    if value is None:
        return "—"
    return str(value)


def _step_rows(steps: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for step in steps:
        x0 = step.get("x0", {}) or {}
        cfg = step.get("cfg", {}) or {}
        control = step.get("control", {}) or {}
        rows.append(
            [
                str(step.get("segmentIndex", 0)),
                str(step.get("step", "")),
                _fmt(step.get("sigma")),
                _fmt(step.get("previewChange")),
                _fmt(x0.get("mean")),
                _fmt(x0.get("std")),
                _fmt(cfg.get("deltaMeanAbs")),
                _fmt(control.get("weightedMeanAbs")),
                str(step.get("previewFile") or ""),
            ]
        )
    return rows


def _notes(run: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        probe
        for probe in run.get("probes", [])
        if isinstance(probe, dict) and probe.get("probeType") == "note"
    ]


def _note_step_label(note: dict[str, Any]) -> str:
    step = note.get("step")
    if isinstance(step, int) and not isinstance(step, bool) and step >= 0:
        segment_index = note.get("segmentIndex")
        if (
            isinstance(segment_index, int)
            and not isinstance(segment_index, bool)
            and segment_index >= 0
        ):
            return f"segment {segment_index + 1} · step {step + 1}"
        return f"step {step + 1}"
    return "run-wide"


def _actual_sampler(run: dict[str, Any]) -> str:
    segments = run.get("segments", []) or []
    if segments and isinstance(segments[0], dict):
        return str(segments[0].get("sampler") or "")
    return ""


def _prompt_tokenization(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("promptTokenization", {}) or {}
    return value if isinstance(value, dict) else {}


def _prompt_role_text(prompt: dict[str, Any]) -> str:
    roles = prompt.get("roles", []) or ["unknown"]
    return ", ".join(str(role) for role in roles)


def _prompt_calls(prompt: dict[str, Any]) -> list[dict[str, Any]]:
    calls = [call for call in (prompt.get("calls", []) or []) if not call.get("internal")]
    if calls:
        return calls
    return [
        {
            "sourceField": source,
            "text": text,
            "encoders": prompt.get("encoders", []) or [],
        }
        for source, text in (prompt.get("texts", {}) or {}).items()
    ]


def _used_encoders(call: dict[str, Any]) -> list[dict[str, Any]]:
    encoders = call.get("encoders", []) or []
    used = {str(name) for name in (call.get("usedEncoders", []) or [])}
    return [encoder for encoder in encoders if not used or str(encoder.get("name")) in used]


def render_markdown(run: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    options = run.get("options", {}) or {}
    settings = run.get("generationSettings", {}) or {}
    lines = [
        "# ComfyUI Sampling Trace Inspector Report",
        "",
        "## Run",
        "",
        f"- Run ID: `{run.get('runId', '')}`",
        f"- Prompt ID: `{run.get('promptId') or '—'}`",
        f"- Workflow: {run.get('workflowName') or '—'}",
        f"- Label: {run.get('label') or '—'}",
        f"- Status: `{run.get('status', '')}`",
        f"- Created: `{run.get('createdAt', '')}`",
        f"- Started: `{run.get('startedAt', '')}`",
        f"- Finished: `{run.get('finishedAt', '')}`",
        f"- Trace mode: `{options.get('mode', '')}`",
        f"- Workflow hash: `{run.get('workflowHash', '')}`",
        "",
        "## Generation settings",
        "",
        "```json",
        json.dumps(settings, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Runtime execution",
        "",
        f"- Requested sampler: `{settings.get('sampler_name', '')}`",
        f"- Actual sampler: `{_actual_sampler(run) or '—'}`",
        "- Model patch snapshot:",
        "",
        "```json",
        json.dumps(run.get("modelSnapshot", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Text prompt tokens",
        "",
        f"- Capture status: `{_prompt_tokenization(run).get('status') or 'not captured'}`",
        "- Boundary: token splitting and input weights are recorded; attention, quality contribution, and causal percentages are not measured here.",
        "",
    ]
    prompts = _prompt_tokenization(run).get("prompts", []) or []
    if prompts:
        for prompt in prompts:
            lines.extend(
                [
                    "",
                    f"### Node {prompt.get('nodeId', '—')} · {_prompt_role_text(prompt)} · `{prompt.get('classType', '')}`",
                    "",
                ]
            )
            for call in _prompt_calls(prompt):
                lines.extend([f"**{call.get('sourceField', 'tokenize')} actual source**", "", "```text", str(call.get("text", "")), "```", ""])
                for encoder in _used_encoders(call):
                    lines.append(
                        f"- `{encoder.get('name', 'clip')}`: {encoder.get('chunkCount', 0)} chunk(s), "
                        f"{encoder.get('contentTokenCount', 0)} content token(s), "
                        f"{encoder.get('paddingTokenCount', 0)} padding token(s)"
                    )
            if prompt.get("error"):
                lines.append(f"- Tokenization error: `{prompt.get('error')}`")
    else:
        lines.append("- No supported standard prompt token record is available.")
    lines.extend(["", "## Notes", ""])
    notes = _notes(run)
    if notes:
        for note in notes:
            text = str((note.get("summary") or {}).get("text", "")).replace("\n", "  \n  ")
            timestamp = note.get("updatedAt") or note.get("timestamp") or ""
            lines.append(
                f"- **{note.get('label', 'observation')} · {_note_step_label(note)}** "
                f"`{timestamp}` — {text}"
            )
    else:
        lines.append("- No notes recorded.")

    lines.extend(
        [
        "",
        "## Sampling segments",
        "",
        "```json",
        json.dumps(run.get("segments", []), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Diagnostics (관찰 기반 가설)",
        "",
        "```json",
        json.dumps(run.get("diagnostics", []), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Step timeline",
        "",
        "| Segment | Step | Sigma (노이즈 강도) | Preview change | x0 mean | x0 std | CFG delta | Control residual | Preview |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in _step_rows(steps):
        preview = f"[{row[8]}](artifacts/{row[8]})" if row[8] else "—"
        lines.append("| " + " | ".join(row[:8] + [preview]) + " |")

    lines.extend(
        [
            "",
            "## 용어",
            "",
            "- Preview (중간 미리보기): 현재 step의 x0 예측을 빠르게 이미지로 변환한 근사 화면",
            "- Latent (잠재 표현 / 압축된 이미지 정보): 확산 모델이 직접 수정하는 내부 이미지 표현",
            "- x0: 현재 step에서 모델이 예상한 노이즈가 제거된 결과",
            "- Sigma (노이즈 강도): 현재 샘플링 단계의 노이즈 수준",
            "- CFG (조건 반영 강도): 조건부/비조건부 예측 차이를 증폭하는 과정",
            "- Control residual (제어 잔차): ControlNet이 본 모델 내부에 더하는 특징 보정값",
            "",
        ]
    )
    return "\n".join(lines)


def render_html(run: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    rows = []
    for row in _step_rows(steps):
        image_cell = (
            f'<a href="artifacts/{html.escape(row[8])}"><img src="artifacts/{html.escape(row[8])}" loading="lazy"></a>'
            if row[8]
            else "—"
        )
        rows.append(
            "<tr>"
            + "".join(f"<td>{html.escape(cell)}</td>" for cell in row[:8])
            + f"<td>{image_cell}</td></tr>"
        )

    mode = (run.get("options") or {}).get("mode", "")
    settings_json = json.dumps(run.get("generationSettings", {}), ensure_ascii=False, indent=2)
    diagnostics_json = json.dumps(run.get("diagnostics", []), ensure_ascii=False, indent=2)
    model_snapshot_json = json.dumps(run.get("modelSnapshot", {}), ensure_ascii=False, indent=2)
    requested_sampler = str((run.get("generationSettings") or {}).get("sampler_name", ""))
    actual_sampler = _actual_sampler(run) or "—"
    notes = _notes(run)
    if notes:
        note_cards = "".join(
            '<article class="note">'
            f'<div><b>{html.escape(str(note.get("label", "observation")))} · '
            f'{html.escape(_note_step_label(note))}</b> '
            f'<span class="small">{html.escape(str(note.get("updatedAt") or note.get("timestamp") or ""))}</span></div>'
            f'<p>{html.escape(str((note.get("summary") or {}).get("text", ""))).replace(chr(10), "<br>")}</p>'
            "</article>"
            for note in notes
        )
    else:
        note_cards = '<p class="small">No notes recorded.</p>'
    prompt_capture = _prompt_tokenization(run)
    prompt_cards = []
    for prompt in prompt_capture.get("prompts", []) or []:
        sources = ""
        for call in _prompt_calls(prompt):
            encoders = "".join(
                "<li>"
                f'<code>{html.escape(str(encoder.get("name", "clip")))}</code>: '
                f'{int(encoder.get("chunkCount", 0) or 0)} chunk(s), '
                f'{int(encoder.get("contentTokenCount", 0) or 0)} content, '
                f'{int(encoder.get("paddingTokenCount", 0) or 0)} padding'
                "</li>"
                for encoder in _used_encoders(call)
            )
            sources += (
                f'<div><b>{html.escape(str(call.get("sourceField", "tokenize")))} actual source</b>'
                f'<pre>{html.escape(str(call.get("text", "")))}</pre><ul>{encoders}</ul></div>'
            )
        error = f'<p class="small">{html.escape(str(prompt.get("error")))}</p>' if prompt.get("error") else ""
        prompt_cards.append(
            '<article class="prompt">'
            f'<h3>Node {html.escape(str(prompt.get("nodeId", "—")))} · '
            f'{html.escape(_prompt_role_text(prompt))} · '
            f'<code>{html.escape(str(prompt.get("classType", "")))}</code></h3>'
            f'{sources}{error}</article>'
        )
    prompt_cards_html = "".join(prompt_cards) or '<p class="small">No supported standard prompt token record is available.</p>'
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ComfyUI Trace {html.escape(str(run.get('runId', '')))}</title>
<style>
body{{font:14px/1.5 system-ui,sans-serif;margin:24px;background:#111;color:#ddd}}
code,pre{{font-family:ui-monospace,monospace}}pre{{background:#1b1b1b;padding:12px;overflow:auto}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #333;padding:6px;text-align:left}}
th{{position:sticky;top:0;background:#202020}}img{{max-width:180px;max-height:120px}}
.small{{color:#aaa}}
.note{{border-left:3px solid #78aeda;background:#1b1b1b;padding:8px 10px;margin:8px 0}}.note p{{margin:5px 0 0}}
.prompt{{border-left:3px solid #78aeda;background:#1b1b1b;padding:8px 10px;margin:8px 0}}.prompt h3{{margin:0 0 7px}}
</style>
</head>
<body>
<h1>ComfyUI Sampling Trace Inspector Report</h1>
<p><b>Run:</b> <code>{html.escape(str(run.get('runId', '')))}</code><br>
<b>Prompt:</b> <code>{html.escape(str(run.get('promptId') or '—'))}</code><br>
<b>Workflow:</b> {html.escape(str(run.get('workflowName') or '—'))}<br>
<b>Status:</b> {html.escape(str(run.get('status', '')))}<br>
<b>Mode:</b> {html.escape(str(mode))}</p>
<h2>Generation settings</h2>
<pre>{html.escape(settings_json)}</pre>
<h2>Runtime execution</h2>
<p><b>Requested sampler:</b> <code>{html.escape(requested_sampler)}</code><br>
<b>Actual sampler:</b> <code>{html.escape(actual_sampler)}</code></p>
<pre>{html.escape(model_snapshot_json)}</pre>
<h2>Text prompt tokens</h2>
<p><b>Capture status:</b> <code>{html.escape(str(prompt_capture.get('status') or 'not captured'))}</code></p>
<p class="small">Token splitting and input weights are recorded. Attention, quality contribution, and causal percentages are not measured here.</p>
{prompt_cards_html}
<h2>Notes</h2>
{note_cards}
<h2>Diagnostics (관찰 기반 가설)</h2>
<pre>{html.escape(diagnostics_json)}</pre>
<h2>Step timeline</h2>
<table><thead><tr><th>Segment</th><th>Step</th><th>Sigma</th><th>Preview change</th><th>x0 mean</th><th>x0 std</th><th>CFG delta</th><th>Control residual</th><th>Preview</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p class="small">Preview는 현재 step의 x0를 빠르게 디코드한 근사 이미지이며 최종 VAE Decode 결과와 같지 않을 수 있습니다.</p>
</body></html>"""


def _compare_rows(comparison: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for pair in comparison.get("stepPairs", []) or []:
        left = pair.get("left", {}) or {}
        right = pair.get("right", {}) or {}
        difference = pair.get("difference", {}) or {}
        left_control = left.get("control", {}) or {}
        right_control = right.get("control", {}) or {}
        rows.append(
            [
                str(left.get("step", pair.get("index", ""))),
                _fmt(left.get("sigma")),
                _fmt(right.get("sigma")),
                _fmt((left.get("x0") or {}).get("mean")),
                _fmt((right.get("x0") or {}).get("mean")),
                _fmt(difference.get("x0MeanAbsolute"), 6),
                _fmt(left_control.get("weightedMeanAbs")),
                _fmt(right_control.get("weightedMeanAbs")),
                _fmt(difference.get("controlWeightedMeanAbsolute"), 6),
                str(left.get("previewFile") or ""),
                str(right.get("previewFile") or ""),
            ]
        )
    return rows


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    left = comparison.get("left", {}) or {}
    right = comparison.get("right", {}) or {}
    workflow = comparison.get("workflow", {}) or {}
    runtime = comparison.get("runtime", {}) or {}
    lines = [
        "# ComfyUI Sampling Trace Inspector A/B Report",
        "",
        "## Runs",
        "",
        "| Side | Run | Prompt | Workflow | Label | Workflow hash | Requested sampler | Actual sampler | Steps |",
        "|---|---|---|---|---|---|---|---|---:|",
        f"| A | `{left.get('runId', '')}` | `{left.get('promptId') or '—'}` | {left.get('workflowName') or '—'} | {left.get('label') or '—'} | `{workflow.get('leftHash', '')}` | `{(runtime.get('left') or {}).get('requestedSampler', '')}` | `{(runtime.get('left') or {}).get('actualSampler', '')}` | {comparison.get('leftStepCount', 0)} |",
        f"| B | `{right.get('runId', '')}` | `{right.get('promptId') or '—'}` | {right.get('workflowName') or '—'} | {right.get('label') or '—'} | `{workflow.get('rightHash', '')}` | `{(runtime.get('right') or {}).get('requestedSampler', '')}` | `{(runtime.get('right') or {}).get('actualSampler', '')}` | {comparison.get('rightStepCount', 0)} |",
        "",
        "## Workflow relation",
        "",
        f"- Exact workflow hash match: `{workflow.get('hashMatch', False)}`",
        f"- Node count A / B: `{workflow.get('leftNodeCount', 0)} / {workflow.get('rightNodeCount', 0)}`",
        "",
        "## Changed settings",
        "",
        "```json",
        json.dumps(comparison.get("settingsDiff", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Model patch snapshots",
        "",
        "```json",
        json.dumps(comparison.get("modelPatches", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Aligned step evidence",
        "",
        "| Step | Sigma A | Sigma B | x0 mean A | x0 mean B | x0 mean |A-B| | Control A | Control B | Control |A-B| | Preview A | Preview B |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    left_id = str(left.get("runId", ""))
    right_id = str(right.get("runId", ""))
    for row in _compare_rows(comparison):
        preview_a = f"[{row[9]}](/trace-inspector/runs/{left_id}/artifact/{row[9]})" if row[9] else "—"
        preview_b = f"[{row[10]}](/trace-inspector/runs/{right_id}/artifact/{row[10]})" if row[10] else "—"
        lines.append("| " + " | ".join(row[:9] + [preview_a, preview_b]) + " |")
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            f"- {comparison.get('disclaimer', 'Observed differences are evidence, not causal percentages.')}",
            "- Preview는 x0의 근사 디코드이며 최종 VAE Decode 이미지와 같지 않을 수 있습니다.",
            "",
        ]
    )
    return "\n".join(lines)


def render_comparison_html(comparison: dict[str, Any]) -> str:
    left = comparison.get("left", {}) or {}
    right = comparison.get("right", {}) or {}
    workflow = comparison.get("workflow", {}) or {}
    runtime = comparison.get("runtime", {}) or {}
    left_id = str(left.get("runId", ""))
    right_id = str(right.get("runId", ""))
    rows = []
    for row in _compare_rows(comparison):
        preview_a = (
            f'<a href="/trace-inspector/runs/{html.escape(left_id)}/artifact/{html.escape(row[9])}"><img src="/trace-inspector/runs/{html.escape(left_id)}/artifact/{html.escape(row[9])}" loading="lazy"></a>'
            if row[9]
            else "—"
        )
        preview_b = (
            f'<a href="/trace-inspector/runs/{html.escape(right_id)}/artifact/{html.escape(row[10])}"><img src="/trace-inspector/runs/{html.escape(right_id)}/artifact/{html.escape(row[10])}" loading="lazy"></a>'
            if row[10]
            else "—"
        )
        rows.append(
            "<tr>"
            + "".join(f"<td>{html.escape(cell)}</td>" for cell in row[:9])
            + f"<td>{preview_a}</td><td>{preview_b}</td></tr>"
        )
    settings_json = json.dumps(comparison.get("settingsDiff", {}), ensure_ascii=False, indent=2)
    patches_json = json.dumps(comparison.get("modelPatches", {}), ensure_ascii=False, indent=2)
    left_runtime = runtime.get("left", {}) or {}
    right_runtime = runtime.get("right", {}) or {}
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ComfyUI Trace A/B {html.escape(left_id)} vs {html.escape(right_id)}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;margin:24px;background:#111;color:#ddd}}code,pre{{font-family:ui-monospace,monospace}}pre{{background:#1b1b1b;padding:12px;overflow:auto}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #333;padding:6px;text-align:left}}th{{position:sticky;top:0;background:#202020}}img{{max-width:150px;max-height:110px}}.small{{color:#aaa}}</style>
</head><body><h1>ComfyUI Sampling Trace Inspector A/B Report</h1>
<table><thead><tr><th>Side</th><th>Run</th><th>Prompt</th><th>Workflow</th><th>Label</th><th>Workflow hash</th><th>Requested sampler</th><th>Actual sampler</th><th>Steps</th></tr></thead><tbody>
<tr><td>A</td><td><code>{html.escape(left_id)}</code></td><td><code>{html.escape(str(left.get('promptId') or '—'))}</code></td><td>{html.escape(str(left.get('workflowName') or '—'))}</td><td>{html.escape(str(left.get('label') or '—'))}</td><td><code>{html.escape(str(workflow.get('leftHash', '')))}</code></td><td>{html.escape(str(left_runtime.get('requestedSampler', '')))}</td><td>{html.escape(str(left_runtime.get('actualSampler', '')))}</td><td>{comparison.get('leftStepCount', 0)}</td></tr>
<tr><td>B</td><td><code>{html.escape(right_id)}</code></td><td><code>{html.escape(str(right.get('promptId') or '—'))}</code></td><td>{html.escape(str(right.get('workflowName') or '—'))}</td><td>{html.escape(str(right.get('label') or '—'))}</td><td><code>{html.escape(str(workflow.get('rightHash', '')))}</code></td><td>{html.escape(str(right_runtime.get('requestedSampler', '')))}</td><td>{html.escape(str(right_runtime.get('actualSampler', '')))}</td><td>{comparison.get('rightStepCount', 0)}</td></tr>
</tbody></table>
<h2>Workflow relation</h2><p>Exact workflow hash match: <code>{workflow.get('hashMatch', False)}</code><br>Node count A / B: {workflow.get('leftNodeCount', 0)} / {workflow.get('rightNodeCount', 0)}</p>
<h2>Changed settings</h2><pre>{html.escape(settings_json)}</pre>
<h2>Model patch snapshots</h2><pre>{html.escape(patches_json)}</pre>
<h2>Aligned step evidence</h2><table><thead><tr><th>Step</th><th>Sigma A</th><th>Sigma B</th><th>x0 mean A</th><th>x0 mean B</th><th>x0 |A-B|</th><th>Control A</th><th>Control B</th><th>Control |A-B|</th><th>Preview A</th><th>Preview B</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>Interpretation boundary</h2><p>{html.escape(str(comparison.get('disclaimer', 'Observed differences are evidence, not causal percentages.')))}</p><p class="small">Preview는 x0의 근사 디코드이며 최종 VAE Decode 이미지와 같지 않을 수 있습니다.</p>
</body></html>"""


def write_comparison_reports(
    run_dir: Path,
    comparison: dict[str, Any],
    right_id: str,
) -> dict[str, str]:
    markdown_name = f"compare_{right_id}.md"
    html_name = f"compare_{right_id}.html"
    (run_dir / markdown_name).write_text(render_comparison_markdown(comparison), encoding="utf-8")
    (run_dir / html_name).write_text(render_comparison_html(comparison), encoding="utf-8")
    return {"markdown": markdown_name, "html": html_name}


def write_reports(run_dir: Path, run: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, str]:
    markdown_path = run_dir / "report.md"
    html_path = run_dir / "report.html"
    markdown_path.write_text(render_markdown(run, steps), encoding="utf-8")
    html_path.write_text(render_html(run, steps), encoding="utf-8")
    return {"markdown": markdown_path.name, "html": html_path.name}
