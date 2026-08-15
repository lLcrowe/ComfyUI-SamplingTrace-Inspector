# ComfyUI Sampling Trace Inspector — Test Plan

## 1. 테스트 원칙

이 도구는 **관찰 도구**이므로 최우선 계약은 다음입니다.

> Trace On/Off가 생성 결과를 바꾸면 안 됩니다.

성능 저하는 측정·조절할 수 있지만 결과 변경은 구조 오류로 판정합니다.

---

## 2. Gate -1 — Installed Custom Node Inventory

### 절차

```bash
python scripts/scan_custom_nodes.py \
  --comfy-root "<actual comfy root>" \
  --output-dir docs
```

확인:

- scanner가 다른 custom node를 import/실행하지 않음
- 5개 inventory/plan 산출물 생성
- Scan/Parse error 검토
- Priority A package 실제 사용 여부 확인
- `LOCAL_ADAPTER_PLAN.md` 작성

### 통과 조건

- 현재 설치된 package/commit/source fingerprint 기록
- Runtime Hook을 우회할 가능성이 있는 package 식별
- Phase 5 전용 Adapter 범위 고정

---

## 3. Gate 0 — Import / UI

### 절차

```bash
python scripts/static_check.py
pytest -q
python scripts/comfy_integration_smoke.py
```

ComfyUI 시작 후:
- terminal import error 확인
- browser console 확인
- node search 확인
- bottom panel 확인

### 통과 조건
- `Trace Model` 검색 가능
- `Sampling Trace Inspector` panel 표시
- route `/trace-inspector/health`가 `ok=true`

---

## 4. Gate 1 — 최소 Sampling Trace

### Workflow

```text
Checkpoint Loader
  MODEL → Trace Model → KSampler
  CLIP  → Sampling Trace CLIP → Positive / Negative Text Encode → KSampler
                      prompt_trace → Trace Model
  VAE   ← KSampler Latent → VAE Decode → Save Image
```

### 설정
- 512×512
- 8 steps
- fixed seed
- Advanced
- preview_every=1

실서버 단일 모드 검증은 metadata-free cold 서버에서 다음 스크립트를 Off/On 각각 실행합니다.

```powershell
python scripts/validate_prompt_capture_live.py --mode off --output-prefix TraceInspectorValidation/prompt_capture_off
python scripts/validate_prompt_capture_live.py --mode on --output-prefix TraceInspectorValidation/prompt_capture_on
```

### 확인
- 기존 live Preview 표시
- run 폴더 생성
- `steps.jsonl` 8개 전후 record
- Preview 8장 전후
- Sigma 감소
- x/x0 shape 정상
- CFG event 존재
- `run.json.promptTokenization.status=captured`
- 표준·커스텀 sampler의 Positive/Negative 역할과 실제 CLIP-L/CLIP-G token ID·weight가 직접 tokenizer 반환 객체와 동일
- Trace CLIP 전후 `tokenize()` 반환 객체 identity/equality와 Conditioning 결과가 보존됨
- 패널의 Text Prompt & Tokens에서 원문·encoder·token 선택·원시 token 접기 표시

### 통과 조건
- 최종 이미지 생성 성공
- report.md/html 열림
- panel slider 작동
- prompt token 구역의 빈 상태·CLIP 미연결 안내·실제 capture 상태가 구분됨

---

## 5. Gate 2 — 결과 불변성

### 절차

A:
```text
MODEL → KSampler
```

B:
```text
MODEL → Trace Model → KSampler
```

모든 설정과 Seed를 동일하게 둡니다.

### 비교
- PNG pixel hash
- decoded pixel exact equality
- metadata 차이는 제외 가능

### 통과 조건
- Pixel data 동일

다르면 확인 순서:
1. wrapper callback 순서
2. model clone
3. pre-CFG hook 반환값
4. Control wrapper 부작용
5. dtype/device 변경 여부

---

## 6. Gate 3 — Mode 비용

동일 workflow를 5회 반복하고 첫 회 warm-up을 제외합니다.

| Mode | Time | VRAM peak | Trace disk | Result hash |
|---|---:|---:|---:|---|
| Off | | | | |
| Basic | | | | |
| Advanced (`persist_tensor_stats=false`) | | | | |
| Advanced (`persist_tensor_stats=true`) | | | | |

### 통과 기준 제안
실사용 허용치는 사용자 환경에서 결정하되:
- Basic은 눈에 띄는 지연이 작아야 함
- Advanced는 R&D 사용 가능 수준
- Advanced의 Tensor 통계 활성 상태는 명시적으로 비싼 캡처여도 됨
- 모든 Mode 결과 hash 동일

---

## 7. Gate 4 — Preview 간격

각 설정을 실행합니다.

```text
preview_every = 1 / 2 / 5
persist_previews = true / false
```

확인:
- 마지막 step은 항상 저장
- false일 때 수치 trace는 남음
- 파일 수가 예상과 맞음
- slider가 Preview 없는 step을 처리

---

## 8. Gate 5 — ControlNet

## 8.1 Depth

고정:
- Seed
- Prompt
- Model
- Preprocessor output

변경:

```text
strength = 0.0 / 0.5 / 1.0
end_percent = 0.5 / 0.75 / 1.0
```

확인:
- strength 0에서 residual 영향이 없거나 매우 낮음
- end_percent 이후 active event 패턴 변화
- Preview에서 구조 유지 시점 확인

## 8.2 OpenPose

관찰:
- 초기 실루엣
- 중기 관절/몸통 방향
- 후기 얼굴·손·의상에 의한 구조 변화

### 주의
Residual magnitude가 이미지 품질이나 pose 정확도를 직접 의미하지 않습니다. Preview 관찰과 같이 봅니다.

---

## 9. Gate 6 — CFG

```text
CFG = 1 / 4 / 7 / 10
```

확인:
- condScale 표시
- CFG delta event 존재
- CFG 1 최적화 경로에서 uncond가 생략되는지 확인
- sampler별 eventCount 차이 기록

CFG 1에서 cond/uncond 두 출력이 없으면 `delta=unavailable`을 정상 처리해야 합니다.

---

## 10. Gate 7 — LoRA

```text
strength_model = 0 / 0.5 / 1.0
strength_clip  = 0 / 0.5 / 1.0
```

확인:
- prompt semantic adapter에 LoRA 표시
- Model Snapshot patch count 변화
- Trace Model을 LoRA 앞/뒤에 둔 차이 문서화
- 최종 권장 위치는 LoRA 뒤

---

## 11. Gate 8 — IPAdapter

사용자의 실제 IPAdapter custom node 구현을 대상으로 합니다.

변경:
- weight
- start/end
- weight type
- reference image

확인:
- graph node semantic summary
- transformer patch key
- Preview에서 참조 특징이 형성되는 시점
- 모델 구현이 표준 wrapper를 우회하는지

표준 데이터만으로 부족하면 전용 Adapter 또는 wrapper를 추가합니다.

---

## 12. Gate 9 — Multi-segment workflow

예:

```text
KSampler 1
  ↓
Latent upscale
  ↓
KSampler 2
```

확인:
- segmentIndex 0/1 분리
- 각 segment Sigma list 분리
- Preview filename 충돌 없음
- report에 둘 다 표시

---

## 13. Gate 10 — Cache / Queue / Interrupt

### Cache
동일 workflow 재실행:
- Trace Model은 새 session 생성
- execution_cached 목록 표시
- downstream sampler가 실제 재실행되는지 확인

### Interrupt
중간 중단:
- 앞 step JSONL 보존
- status interrupted/error 반영
- 깨진 JSON 없음

### Queue
여러 prompt queue:
- runId 혼선 없음
- frontend event가 올바른 run에 연결

---

## 14. Gate 11 — Probe nodes

각 Probe의 전후 hash/identity를 확인합니다.

- Trace Image
- Trace Latent
- Trace Mask
- Trace Conditioning
- Trace Model Snapshot

통과 조건:
- 출력 객체/값을 변경하지 않음
- summary 기록

---

## 15. Gate 12 — Model families

| Family | Preview | Step trace | CFG | Control | Status |
|---|---|---|---|---|---|
| SD 1.5 | | | | | |
| SDXL / Illustrious XL | | | | | |
| Flux | | | | | |
| Qwen Image | | | | | |
| Video / nested latent | | | | | |

첫 제품 완료 기준은 SDXL / Illustrious XL입니다.

---

## 16. 시각 판정 기록 형식

각 실험마다:

```text
Observation
- 실제 Preview에서 보인 변화

Hypothesis
- 그 변화의 원인 추정

General Principle
- 다른 workflow에도 적용할 수 있는 원리

Personal Fit
- 현재 사용자 workflow에 채택할지
```

수치와 인과를 혼동하지 않습니다.
