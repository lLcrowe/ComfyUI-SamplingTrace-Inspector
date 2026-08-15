# Codex Handoff — ComfyUI SamplingTrace Inspector

## 1. 인계 목표

이 폴더는 설계 문서만 있는 상태가 아니라 다음이 포함된 **구현 초안**입니다.

- ComfyUI custom node entry point
- Trace Model wrapper
- Step Preview capture
- x/x0/Sigma/CFG/Control trace
- Probe nodes
- frontend bottom panel
- local persistence/report/compare
- Adapter SDK
- 설치된 custom node 비실행 정적 scanner와 compatibility matrix
- unit tests / smoke scripts

Codex의 역할은 새로 설계하는 것이 아니라, **먼저 실제 설치된 custom node를 정적 조사한 뒤 사용자의 ComfyUI 설치본에 장착하고 버전 차이를 수정하며 Phase 0~7을 검증**하는 것입니다.

---

## 2. 우선 읽을 파일

1. `README.md`
2. `docs/CUSTOM_NODE_SCAN_GUIDE.md`
3. `docs/CODEX_CUSTOM_NODE_INVENTORY_PROMPT.md`
4. 생성된 `docs/CUSTOM_NODE_INVENTORY.md` / `TRACE_COMPATIBILITY_MATRIX.md` / `ADAPTER_PRIORITY.md`
5. `docs/ARCHITECTURE.md`
6. `docs/PHASES.md`
7. `docs/TEST_PLAN.md`
8. `docs/KNOWN_LIMITATIONS.md`
9. `docs/RESEARCH_NOTES_2026-08-12.md`
10. 코드:
   - `nodes.py`
   - `trace_inspector/runtime_hooks.py`
   - `trace_inspector/session.py`
   - `trace_inspector/server_routes.py`
   - `web/trace_inspector.js`

---

## 3. 수정 대상

### 주 수정 대상

```text
ComfyUI/custom_nodes/ComfyUI-SamplingTrace-Inspector/
```

### 건드리지 말 것
- 사용자의 기존 workflow 파일
- model/checkpoint/LoRA 파일
- 다른 custom node 소스
- ComfyUI core

ComfyUI core 수정은 다음을 모두 확인한 뒤에만 후보로 기록합니다.

1. 공식 wrapper/custom route로 불가능함
2. 작은 compatibility shim으로 불가능함
3. 수정 지점과 rollback이 명확함

사용자 승인 없이 core를 수정하지 않습니다.

---

## 4. 첫 작업 순서

### Step 0 — Installed Custom Node Inventory

Plugin import 전 `docs/CODEX_CUSTOM_NODE_INVENTORY_PROMPT.md`를 수행합니다.

필수 결과:

```text
CUSTOM_NODE_INVENTORY.json
CUSTOM_NODE_INVENTORY.md
TRACE_COMPATIBILITY_MATRIX.md
ADAPTER_PRIORITY.md
LOCAL_ADAPTER_PLAN.md
```

Priority A 실제 사용 package를 확정한 뒤에만 Plugin 통합으로 이동합니다.

### Step A — 환경 고정

다음을 기록합니다.

```text
ComfyUI commit / release
ComfyUI frontend version
Python
PyTorch
CUDA
GPU
Installed custom nodes relevant to tests
```

결과를 `docs/LOCAL_VALIDATION.md`에 씁니다.

### Step B — 정적 확인

```bash
cd ComfyUI/custom_nodes/ComfyUI-SamplingTrace-Inspector
python scripts/static_check.py
pytest -q
python scripts/comfy_integration_smoke.py
```

### Step C — ComfyUI 부팅

확인:
- import error 없음
- route duplicate 없음
- `Trace Model` 노드 검색 가능
- `SamplingTrace Inspector` bottom panel 표시
- browser console error 없음

### Step D — 가장 작은 workflow

```text
Checkpoint → Trace Model → KSampler → VAE Decode → Preview/Save
```

Advanced mode, 8 steps, 512×512로 실행합니다.

### Step E — ControlNet
Depth와 OpenPose를 각각 실행합니다.

### Step F — LoRA / IPAdapter
사용자의 실제 노드 팩을 확인하고 Adapter를 보강합니다.

---

## 5. 핵심 검증 계약

## 5.1 결과 불변성

같은 Seed에서 Trace On/Off 최종 output이 같아야 합니다.

허용:
- 실행 시간 증가
- Preview 저장 파일
- 로그/보고서

불허:
- 생성 결과 변화
- Seed 변경
- callback 누락
- 기존 live Preview 중단

## 5.2 오류 격리

Trace 내부 오류가 발생해도 가능한 한 generation은 계속되어야 합니다.

## 5.3 원본 callback 보존

`runtime_hooks.py`의 `traced_callback`은 기록 후 원본 callback을 호출해야 합니다.

## 5.4 wrapper 순서

다른 custom node wrapper가 이미 있을 때:
- 기존 wrapper를 덮어쓰지 않음
- `add_wrapper_with_key` 사용
- 실행 순서 기록

---

## 6. 예상 호환성 수정 지점

### A. `WrappersMP` 이름/위치
현재 초안:

```python
from comfy.patcher_extension import WrappersMP
```

실제 설치본에서 상수와 메서드를 확인합니다.

### B. OUTER_SAMPLE 인자 순서
초안은 현재 공식 경로의 위치 계약을 사용합니다.

```text
noise, latent_image, sampler, sigmas, denoise_mask,
callback, disable_pbar, seed, latent_shapes
```

다르면 `_argument` / `_replace_argument` compatibility layer만 수정합니다.

### C. Preview decoder

```python
latent_preview.get_previewer(load_device, latent_format)
```

모델 계열별 decoder가 없으면 Preview 없는 Trace도 정상 동작해야 합니다.

### D. Frontend bottom panel
`bottomPanelTabs` API가 다르면 frontend extension 방식만 수정합니다. Backend/trace schema는 유지합니다.

### E. 사용자 디렉터리
`folder_paths.get_user_directory()` 유무를 확인합니다.

---

## 7. 커밋 단위

권장:

1. `chore: record local comfyui validation baseline`
2. `fix: load trace inspector on installed comfyui version`
3. `feat: validate step preview trace on sd/illustrious`
4. `feat: validate controlnet residual timeline`
5. `feat: add installed ipadapter/lora adapters`
6. `feat: validate run comparison and reports`
7. `docs: complete compatibility and benchmark report`

각 커밋은 실행 가능한 상태를 유지합니다.

---

## 8. 완료 보고 형식

```markdown
# Validation result

## Environment
- ...

## Passed
- ...

## Fixed
- file / reason / change

## Remaining
- Structural
- Local
- Cosmetic

## Performance
- Trace Off
- Basic
- Advanced
- Advanced + `persist_tensor_stats=true`

## Evidence
- workflow
- run id
- screenshots
- reports
```

---

## 9. Definition of Done

- [ ] Static custom-node inventory generated without importing packages
- [ ] Priority A packages manually reviewed
- [ ] `LOCAL_ADAPTER_PLAN.md` completed
- [ ] Plugin imports in actual ComfyUI
- [ ] Bottom panel loads
- [ ] Trace Model works with existing KSampler
- [ ] Original live Preview remains
- [ ] Step images and JSONL are saved
- [ ] CFG delta is visible
- [ ] ControlNet active range is visible
- [ ] LoRA/IPAdapter patch summary is meaningful
- [ ] Run A/B comparison works
- [ ] Markdown/HTML report opens
- [ ] Trace On/Off output identity verified
- [ ] Basic/Advanced(`persist_tensor_stats` Off/On) overhead measured
- [ ] `docs/LOCAL_VALIDATION.md` completed
