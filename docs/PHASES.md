# ComfyUI Sampling Trace Inspector — Phase 0~7

## 전체 요약

| Phase | 목표 | 이 초안 상태 | Codex 실제 환경 작업 |
|---|---|---|---|
| **0** | 기준·스키마·설치된 Custom Node Inventory | 구현 완료 | 실제 설치본 scan·Priority A 검토 |
| **1** | 범용 실행 추적 | 구현 | 실제 WebSocket 이벤트 검증 |
| **2** | Step Preview Timeline | 구현 | SDXL/Illustrious 실생성 검증 |
| **3** | x/x0/Sigma/CFG 데이터화 | 구현 | 값·성능·callback 순서 검증 |
| **4** | ControlNet Runtime Trace | 구현 초안 | residual 구조와 step 대응 검증 |
| **5** | LoRA/IPAdapter/Model Patch Trace | 구현 초안 | 커스텀 노드별 patch key Adapter 보강 |
| **6** | A/B Compare / Export | 구현 | UI와 보고서 실사용 검증 |
| **7** | 배포·호환성·문서 | 문서 초안 | 설치본 테스트·스크린샷·릴리스 |

---

## Phase 0 — Research, Contract & Installed Node Inventory

### 목표
- ComfyUI 공식 실행 구조 확인
- Hook 지점과 Trace JSON schema 고정
- 사용자의 실제 `custom_nodes`를 import 없이 정적 조사
- Priority A/B/C와 전용 Adapter 범위 고정

### 구현 산출물
- `docs/RESEARCH_NOTES_2026-08-12.md`
- `trace_inspector/config.py`
- `trace_inspector/session.py`
- `trace_inspector/store.py`
- `trace_inspector/custom_node_inventory.py`
- `scripts/scan_custom_nodes.py`
- `docs/CUSTOM_NODE_SCAN_GUIDE.md`
- `docs/CUSTOM_NODE_INVENTORY_SCHEMA.md`

### 실제 설치본 산출물
- `docs/CUSTOM_NODE_INVENTORY.json`
- `docs/CUSTOM_NODE_INVENTORY.md`
- `docs/TRACE_COMPATIBILITY_MATRIX.md`
- `docs/ADAPTER_PRIORITY.md`
- `docs/LOCAL_ADAPTER_PLAN.md`

### 완료 조건
- Target ComfyUI commit가 기록됩니다.
- 설치된 custom node의 source fingerprint와 Git commit이 기록됩니다.
- Priority A package의 실제 사용 여부와 missing trace signal이 검토됩니다.
- callback/wrapper 시그니처가 설치본과 일치합니다.

---

## Phase 1 — Generic Execution Trace

### 목표
모든 workflow에 대해 노드 실행 흐름을 봅니다.

### 구현 산출물
- 공식 WebSocket event listener
- Node start/end duration
- Cache/Error/Progress log
- Run list

### 완료 조건
- 기본 txt2img에서 모든 실행 노드 순서가 기록됩니다.
- cache 재실행 시 cached 노드를 구분합니다.

---

## Phase 2 — Preview Timeline

### 목표
ComfyUI Preview (중간 미리보기)를 실행 후 다시 재생합니다.

### 구현 산출물
- callback wrapping
- Preview decoder
- step image persistence
- slider viewer
- Preview change score

### 완료 조건
- 30-step 생성 결과에서 step timeline이 재생됩니다.
- 기존 ComfyUI live Preview가 그대로 작동합니다.

---

## Phase 3 — Sampling Metrics

### 목표
Preview 옆에 현재 생성 상태를 수치로 붙입니다.

### 구현 산출물
- x summary
- x0 summary
- Sigma
- CFG delta
- Basic/Advanced mode (`persist_tensor_stats`로 Advanced 고비용 통계 선택)

### 완료 조건
- 같은 Seed/설정에서 trace가 재현 가능한 범위로 유사합니다.
- trace On/Off 결과 이미지가 동일합니다.

---

## Phase 4 — ControlNet Runtime Trace

### 목표
ControlNet이 실제로 어느 step에 얼마나 큰 residual을 전달하는지 봅니다.

### 구현 산출물
- APPLY_MODEL wrapper
- control active event
- residual shape/statistics
- start/end/strength semantic summary

### 완료 조건
- ControlNet off일 때 `active=false`입니다.
- start/end 범위 변화가 timeline에서 드러납니다.
- strength 변화와 residual summary 관계를 확인합니다.

---

## Phase 5 — Model Patch Trace

### 목표
Inventory에서 선정된 실제 설치 LoRA/IPAdapter/Detailer/Regional/Tiled/Qwen/Custom Sampler의 그래프 실행과 런타임 영향을 분리합니다.

### 구현 산출물
- ModelPatcher snapshot
- transformer patch key
- Inventory 기반 package-specific semantic/runtime adapter
- Adapter Registry

### 완료 조건
- LoRA 적용 전후 weight patch count 차이가 보입니다.
- IPAdapter 적용 시 attention 관련 patch key가 확인됩니다.
- 지원하지 않는 구현은 generic trace로 안전하게 fallback합니다.

---

## Phase 6 — Compare & Export

### 목표
튜닝 전후를 근거 있게 비교합니다.

### 구현 산출물
- Run A/B 설정 diff
- Step pair Preview
- CFG/Control metrics diff
- Markdown/HTML/JSON export

### 완료 조건
- 동일 Seed에서 한 파라미터만 변경한 비교가 가능합니다.
- 보고서를 외부 브라우저에서 열 수 있습니다.

---

## Phase 7 — Productization

### 목표
다른 ComfyUI 설치에서도 재현 가능한 패키지로 닫습니다.

### 작업
- 지원 버전 표
- 설치/제거 문서
- 성능 benchmark
- 실제 스크린샷
- sample workflows
- Registry metadata
- 릴리스 ZIP

### 완료 조건
- 새 ComfyUI portable 설치에서 복사→재시작→실행이 됩니다.
- 최소 SDXL/Illustrious workflow 3개를 통과합니다.
- Known limitations가 실제 검증 결과로 갱신됩니다.

---

## 제품 완료선

```text
Phase 0~3 = 관찰 도구
Phase 4~5 = 원인 추적·튜닝 도구
Phase 6~7 = 배포 가능한 제품
```

현재 제공되는 것은 **Phase 0~7 전체 구조가 들어간 구현 초안**입니다. 실제 Production Ready 판정은 Codex가 사용자의 ComfyUI 설치본에서 통합 테스트를 통과한 뒤 내립니다.
