from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _metric(steps: Sequence[Mapping[str, Any]], path: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    for step in steps:
        value: Any = step
        for key in path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(key)
        parsed = _number(value)
        if parsed is not None:
            values.append(parsed)
    return values


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _quantile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[max(0, min(len(ordered) - 1, index))]


def _control_nodes(run: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    settings = run.get("generationSettings", {})
    if not isinstance(settings, Mapping):
        return []
    nodes = settings.get("controlnet", [])
    return [node for node in nodes if isinstance(node, Mapping)] if isinstance(nodes, Sequence) else []


def diagnose_run(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generate cautious, testable hypotheses from relative signals.

    These rules do not claim causality. They propose one-variable A/B experiments.
    """
    steps = run.get("steps", [])
    if not isinstance(steps, Sequence) or not steps:
        return []
    step_maps = [step for step in steps if isinstance(step, Mapping)]
    if not step_maps:
        return []

    diagnostics: list[dict[str, Any]] = []
    preview_changes = _metric(step_maps, ("previewChange",))
    cfg_deltas = _metric(step_maps, ("cfg", "deltaMeanAbs"))
    control_values = _metric(step_maps, ("control", "weightedMeanAbs"))
    preview_median = _median(preview_changes)
    cfg_median = _median(cfg_deltas)
    control_median = _median(control_values)

    split = max(1, math.floor(len(step_maps) * 0.7))
    late_steps = step_maps[split:]
    late_changes = _metric(late_steps, ("previewChange",))
    early_changes = _metric(step_maps[:split], ("previewChange",))
    late_median = _median(late_changes)
    earlier_median = _median(early_changes)

    if (
        late_median is not None
        and earlier_median is not None
        and late_median > max(0.02, earlier_median * 1.35)
    ):
        diagnostics.append(
            {
                "id": "late-visual-instability",
                "severity": "warning",
                "observation": "후반 30%의 Preview 변화량 중앙값이 앞 구간보다 높습니다.",
                "hypothesis": "후기 디테일 단계에서도 구조·색이 계속 재설계되거나 강한 조건이 충돌할 가능성이 있습니다.",
                "evidence": {
                    "earlierPreviewChangeMedian": earlier_median,
                    "latePreviewChangeMedian": late_median,
                },
                "experiments": [
                    "동일 Seed에서 CFG만 낮춘 Run을 비교합니다.",
                    "Style LoRA 또는 IPAdapter weight를 하나씩만 낮춰 비교합니다.",
                    "ControlNet end_percent가 짧다면 후기까지 연장한 Run을 비교합니다.",
                ],
            }
        )

    controls = _control_nodes(run)
    if controls:
        end_values: list[float] = []
        for node in controls:
            inputs = node.get("inputs", {})
            if isinstance(inputs, Mapping):
                value = _number(inputs.get("end_percent"))
                if value is not None:
                    end_values.append(value)
        active_steps = sum(bool(step.get("control", {}).get("active")) for step in step_maps)
        if active_steps == 0:
            diagnostics.append(
                {
                    "id": "control-configured-but-not-observed",
                    "severity": "warning",
                    "observation": "Workflow에는 ControlNet 계열 노드가 있지만 APPLY_MODEL에서 active control이 관찰되지 않았습니다.",
                    "hypothesis": "적용 범위 밖이거나, 커스텀 구현이 표준 control 경로를 우회하거나, Trace Model 연결 위치가 다를 수 있습니다.",
                    "evidence": {"controlNodeCount": len(controls), "activeStepCount": active_steps},
                    "experiments": [
                        "ControlNet start/end와 strength를 확인합니다.",
                        "Trace Model이 실제 KSampler에 들어가는 MODEL 선에 연결됐는지 확인합니다.",
                        "해당 커스텀 노드용 Runtime Adapter 필요 여부를 확인합니다.",
                    ],
                }
            )
        elif end_values and max(end_values) < 0.85:
            diagnostics.append(
                {
                    "id": "control-ends-before-late-stage",
                    "severity": "info",
                    "observation": "ControlNet end_percent가 후기 단계 전에 끝나도록 설정되어 있습니다.",
                    "hypothesis": "초기 구조는 맞고 후기에 무너진다면 control 종료 이후 다른 조건이 구조를 덮을 수 있습니다.",
                    "evidence": {"maxEndPercent": max(end_values)},
                    "experiments": [
                        "strength는 고정하고 end_percent만 1.0으로 늘린 Run을 비교합니다.",
                    ],
                }
            )

    if cfg_median is not None and preview_median is not None:
        cfg_high = _quantile(cfg_deltas, 0.75)
        change_high = _quantile(preview_changes, 0.75)
        correlated_count = 0
        if cfg_high is not None and change_high is not None:
            for step in step_maps:
                cfg = _number((step.get("cfg") or {}).get("deltaMeanAbs"))
                change = _number(step.get("previewChange"))
                if cfg is not None and change is not None and cfg >= cfg_high and change >= change_high:
                    correlated_count += 1
        if correlated_count >= max(2, len(step_maps) // 8):
            diagnostics.append(
                {
                    "id": "high-cfg-delta-and-visual-change",
                    "severity": "info",
                    "observation": "상대적으로 CFG delta와 Preview 변화량이 동시에 높은 step이 반복됩니다.",
                    "hypothesis": "Prompt/Negative 조건 압력이 큰 변화 구간과 겹칠 가능성이 있습니다. 상관이며 인과 확정은 아닙니다.",
                    "evidence": {
                        "matchingStepCount": correlated_count,
                        "cfgMedian": cfg_median,
                        "previewChangeMedian": preview_median,
                    },
                    "experiments": [
                        "동일 Seed에서 CFG만 한 단계 낮춰 비교합니다.",
                        "Positive/Negative prompt는 그대로 두고 CFG만 변경합니다.",
                    ],
                }
            )

    if control_median is not None and preview_median is not None:
        control_high = _quantile(control_values, 0.75)
        change_low = _quantile(preview_changes, 0.25)
        rigid_count = 0
        if control_high is not None and change_low is not None:
            for step in step_maps:
                control = _number((step.get("control") or {}).get("weightedMeanAbs"))
                change = _number(step.get("previewChange"))
                if control is not None and change is not None and control >= control_high and change <= change_low:
                    rigid_count += 1
        if rigid_count >= max(2, len(step_maps) // 8):
            diagnostics.append(
                {
                    "id": "strong-control-low-change-candidate",
                    "severity": "info",
                    "observation": "상대적으로 Control residual이 높고 Preview 변화량이 낮은 step이 반복됩니다.",
                    "hypothesis": "구조 제약이 강하게 고정되는 구간일 수 있습니다. 딱딱한 결과가 문제일 때만 의미가 있습니다.",
                    "evidence": {"matchingStepCount": rigid_count, "controlMedian": control_median},
                    "experiments": [
                        "ControlNet strength만 10~20% 낮춘 Run을 비교합니다.",
                        "strength는 유지하고 end_percent만 줄인 Run을 비교합니다.",
                    ],
                }
            )

    missing_previews = sum(not step.get("previewFile") for step in step_maps)
    if missing_previews == len(step_maps):
        diagnostics.append(
            {
                "id": "no-preview-artifacts",
                "severity": "info",
                "observation": "Step 수치는 있지만 저장된 Preview가 없습니다.",
                "hypothesis": "persist_previews가 꺼졌거나 해당 latent format에 사용할 Preview decoder가 없을 수 있습니다.",
                "evidence": {"stepCount": len(step_maps)},
                "experiments": [
                    "Trace Model의 persist_previews를 켭니다.",
                    "ComfyUI Preview 설정 또는 latent RGB/TAESD 지원 여부를 확인합니다.",
                ],
            }
        )

    return diagnostics
