# ComfyUI Sampling Trace Inspector — Product Specification

## 1. 한 줄 정의

ComfyUI의 Preview (중간 미리보기)와 내부 생성 신호를 연결해, 사용자가 **어느 step에서 무엇 때문에 결과가 변했는지 관찰하고 다음 파라미터를 조절**할 수 있게 하는 실행·샘플링 분석 도구입니다.

---

## 2. 핵심 문제

### 2.1 최종 결과만으로 원인을 역추론한다

최종 이미지가 잘못되어도 다음 중 무엇이 원인인지 분리하기 어렵습니다.

- Prompt / Conditioning
- CFG
- Sampler / Scheduler
- ControlNet
- LoRA
- IPAdapter
- Denoise
- Preprocessor

### 2.2 Preview는 보이지만 상태 정보가 연결되지 않는다

사용자는 그림이 변하는 것은 볼 수 있지만 다음을 함께 보기 어렵습니다.

- 현재 Sigma
- x0 통계
- CFG conditional/unconditional 차이
- ControlNet residual
- 현재 실행 노드
- MODEL patch 종류

### 2.3 커스텀 노드는 실행과 실제 영향 시점이 다르다

예:

```text
IPAdapter Apply 노드 실행
  → MODEL에 attention patch 등록
  → 나중에 KSampler 내부 모델 실행 때 실제 영향
```

그래프 노드 실행만 보면 이 차이가 드러나지 않습니다.

---

## 3. 제품 원칙

### P1. Preview-first
사용자가 가장 먼저 이해하는 것은 이미지 변화이므로 Step Preview가 중심입니다.

### P2. Observation과 Hypothesis 분리

```text
Observation: step 14부터 얼굴 폭이 넓어짐
Metric: CFG delta 증가, Control residual 감소
Hypothesis: 후반 prompt/style 영향이 pose control보다 우세해짐
```

수치만으로 원인을 확정하지 않습니다.

### P3. 기존 workflow를 바꾸지 않는다
KSampler 대체 노드가 아니라 MODEL wrapper를 사용합니다.

### P4. 범용 추적 + Adapter 해석

```text
모든 노드
  → 실행시간 / 타입 / 이벤트

지원 Adapter 노드
  → 역할 / 주요 파라미터 / 실제 영향 시점 설명
```

### P5. 측정 때문에 생성이 실패하면 안 된다
Trace 오류는 기록하되 generation 경로로 전파하지 않습니다.

---

## 4. 주요 사용자

### R&D 사용자
- ControlNet strength/start/end 튜닝
- IPAdapter weight/구간 튜닝
- LoRA 충돌 분석
- Sampler 비교

### 파이프라인 제작자
- 복잡한 workflow 실행 순서 확인
- 캐시와 반복 실행 확인
- 커스텀 노드 병목 확인

### 커스텀 노드 개발자
- 노드가 데이터를 즉시 변환하는지 MODEL patch를 등록하는지 설명
- Adapter를 추가해 의미 있는 진단 제공

---

## 5. 핵심 사용 시나리오

## 5.1 ControlNet 튜닝

1. Seed, Prompt, Model을 고정합니다.
2. Advanced mode에서 `persist_tensor_stats=true`로 생성합니다.
3. Step Preview를 이동합니다.
4. 포즈가 처음 흔들리는 step을 찾습니다.
5. 해당 step의 Control residual / CFG delta를 봅니다.
6. ControlNet strength 또는 end_percent를 바꿉니다.
7. A/B Run으로 비교합니다.

## 5.2 LoRA와 IPAdapter 충돌

1. LoRA와 IPAdapter가 적용된 최종 MODEL 뒤에 Trace Model을 둡니다.
2. Model Snapshot에서 patch 종류를 봅니다.
3. Step별 Preview에서 캐릭터 정체성이 바뀌는 시점을 봅니다.
4. IPAdapter weight 또는 LoRA strength를 한 항목씩 변경합니다.
5. 동일 Seed로 비교합니다.

## 5.3 커스텀 노드 분석

1. Node Timeline으로 그래프 실행 시점을 봅니다.
2. 노드가 IMAGE/LATENT를 출력하면 Probe로 전후 데이터를 비교합니다.
3. MODEL patch 노드라면 Model Snapshot 및 runtime patch key를 봅니다.
4. 표준 wrapper 경로를 사용하지 않으면 전용 Adapter 후보로 등록합니다.

---

## 6. 기능 범위

### Execution Trace
- execution_start/success/error/interrupted
- executing/executed/progress/cached
- 노드별 시작/종료/시간

### Sampling Trace
- segment
- step / total steps
- Sigma
- x / x0 Tensor summary
- Preview
- Preview change score

### Runtime Influence
- CFG delta
- Control residual
- transformer patch key
- cond/uncond 배치 정보

### Data Probe
- IMAGE
- LATENT
- MASK
- CONDITIONING
- MODEL

### Comparison
- 설정 diff
- Step pair
- Preview A/B
- CFG/Control 수치 A/B

### Export
- JSON
- JSONL
- Markdown
- HTML
- Preview image bundle

---

## 7. 완료 기준

### Readable
- Run과 Step Preview를 볼 수 있습니다.

### Structured
- Preview와 Sigma/x0/CFG/Control이 같은 Step record에 연결됩니다.

### Established
- ControlNet/LoRA/IPAdapter/KSampler 역할이 Adapter로 설명됩니다.

### Production Ready
- 실제 ComfyUI 버전에서 설치·재시작·생성·보고서·A/B 비교가 반복 검증됩니다.
- 추적 비활성/Basic 상태의 성능 비용이 허용 범위에 있습니다.
- 버전 호환성 표가 작성됩니다.
