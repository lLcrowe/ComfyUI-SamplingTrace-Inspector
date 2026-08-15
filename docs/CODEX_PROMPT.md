# Codex 실행 프롬프트

아래 내용을 Codex 작업 세션에서 **Custom Node Inventory 완료 후 두 번째 요청**으로 사용합니다.

---

## 작업 목표

제공된 `ComfyUI-SamplingTrace-Inspector` 구현을 현재 로컬 ComfyUI 설치본에 장착하고, Phase 0~7을 순서대로 검증·수정해 주세요.

이 도구의 목적은 ComfyUI Preview (중간 미리보기)를 step별로 저장하고, 같은 step의 Latent (잠재 표현), x0, Sigma, CFG delta, ControlNet residual, 노드 실행 Timeline을 연결해서 사용자가 다음 파라미터 조절 근거를 얻도록 하는 것입니다.

## 선행 조건

먼저 `docs/CODEX_CUSTOM_NODE_INVENTORY_PROMPT.md`를 수행해 다음 파일이 있어야 합니다.

- `docs/CUSTOM_NODE_INVENTORY.json`
- `docs/CUSTOM_NODE_INVENTORY.md`
- `docs/TRACE_COMPATIBILITY_MATRIX.md`
- `docs/ADAPTER_PRIORITY.md`
- `docs/LOCAL_ADAPTER_PLAN.md`

없다면 Plugin을 실행하거나 다른 custom node를 import하지 말고 Inventory 작업부터 수행하세요.

## 먼저 읽을 것

1. `README.md`
2. `docs/CUSTOM_NODE_SCAN_GUIDE.md`
3. `docs/CUSTOM_NODE_INVENTORY.md`
4. `docs/TRACE_COMPATIBILITY_MATRIX.md`
5. `docs/ADAPTER_PRIORITY.md`
6. `docs/LOCAL_ADAPTER_PLAN.md`
7. `docs/ARCHITECTURE.md`
8. `docs/PHASES.md`
9. `docs/CODEX_HANDOFF.md`
10. `docs/TEST_PLAN.md`
11. `docs/KNOWN_LIMITATIONS.md`
12. `docs/RESEARCH_NOTES_2026-08-12.md`

## 작업 대상

- 제공된 `ComfyUI-SamplingTrace-Inspector` 폴더
- 실제 ComfyUI 설치본의 호환성 확인
- Inventory에서 선정된 Priority A package의 Trace Adapter

## 건드리지 말 것

- 기존 workflow
- checkpoint / LoRA / VAE / ControlNet 모델
- 다른 custom node source
- ComfyUI core

다른 custom node는 읽고 분석할 수 있지만 수정하지 마세요. ComfyUI core 수정이 필요해 보이면 먼저 이유, 공식 hook으로 불가능한 근거, 대안, 수정 범위, rollback을 문서화하고 수정하지 마세요.

---

## 작업 순서

## 0. Inventory 결과 고정

다음을 확인하세요.

- Inventory가 현재 `custom_nodes` source fingerprint와 일치
- Priority A 중 실제 workflow에 사용하는 package 표시
- Dynamic mapping / parse error 수동 검토
- `LOCAL_ADAPTER_PLAN.md`에 테스트 workflow와 missing signal 기록

Custom Node가 업데이트되어 fingerprint가 달라졌다면 이전 JSON을 보존한 뒤 scanner를 다시 실행하세요.

## 1. 환경 기록

현재 항목을 `docs/LOCAL_VALIDATION.md`에 기록하세요.

```text
ComfyUI path / commit / release
ComfyUI frontend version
Python
PyTorch
CUDA
GPU
Custom Node Inventory generated_at / scanner version
Priority A packages and installed commits
```

## 2. 정적/단위 테스트

```bash
python scripts/static_check.py
pytest -q
python scripts/comfy_integration_smoke.py
```

실패하면 원인을 수정하고 다시 실행하세요.

## 3. Plugin Import / UI

확인:

- import error 없음
- route duplicate 없음
- `Trace Model` 검색 가능
- `SamplingTrace Inspector` bottom panel 표시
- browser console error 없음

## 4. 최소 workflow 검증

```text
Checkpoint → Trace Model → KSampler → VAE Decode → Save/Preview
```

설정:

- 512×512
- 8 steps
- fixed seed
- Advanced mode
- preview_every=1

검증:

- 기존 live Preview 유지
- `run.json`, `steps.jsonl`, Preview 이미지 생성
- bottom panel 표시
- x/x0/Sigma/CFG 기록

## 5. 결과 불변성 검증

동일 Seed와 설정으로 Trace On/Off를 실행하고 최종 output hash 또는 픽셀 동일성을 비교하세요. Trace가 결과를 변경하면 다른 기능보다 먼저 수정하세요.

## 6. ControlNet 검증

Depth와 OpenPose 각각:

- strength: 0 / 0.5 / 1.0
- end_percent: 0.5 / 0.75 / 1.0

검증:

- active range
- residual summary
- Preview 변곡점
- Advanced `persist_tensor_stats=true` 비용
- 실제 설치된 Advanced ControlNet 계열 node와 표준 ControlNet의 차이

## 7. 설치된 Priority A Adapter 검증

`LOCAL_ADAPTER_PLAN.md` 순서로 진행하세요.

대표 대상:

- 실제 IPAdapter implementation
- LoRA / LyCORIS implementation
- Detailer / Impact Pack 내부 sampler
- Regional Prompt / Attention Couple
- Tiled Diffusion / MultiDiffusion
- Qwen Image/Edit 관련 custom pipeline
- 기타 자체 KSampler/CFGGuider 경로

각 package마다:

1. Graph node 실행과 Runtime influence를 분리
2. 표준 wrapper에서 이미 잡히는 신호 확인
3. 부족한 신호만 전용 Adapter로 추가
4. Trace On/Off identity test 추가
5. Basic/Advanced(`persist_tensor_stats` Off/On) 비용 측정
6. 실제 workflow evidence를 `LOCAL_VALIDATION.md`에 기록

## 8. A/B Compare 및 보고서

두 Run의 설정 diff, Step Preview, CFG/Control 수치, Markdown/HTML report를 검증하세요.

## 9. 성능 측정

같은 workflow로 다음을 비교하세요.

```text
Trace Off
Basic
Advanced
Advanced + persist_tensor_stats=true
```

측정:

- 총 생성 시간
- VRAM peak
- 디스크 사용량
- Preview 저장 비용
- 결과 hash

---

## 구현 원칙

- 기존 KSampler를 교체하지 않습니다.
- `Trace Model`의 ModelPatcher wrapper 방식을 유지합니다.
- 모든 Tensor 원본을 dump하지 않습니다.
- trace 오류가 generation을 중단시키지 않게 합니다.
- 원본 sampling callback을 반드시 호출합니다.
- Generic Trace가 충분한 package에는 전용 Adapter를 만들지 않습니다.
- 다른 custom node source를 수정하지 않고 Inspector 내부 compatibility adapter로 대응합니다.
- 작은 compatibility shim을 선호합니다.
- 변경은 작은 커밋으로 분리합니다.

## 완료 조건

`docs/CODEX_HANDOFF.md`의 Definition of Done을 모두 검증하고, 결과를 `docs/LOCAL_VALIDATION.md`에 남기세요.

최종 보고에는 다음을 포함하세요.

- Inventory 요약과 Priority A 실제 사용 package
- 수정 파일
- 수정 이유
- 통과 테스트
- 남은 한계
- 성능표
- Trace On/Off hash
- 실제 Run/Report 경로
