# Known Limitations

## 1. Preview는 최종 이미지가 아닙니다

Preview (중간 미리보기)는 x0를 Latent2RGB 또는 TAESD로 빠르게 디코드한 근사입니다.

잘 보는 것:
- 구도
- 실루엣
- 큰 색 덩어리
- 구조가 형성/붕괴하는 시점

정확하지 않을 수 있는 것:
- 미세 재질
- 최종 VAE 색
- 얼굴 세부
- 노이즈 제거 후 최종 edge

---

## 2. 수치는 인과 증명이 아닙니다

`CFG delta`가 커졌다고 CFG가 문제라고 확정할 수 없습니다. `Control residual`이 커졌다고 ControlNet이 더 정확하다고 볼 수도 없습니다.

이 도구는:
- 원인 후보를 좁힘
- 비교 실험 위치를 정함
- 변곡점을 찾음

까지 지원합니다. 최종 인과는 고정 Seed A/B 실험으로 검증합니다.

---

## 3. Control residual magnitude의 의미

Residual 크기는 모델 계열, dtype, block, resolution에 따라 scale이 다릅니다.

따라서:
- 서로 다른 모델 간 절대값 비교 금지
- 같은 workflow에서 한 파라미터만 바꾼 상대 비교 권장
- block별 의미 해석은 전용 Adapter 필요

---

## 4. Sampler마다 모델 호출 횟수가 다릅니다

하나의 visible step에서 모델이 여러 번 호출될 수 있습니다.

따라서:
- `cfg.eventCount`
- `control.eventCount`

가 step마다 1이 아닐 수 있습니다. 현재 구현은 callback 사이에 발생한 여러 이벤트를 집계합니다.

---

## 5. 표준 경로를 우회하는 커스텀 sampler

다음 경우 Advanced Trace가 잡히지 않을 수 있습니다.

- `CFGGuider`를 사용하지 않음
- `ModelPatcher` wrapper를 복사하지 않음
- 자체 모델 객체를 생성
- 독자 CUDA pipeline을 호출

그래도 frontend Node Timeline은 남습니다. 내부 분석은 전용 Adapter가 필요합니다.

---

## 6. 모든 커스텀 노드 의미를 자동 해석하지 않습니다

범용적으로 알 수 있는 것:
- 실행 순서
- 실행 시간
- 입출력 타입
- Tensor summary
- MODEL patch key

코드를 읽어야 알 수 있는 것:
- 독자 라이브러리 내부 의미
- custom CUDA kernel
- private state
- opaque object mutation

---

## 7. LoRA/IPAdapter 영향량은 근사 해석입니다

현재 구현은:
- prompt node class/parameter
- ModelPatcher patch count
- transformer patch key

를 연결합니다.

아직 하지 않는 것:
- LoRA layer별 실제 activation 영향량
- IPAdapter attention map
- token별 image reference contribution

이 기능은 비용과 모델별 차이가 커서 별도 R&D입니다.

---

## 8. Advanced Tensor 통계는 느립니다

원인:
- GPU Tensor 표본 통계
- CPU synchronization
- Control residual 다수 Tensor 순회
- Preview 추가 decode
- 디스크 쓰기

Advanced의 `persist_tensor_stats=true`는 분석용 고비용 캡처입니다. 상시 추적에서 이 수치가 필요 없으면 해당 옵션을 끕니다.

---

## 9. Preview decode 중복

ComfyUI 기본 live Preview callback과 Trace Preview 저장은 각각 디코드할 수 있습니다. 현재 wrapper는 원본 callback을 보존하기 때문에 두 번 decode될 수 있습니다.

후속 최적화 후보:
- 기존 Preview bytes 공유
- server binary event intercept
- preview_every 증가

---

## 10. Frontend event persistence

Node Timeline persistence는 브라우저 extension이 공식 WebSocket 이벤트를 받아 backend로 돌려보내는 구조입니다.

제한:
- headless 실행에서는 sampling trace만 저장
- 여러 브라우저가 같은 서버를 보면 event 중복 가능
- backend `promptId → runId` 연결은 동시 client 2건에서 검증됨
- 여러 브라우저가 같은 frontend event를 중복 저장하는 de-dup은 아직 없음

---

## 11. Cache 영향

`Trace Model.IS_CHANGED`는 매 queue마다 새 run을 만들기 위해 NaN을 반환합니다. 이로 인해 downstream sampler cache가 무효화될 수 있습니다.

이는 추적 도구의 의도된 동작이지만, cache 분석용 별도 mode가 필요할 수 있습니다.

---

## 12. Video / Nested Latent

Tensor summary는 nested latent 첫 Tensor를 처리하지만:
- 시간축 Preview
- frame별 metric
- 영상 sampler segment

는 아직 전용 UI가 없습니다.

---

## 13. 저장 데이터와 개인정보

로컬에 다음이 저장될 수 있습니다.
- Prompt text
- 모델/LoRA 파일명
- workflow scalar settings
- Preview 이미지

외부 전송은 하지 않지만 공유 전 `run.json/report`을 확인해야 합니다.

---

## 14. 자동 튜닝은 아직 없습니다

현재는 관찰·비교·메모 단계입니다. 다음은 후속 기능입니다.

```text
관찰 규칙
  ↓
조절 후보 추천
  ↓
A/B 실험 자동 생성
  ↓
사용자 승인 후 workflow 변경
```

자동으로 workflow 파라미터를 변경하지 않습니다.

---

## 15. 네트워크 노출과 접근 경계

Trace Inspector의 REST route와 Preview/report 파일은 ComfyUI 서버와 같은 접근 경계를 사용합니다.

따라서 ComfyUI를 `--listen 0.0.0.0`으로 외부 네트워크에 열면 다음 데이터도 접근 대상이 될 수 있습니다.

- Prompt text
- 모델/LoRA 파일명
- Step Preview
- Run report
- Run 삭제 route

권장:
- 신뢰 가능한 로컬 네트워크에서만 사용
- 공개 인터넷에 직접 노출하지 않음
- 원격 사용 시 ComfyUI 앞단 인증/프록시 정책을 함께 사용

---

## 16. Static Custom Node Inventory는 Runtime 증명이 아닙니다

Scanner는 source/manifest/Git metadata를 읽고 Python AST의 선언·심볼·호출 지점을 분석합니다. 원문 문자열은 네트워크·subprocess 위험 플래그에만 제한적으로 사용합니다. 다른 custom node를 import하거나 실행하지 않는 대신 다음을 놓칠 수 있습니다.

- 동적으로 생성되는 `NODE_CLASS_MAPPINGS`
- import 시 등록되는 node
- compiled extension / custom CUDA 내부
- 외부 라이브러리 내부 sampler/model patch
- 실제 workflow에서 실행되지 않는 dead code
- module import 단계에서만 발생하는 monkey patch

따라서 `Priority A`, `dedicated_adapter=required` 같은 값은 **수동 source review와 Runtime 테스트 순서를 정하는 신호**입니다. 위험성이나 실제 실행을 확정하는 판정이 아닙니다.
