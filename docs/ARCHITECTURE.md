# ComfyUI SamplingTrace Inspector — Architecture

## 1. 핵심 판단

ComfyUI 코어를 직접 수정하는 방식보다 **정적 Inventory + 2층 Runtime Trace** 구조가 적합합니다.

```text
Layer 0 — Installed Custom Node Static Inventory
  └─ import/실행 없이 source/manifest/Git 조사
  └─ Priority A/B/C와 Adapter 범위 고정

Layer A — 공식 API / WebSocket
  └─ 모든 노드 실행 추적
  └─ Queue / Cache / Error / Progress

Layer B — ModelPatcher wrapper / CFG hook
  └─ Sampling Step
  └─ x / x0 / Sigma
  └─ CFG delta
  └─ Control residual
```

코어 포크는 사용하지 않습니다.

---

## 2. Inventory 흐름

```text
ComfyUI/custom_nodes
  ↓ filesystem read + Python AST
Custom Node Inventory
  ├─ NODE_CLASS_MAPPINGS
  ├─ MODEL / CONDITIONING / LATENT / IMAGE types
  ├─ ModelPatcher / Sampler / ControlNet signals
  ├─ frontend / route / monkey patch signals
  ├─ Git commit / version / dependency
  └─ source fingerprint
  ↓
Compatibility Matrix + Adapter Priority
  ↓
실제 Runtime 검증 대상 결정
```

정적 Scanner는 custom node를 import하거나 requirements를 설치하지 않습니다. Runtime 동작을 증명하는 것이 아니라 **어디부터 실제로 봐야 하는지 결정**합니다.

---

## 3. Runtime 흐름

```text
User queues workflow
  ↓
PromptExecutor
  ↓ WebSocket
Frontend Trace Panel
  ├─ execution_start
  ├─ executing
  ├─ progress
  ├─ execution_cached
  └─ success/error/interrupted

Trace Model node
  ↓ clone MODEL
ModelPatcher
  ├─ OUTER_SAMPLE wrapper
  ├─ APPLY_MODEL wrapper
  └─ sampler_pre_cfg_function

KSampler / CFGGuider
  ↓
Sampling step callback(step, x0, x, total_steps)
  ↓
TraceSession
  ├─ Tensor summary
  ├─ Preview decode/save
  ├─ CFG event aggregation
  ├─ Control event aggregation
  ├─ JSONL append
  └─ WebSocket custom event
```

---

## 4. `Trace Model`을 사용하는 이유

### 대안 A — KSampler를 새 노드로 복제
문제:
- KSampler 변형마다 별도 대응
- 커스텀 sampler와 중복
- upstream 변경에 취약

### 선택 B — ModelPatcher wrapper 등록
장점:
- 기존 KSampler 유지
- 표준 CFGGuider 경로를 쓰는 sampler 공통 관찰
- LoRA/IPAdapter가 clone한 MODEL에도 wrapper 계층을 유지하기 쉬움
- ComfyUI가 제공하는 wrapper 체계에 맞음

---

## 5. Hook 지점

## 5.1 OUTER_SAMPLE

관찰:
- noise
- input latent
- sampler 객체
- sigmas
- seed
- callback

처리:
- 원래 callback을 `traced_callback`으로 감쌉니다.
- Trace callback 실행 후 원래 Preview callback도 그대로 호출합니다.
- 따라서 ComfyUI의 기존 live Preview를 유지합니다.

## 5.2 Step callback

입력:

```text
step
x0 = 현재 예상 clean latent
x  = 현재 noisy latent
Total steps
```

출력 record:

```json
{
  "step": 12,
  "sigma": 4.812,
  "x": {},
  "x0": {},
  "cfg": {},
  "control": {},
  "previewFile": "segment_00_step_0012.jpg"
}
```

## 5.3 Pre-CFG hook

`conds_out[0]`과 `conds_out[1]`의 bounded sample 차이를 계산합니다.

```text
CFG delta = Conditional prediction - Unconditional prediction
```

전체 Tensor 차이를 생성하지 않고 동일 위치 표본만 빼서 비용을 제한합니다.

## 5.4 APPLY_MODEL wrapper

관찰:
- timestep
- control residual 구조
- cond_or_uncond
- transformer patch / patches_replace key

Advanced mode에서 `persist_tensor_stats=true`일 때만 residual 통계를 계산합니다. 이전 workflow의 `Deep` 값은 Advanced로 정규화합니다.

---

## 6. Preview pipeline

```text
x0 Latent
  ↓
ComfyUI configured Previewer
  ├─ Latent2RGB
  └─ TAESD
  ↓
PIL Image
  ↓ max side resize
JPEG / PNG
  ↓
artifacts/
```

ComfyUI live Preview가 꺼진 경우에도 latent RGB factor가 있으면 Latent2RGB fallback을 시도합니다.

### Preview change score

```text
Current Preview → 128×128 thumbnail
Previous Preview → 128×128 thumbnail
Absolute RGB difference mean / 255
```

이 값은 품질 점수가 아니라 **시각 변화량**입니다.

---

## 7. 데이터 저장

### run.json
작은 최신 상태 snapshot입니다.

### steps.jsonl
Step마다 append합니다. 생성이 중단돼도 앞부분이 남습니다.

### frontend_events.jsonl
브라우저가 받은 노드 실행 이벤트입니다.

### probes.jsonl
Probe와 Note입니다.

### artifacts
Preview 이미지입니다.

---

## 8. Concurrency / Error isolation

- TraceSession은 `RLock`으로 보호합니다.
- JSON은 임시 파일 후 replace로 저장합니다.
- Step은 JSONL append로 기록합니다.
- wrapper 계측 오류는 `record_error` 후 원본 실행을 계속합니다.
- original callback을 반드시 호출합니다.

---

## 9. Adapter 구조

```text
Generic Prompt Node
  ↓
AdapterRegistry
  ├─ KSamplerAdapter
  ├─ ControlNetAdapter
  ├─ LoRAAdapter
  ├─ IPAdapterAdapter
  ├─ VAEAdapter
  └─ CLIPTextAdapter
  ↓
Semantic summary
```

Adapter가 없는 노드도 generic trace는 유지됩니다.

---

## 10. 확장 지점

### NodeSemanticAdapter
커스텀 노드의 역할과 주요 파라미터를 해석합니다.

### Runtime wrapper
표준 APPLY_MODEL 데이터만으로 부족한 노드는 전용 wrapper를 등록할 수 있습니다.

### Probe node
커스텀 데이터 타입을 passthrough하면서 summary를 기록할 수 있습니다.

---

## 11. 가장 취약한 경계

1. ComfyUI frontend bottom panel API 변경
2. ModelPatcher wrapper API 변경
3. 표준 CFGGuider를 우회하는 커스텀 sampler
4. 자체 CUDA kernel 내부에서만 작동하는 커스텀 노드
5. Video / nested latent의 Preview 표현

이 경계는 `docs/TEST_PLAN.md`와 `docs/KNOWN_LIMITATIONS.md`에서 별도로 검증합니다.
