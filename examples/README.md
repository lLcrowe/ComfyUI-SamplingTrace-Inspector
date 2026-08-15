# Examples

## 1. 최소 연결

```text
Checkpoint MODEL
  ↓
Trace Model (Sampling Inspector)
  ↓
KSampler
```

`Trace Model` 출력:

```text
MODEL         → 기존 KSampler
TRACE_SESSION → Trace Export / Finalize (선택)
```

## 2. LoRA / IPAdapter 포함

```text
Checkpoint
  ↓
LoRA
  ↓
IPAdapter
  ↓
Trace Model
  ↓
KSampler
```

## 3. ControlNet 포함

MODEL 선:

```text
Checkpoint → LoRA/IPAdapter → Trace Model → KSampler
```

CONDITIONING 선:

```text
Positive/Negative → ControlNet Apply → KSampler
```

## 4. Probe

```text
VAE Encode → Trace Latent → KSampler latent_image
```

```text
Preprocessor Image → Trace Image → ControlNet Apply image
```

## 5. JSON fragment

`trace_workflow_fragment.json`은 standalone workflow가 아닙니다. API prompt에서 `<UPSTREAM_MODEL_NODE>`와 KSampler model link를 실제 node id로 교체할 때 참고하는 구조 예시입니다.
