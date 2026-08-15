# Implementation Status

## 전체 상태

이 패키지는 Phase 0~7의 **코드·UI·문서 구조를 모두 포함**합니다. 다만 각 Phase의 “실제 ComfyUI 환경 완료”는 분리해서 판정합니다.

| Phase | 코드/문서 초안 | 독립 테스트 | 실제 ComfyUI 검증 | 판정 |
|---|---:|---:|---:|---|
| 0. Research & Installed Node Inventory | 완료 | scanner 테스트 완료 | 실제 `custom_nodes` + workflow usage scan 완료 | 로컬 정적 조사 완료 |
| 1. Generic Execution Trace | 완료 | stub 검증 | 실제 callback·promptId·동시 client PASS | 로컬 통합 완료 |
| 2. Preview Timeline | 완료 | fake preview 검증 | SDXL/Illustrious 8-frame Preview PASS | 로컬 통합 완료 |
| 3. Sampling Metrics | 완료 | x/x0/CFG 검증 | Trace identity·N=3 performance PASS | 로컬 통합 완료 |
| 4. ControlNet Trace | 완료 | fake residual 검증 | OpenPose·Depth residual/A-B PASS | 로컬 통합 완료 |
| 5. Model Patch Trace | 완료 | semantic adapter 검증 | IPAdapter/easy-use/EasyIllustrious PASS | P1 완료 |
| 6. Compare & Export | 완료 | store/report 검증 | 실제 UI·Markdown/HTML HTTP PASS | 로컬 통합 완료 |
| 7. Productization | 문서·패키지 완료 | 정적 검사 완료 | 설치·benchmark PASS; clean install 미검증 | 공개 베타 후보 |

---

## 구현 파일별 역할

### ComfyUI entry
- `__init__.py`
- `nodes.py`

### Runtime capture
- `trace_inspector/runtime_hooks.py`
- `trace_inspector/session.py`
- `trace_inspector/preview_capture.py`
- `trace_inspector/tensor_stats.py`

### Installed custom-node inventory
- `trace_inspector/custom_node_inventory.py`
- `scripts/scan_custom_nodes.py`
- `scripts/scan_custom_nodes.ps1` / `.cmd`

### Workflow usage inventory
- `trace_inspector/workflow_usage.py`
- `scripts/scan_workflow_usage.py`
- `tests/test_workflow_usage.py`
- `docs/WORKFLOW_USAGE_INVENTORY.json` / `.md`
- `docs/LOCAL_ADAPTER_PLAN_FROM_USAGE.md`
- `docs/CUSTOM_NODE_RUNTIME_PATHS.md`
- `docs/USER_DECISION_QUEUE.md`

### Graph/state analysis
- `trace_inspector/prompt_analysis.py`
- `trace_inspector/model_snapshot.py`
- `trace_inspector/adapters/`
- `trace_inspector/diagnostics.py`

### Persistence/API
- `trace_inspector/store.py`
- `trace_inspector/server_routes.py`
- `trace_inspector/report.py`
- `trace_inspector/events.py`

### UI
- `web/trace_inspector.js`
- `web/trace_inspector.css`

### Validation
- `tests/test_custom_node_inventory.py`
- `tests/`
- `scripts/static_check.py`
- `scripts/comfy_integration_smoke.py`
- `scripts/benchmark_live.py`

---

## 구현된 주요 기능

- `Trace Model`을 MODEL 선에 삽입
- 기존 KSampler를 교체하지 않는 wrapper 방식
- Sampling callback의 `step/x0/x/total_steps` 기록
- 기존 live Preview callback 보존
- Latent2RGB/TAESD 계층을 이용한 저장 Preview
- x/x0/Sigma statistics
- CFG conditional/unconditional delta
- APPLY_MODEL에서 Control residual 구조/통계
- ModelPatcher patch/wrapper snapshot
- 모든 노드의 frontend execution timeline
- Run persistence
- Step slider
- A/B compare
- Markdown/HTML report
- 관찰 기반 진단 규칙
- Generic adapter fallback과 전용 Adapter SDK
- 설치된 custom node를 import하지 않는 AST/static source inventory
- package별 Git/version/dependency/source fingerprint
- Trace compatibility matrix와 Priority A/B/C adapter plan
- 저장 workflow JSON, PNG prompt/workflow metadata, localhost history의 read-only 사용 증거 분류
- 사용 상태와 추적 우선순위 분리; 미관찰 package는 `UNKNOWN` 유지

---

## 의도적으로 자동화하지 않은 것

- workflow 파라미터 자동 변경
- 최종 원인 단정
- Tensor 전체 dump
- 모든 커스텀 노드 내부 의미 추측
- ComfyUI core 수정

---

## 다음 게이트

Codex가 실제 설치본에서 다음 순서로 닫습니다.

```text
Static Custom Node Inventory
→ Workflow Usage Inventory
→ Usage-based Local Adapter Plan
→ Import
→ Bottom Panel
→ Minimal KSampler
→ Trace On/Off Identity
→ ControlNet
→ LoRA/IPAdapter
→ A/B Compare
→ Performance [PASS]
→ Clean install / external first-user Quick Start
→ Public beta
```
