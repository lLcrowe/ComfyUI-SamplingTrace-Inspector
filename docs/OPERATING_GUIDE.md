# 운영 가이드 — 관찰에서 조절까지

## 0. 설치본 조사 게이트

실제 튜닝 전에 현재 설치된 custom node가 어떤 경로로 생성에 개입하는지 분류합니다.

```bash
python scripts/scan_custom_nodes.py \
  --comfy-root "<actual comfy root>" \
  --output-dir docs
```

먼저 확인:

- Priority A 중 실제 workflow에 사용하는 package
- 표준 KSampler/CFGGuider를 우회하는 package
- MODEL patch / CONDITIONING / ControlNet 계열
- Generic Trace로 충분한 package
- 전용 Adapter가 필요한 package

`LOCAL_ADAPTER_PLAN.md`가 채워지기 전에는 모든 설치 노드에 대한 Adapter를 추측해서 만들지 않습니다.

---

## 1. 기본 실험 규칙

한 번에 하나만 바꿉니다.

고정:
- Model
- Seed
- Prompt
- Resolution
- Sampler
- Steps

변경 후보:
- ControlNet strength
- ControlNet end_percent
- CFG
- LoRA weight
- IPAdapter weight

---

## 2. Step 관찰 순서

### Early
대략 전체 step의 0~30%

봅니다:
- 구도
- 카메라
- 큰 실루엣
- 인물 수
- pose 방향

### Middle
대략 30~70%

봅니다:
- 비례
- 얼굴/몸통 방향
- 겹침
- 의상 큰 덩어리
- 참조 이미지 특징

### Late
대략 70~100%

봅니다:
- 스타일
- 얼굴 세부
- 재질
- edge
- 노이즈/과도한 디테일

절대적인 구간이 아니라 비교용 기준입니다.

---

## 3. 대표 패턴

## 패턴 A — 초반부터 pose가 다름

Observation:
- 첫 몇 Preview부터 실루엣이 control hint와 다름

확인:
- Control active
- preprocessor output
- strength
- start_percent

다음 실험:
- strength만 증가
- hint 해상도/형태 확인

## 패턴 B — 초반 pose는 맞고 후반에 무너짐

Observation:
- 중기까지 pose 유지
- 후기 얼굴/의상 렌더링과 함께 구조 변형

확인:
- end_percent
- 후기 Control event
- CFG delta
- LoRA/IPAdapter weight

다음 실험:
- end_percent 증가
- CFG 또는 style LoRA를 각각 감소

## 패턴 C — 너무 딱딱함

Observation:
- pose는 정확하지만 자연스러운 변형이 없음

확인:
- Control strength
- Control residual 상대값
- IPAdapter/CFG 동시 제약

다음 실험:
- Control strength 감소
- end_percent 단축

## 패턴 D — 참조 캐릭터가 중간에 사라짐

Observation:
- 초기 얼굴/헤어 특징이 보였다가 후기 다른 인물로 수렴

확인:
- IPAdapter start/end
- IPAdapter weight
- character LoRA strength
- Prompt token 충돌

다음 실험:
- IPAdapter end 연장
- character LoRA/IPAdapter를 각각 단독 비교

---

## 4. Run Note 형식

```text
Observation
- step 11까지 얼굴형 유지, step 15부터 턱이 넓어짐

Hypothesis
- 후기 style LoRA가 reference face shape보다 우세

Change
- style LoRA 0.8 → 0.6

Result
- step 15 이후 변화량 감소, 얼굴형 유지

Decision
- 0.65 채택
```

---

## 5. A/B 실험 최소 세트

### ControlNet

```text
A: strength 0.5 / end 0.6
B: strength 0.5 / end 1.0
```

### CFG

```text
A: CFG 5
B: CFG 7
```

### LoRA vs IPAdapter

```text
A: LoRA only
B: IPAdapter only
C: both
```

세 항목은 UI의 2-run 비교를 두 번 사용합니다.

---

## 6. 종료 조건

조절을 멈추는 기준:
- 의도한 구조가 early/middle에서 유지됨
- 후기 스타일이 구조를 덮지 않음
- 동일 설정 반복 시 변동을 이해할 수 있음
- 추가 조절의 개선량이 작음

Trace 수치가 예뻐지는 것이 목표가 아니라 **원하는 이미지가 안정적으로 나오는 설정을 찾는 것**이 목표입니다.

---

## 7. 보관·공유 정책

- Run에는 Prompt, 모델 파일명, 설정값, Preview가 포함될 수 있습니다.
- 외부 공유 전 `run.json`, `report.md`, `artifacts/`를 확인합니다.
- ComfyUI를 네트워크에 공개한 환경에서는 Trace route도 같은 접근 경계에 포함된다고 봅니다.
- 불필요한 Run은 패널의 Delete 버튼으로 명시적으로 삭제합니다.
