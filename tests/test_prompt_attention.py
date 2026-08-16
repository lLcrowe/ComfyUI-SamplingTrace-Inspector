from __future__ import annotations

from pathlib import Path

import pytest
import torch

from trace_inspector.prompt_attention import aggregate_attention_events, observe_cross_attention


def _reference(q: torch.Tensor, k: torch.Tensor, heads: int) -> torch.Tensor:
    batch, query_count, width = q.shape
    dim_head = width // heads
    qh = q.reshape(batch, query_count, heads, dim_head).permute(0, 2, 1, 3)
    kh = k.reshape(batch, k.shape[1], heads, dim_head).permute(0, 2, 1, 3)
    return (torch.matmul(qh.float(), kh.float().transpose(-1, -2)) * dim_head**-0.5).softmax(-1).mean((0, 1, 2))


def test_observer_matches_full_reference_when_all_queries_are_sampled():
    torch.manual_seed(7)
    q = torch.randn(2, 5, 8)
    k = torch.randn(2, 3, 8)

    events = observe_cross_attention(q, k, 2, [0, 1], max_query_samples=8)

    assert len(events) == 2
    assert events[0]["roleIndex"] == 0
    assert events[1]["roleIndex"] == 1
    assert torch.allclose(events[0]["weights"], _reference(q[:1], k[:1], 2), atol=1e-6)
    assert torch.allclose(events[1]["weights"], _reference(q[1:], k[1:], 2), atol=1e-6)
    assert q.shape == (2, 5, 8) and k.shape == (2, 3, 8)


def test_observer_ignores_self_attention_and_invalid_role_batches():
    q = torch.randn(2, 4, 8)
    assert observe_cross_attention(q, q, 2, [0, 1]) == []
    assert observe_cross_attention(q, torch.randn(2, 3, 8), 2, [0, 1, 0]) == []


def test_aggregation_keeps_positive_and_negative_separate():
    events = [
        {"roleIndex": 0, "weights": torch.tensor([0.2, 0.8]), "querySamples": 4},
        {"roleIndex": 0, "weights": torch.tensor([0.4, 0.6]), "querySamples": 4},
        {"roleIndex": 1, "weights": torch.tensor([0.7, 0.3]), "querySamples": 4},
    ]

    result = aggregate_attention_events(events)

    assert result["approximate"] is True
    assert result["layerCount"] == 3
    assert result["roles"]["positive"]["weights"] == pytest.approx([0.3, 0.7])
    assert result["roles"]["negative"]["weights"] == pytest.approx([0.7, 0.3])


def test_panel_exposes_role_colors_and_step_attention_disclaimer():
    root = Path(__file__).resolve().parents[1]
    javascript = (root / "web" / "trace_inspector.js").read_text(encoding="utf-8")
    stylesheet = (root / "web" / "trace_inspector.css").read_text(encoding="utf-8")

    assert "샘플러 조건의 단계별 단어 주의" in javascript
    assert "KSampler positive·negative 소켓" in javascript
    assert "샘플러 positive · 긍정 조건" in javascript
    assert "샘플러 negative · 부정 조건" in javascript
    assert "samplerConditionTooltip" in javascript
    assert "function promptRoleNodeIds(run, role)" in javascript
    assert "현재 주의 수치는 단어 이름에 연결하지 않습니다" in javascript
    assert "const selectedStep = steps[selectedStepIndex]" in javascript
    assert "function refreshSelectedStepSurfaces(viewerContainer, run)" in javascript
    assert "refreshSelectedStepSurfaces(container, run);" in javascript
    assert 'range.addEventListener("change", render);' in javascript
    scrubber_input_handler = javascript.split('range.addEventListener("input", () => {', 1)[1].split("});", 1)[0]
    assert "render();" not in scrubber_input_handler
    assert "selectedInfluenceStepIndex" not in javascript
    assert "cti-influence-steps" not in javascript
    assert "부분 토큰과 반복 출현을 합한 Q/K 관측 주의 비중" in javascript
    assert "전체 단어의 스텝 흐름" in javascript
    assert "promptWordGroups" in javascript
    assert "sourceAligned" in javascript
    assert "같은 단어는 합산" in javascript
    assert "입력 프롬프트·CLIP 토큰 상세" not in javascript
    assert "promptTokenDetailsExpanded" not in javascript
    assert "finalizePromptTokenDetails" not in javascript
    assert "인과적 품질 기여율은 아닙니다" in javascript
    assert "--cti-prompt-positive" in stylesheet
    assert "--cti-prompt-negative" in stylesheet
    assert ".cti-influence-card.role-positive" in stylesheet
    assert ".cti-influence-card.role-negative" in stylesheet
    assert ".cti-prompt-token-details" not in stylesheet
    assert "max-height: 300px" in stylesheet
