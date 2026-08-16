# ComfyUI Sampling Trace Inspector

ComfyUI의 Preview (중간 미리보기)를 출발점으로, 생성 과정의 **노드 실행 흐름**, **Sampling Step (샘플링 단계)**, **Latent (잠재 표현 / 압축된 이미지 정보)**, **x0 (현재 예상 완성 Latent)**, **Sigma (현재 노이즈 강도)**, **CFG (조건 반영 강도)**, **ControlNet residual (제어 잔차)**을 한 타임라인에서 관찰하는 커스텀 노드 패키지입니다.

> 현재 상태: **0.4.0b1 비공개 베타 후보**. 기존 설치본의 기능 경로에 더해, 비공개 저장소에서 새로 복제한 배포본을 별도 ComfyUI·사용자·출력 환경에서 내부 수용 테스트했습니다. 이 작업 머신 밖의 clean install과 외부 첫 사용자의 Quick Start 완주는 아직 별도 검증 항목입니다. 상세 근거는 `docs/LOCAL_VALIDATION.md`와 `docs/BUILD_VALIDATION.md`를 봅니다.

---

## 1. 핵심 목적

기존 작업은 보통 다음과 같습니다.

```text
최종 이미지 확인
  → 결과가 이상함
  → CFG / ControlNet / LoRA / IPAdapter 중 하나를 추측해서 변경
  → 다시 생성
```

Sampling Trace Inspector는 이를 다음처럼 바꿉니다.

```text
Step Preview 관찰
  → 문제가 처음 나타난 step 확인
  → 그 step의 Sigma / CFG delta / Control residual 확인
  → 변경할 파라미터 후보를 좁힘
  → 동일 Seed로 A/B Run 비교
```

최종 결과만 비교하는 도구가 아니라 **생성 과정의 변곡점을 찾는 디버거**입니다.

---

## 2. 구조

기존 KSampler를 대체하지 않습니다. 최종 MODEL 선에 `Trace Model (Sampling Inspector)` 노드를 하나 삽입합니다.

```text
Checkpoint
   ↓
LoRA
   ↓
IPAdapter / 기타 MODEL Patch
   ↓
Trace Model
   ↓
기존 KSampler 또는 표준 ComfyUI sampler 경로
```

ControlNet은 기존 CONDITIONING 선을 그대로 유지합니다.

```text
Positive / Negative Conditioning
   ↓
ControlNet Apply
   ↓
KSampler
```

`Trace Model`은 복제된 ModelPatcher (모델 변경사항 관리자)에 다음 관찰 지점을 등록합니다.

```text
OUTER_SAMPLE wrapper
  └─ Sampling 시작/종료
  └─ 기존 callback을 감싼 Step callback

APPLY_MODEL wrapper
  └─ 실제 모델 호출 시 전달되는 Control residual
  └─ Transformer patch 종류

Pre-CFG hook
  └─ Conditional / Unconditional 출력 차이
```

표준 `CFGGuider → ModelPatcher` 경로를 따르는 sampler라면, 별도 KSampler 교체 없이 추적할 수 있습니다.

---

## 3. 설치 전: 현재 Custom Node Inventory

실제 설치본에 맞는 Adapter 범위를 먼저 고정합니다. 이 단계에서는 다른 custom node를 import하거나 실행하지 않습니다.

```bash
python scripts/scan_custom_nodes.py \
  --comfy-root "<ComfyUI 또는 Windows Portable 루트>" \
  --output-dir docs
```

생성 결과:

```text
docs/CUSTOM_NODE_INVENTORY.json
docs/CUSTOM_NODE_INVENTORY.md
docs/TRACE_COMPATIBILITY_MATRIX.md
docs/ADAPTER_PRIORITY.md
docs/LOCAL_ADAPTER_PLAN.md
```

이 결과로 실제 설치된 ControlNet, IPAdapter, LoRA, Detailer, Regional Prompt, Tiled Diffusion, Qwen 관련 노드가 표준 Hook으로 잡히는지와 전용 Adapter 필요 여부를 결정합니다. 자세한 절차는 `docs/CUSTOM_NODE_SCAN_GUIDE.md`를 봅니다.

---

## 4. 설치

1. 비공개 베타 참여자는 GitHub 인증 후 다음 위치에 clone합니다. ZIP을 받은 경우에도 같은 폴더명이 되도록 압축을 풉니다.

```bash
git clone https://github.com/lLcrowe/ComfyUI-SamplingTrace-Inspector.git ComfyUI/custom_nodes/ComfyUI-SamplingTrace-Inspector
```

최종 설치 위치:

```text
ComfyUI/custom_nodes/ComfyUI-SamplingTrace-Inspector/
```

2. ComfyUI Python 환경에서 선택적으로 확인합니다.

```bash
cd ComfyUI/custom_nodes/ComfyUI-SamplingTrace-Inspector
python scripts/static_check.py
```

3. ComfyUI를 재시작합니다.

4. 노드 검색에서 다음 노드를 찾습니다.

```text
Trace Model (Sampling Inspector)
Sampling Trace CLIP
Trace Export / Finalize
Trace Image
Trace Latent
Trace Mask
Trace Conditioning
Trace Model Snapshot
Trace Note
```

5. 최종 MODEL patch 뒤, KSampler 앞에 `Trace Model`을 연결합니다.

6. ComfyUI 하단의 `Sampling Trace Inspector` 패널을 엽니다.

---

## 5. 권장 연결

```text
[Checkpoint Loader]
  ① CLIP ──→ [Sampling Trace CLIP · Connect Both Prompts]
                   ② CLIP ──┬──→ Positive Text Encode
                            └──→ Negative Text Encode
                   ③ CLIP 프롬프트 추적 보내기 ──────────┐
       MODEL                                             │
         ↓                                               │
[LoRA Loader]
         ↓
[IPAdapter Advanced]
         ↓
[Trace Model] ←──────────────────────────────────────────┘
    MODEL ↓       └── TRACE_SESSION ──→ [Trace Export / Finalize] (선택)
[KSampler]
```

`Sampling Trace CLIP`의 CLIP 출력을 긍정·부정 Text Encode 양쪽에 연결하고, `prompt_trace`를 `Sampling Trace Model`에 연결합니다. 원본 CLIP을 수정하지 않는 proxy가 실제 `tokenize()` 반환값을 그대로 통과시킨 뒤 호출 노드·원문·CLIP-L/G token ID·입력 가중치·단어 묶음을 같은 Run에 기록합니다. 기존 `Sampling Trace Model.clip` 입력은 이전 표준 재토큰화 방식의 호환용으로만 유지합니다.

### `Trace Model`을 마지막 MODEL patch 뒤에 두는 이유

- LoRA / IPAdapter / 기타 패치가 등록된 최종 MODEL 상태를 snapshot할 수 있습니다.
- 실제 sampling 중 어떤 patch key가 활성화되는지 연결하기 쉽습니다.
- 앞에 두어도 clone 과정에서 wrapper가 유지될 수 있지만, 의미 분석이 불완전해질 수 있습니다.

---

## 6. Trace Mode

| Mode | 기록 | 비용 | 용도 |
|---|---|---:|---|
| **Basic** | Step, Preview, shape/dtype/device, 노드 Timeline | 낮음 | 전체 흐름 확인 |
| **Advanced** | Basic + CFG delta + Control 구조. `persist_tensor_stats=true`이면 x/x0·CFG 상세·Control residual과 샘플러 positive/negative 조건의 단계별 단어 주의까지 캡처 | 중간~높음 | 일반 튜닝 및 ControlNet/프롬프트/커스텀 노드 R&D |

처음에는 `Basic`, 내부 영향량을 볼 때는 `Advanced`를 권장합니다. 고비용 Tensor 통계가 필요 없으면 `persist_tensor_stats=false`로 끌 수 있습니다. 이전 workflow의 `Deep` 값은 `Advanced`로 자동 호환됩니다.

---

## 7. Preview 관련 설정

### `preview_every`
Preview를 몇 step마다 저장할지 결정합니다.

```text
1  = 모든 step
2  = 2 step마다
5  = 5 step마다
```

### `preview_max_side`
저장 Preview의 긴 변 최대 크기입니다. 기본 768입니다.

### `preview_decoder`

- `clear` (기본): 모델 계열에 맞는 TAESD가 설치되어 있으면 이를 사용해 잠재 해상도가 아닌 실제 이미지 크기에 가까운 선명한 Preview를 저장합니다.
- `fast`: Latent2RGB를 사용합니다. 빠르지만 원본이 잠재 해상도라 패널에서 확대하면 픽셀이 크게 보일 수 있습니다.

`clear`도 TAESD가 없으면 자동으로 `fast` 방식으로 대체됩니다. 이 설정은 Trace 저장용 Preview에만 적용되며 ComfyUI의 기존 Live Preview 설정은 바꾸지 않습니다.

### `persist_previews`
끄면 이미지 저장 없이 수치 Trace만 남깁니다.

### Preview의 의미

저장되는 Preview는 최종 VAE Decode 이미지가 아닙니다.

```text
현재 step의 x0
  ↓
Trace Preview decoder
  ├─ clear → 모델별 TAESD → 없으면 Latent2RGB
  └─ fast  → Latent2RGB
  ↓
빠른 근사 Preview
```

따라서 Preview는 **형태가 언제 잡히고 무너지는지**를 보는 용도이며, 최종 재질·색·미세 디테일의 정확한 판정용은 아닙니다.

---

## 8. 패널 기능

### Run List
- 실행 시 활성 워크플로 파일명 / Label / Status / Step 수
- 최근 실행 선택
- 실행이 많아지면 제목은 고정되고 목록만 세로로 스크롤됩니다.

워크플로 이름은 로컬 절대경로 없이 파일명만 `run.json`과 보고서에 저장됩니다. 저장되지 않은 워크플로나 API 실행은 기존 Label 또는 Run ID로 표시됩니다.

가운데 작업 영역과 우측 `Selected Run / Compare Runs` 사이 경계선을 드래그하면 우측 폭을 조절할 수 있습니다. 폭은 현재 브라우저에 저장되며, 경계선을 더블클릭하면 기본 폭으로 돌아갑니다.

일반 생성은 성공했지만 `Sampling Trace Model`이 실행 그래프에 없어서 새 Run이 생기지 않은 경우, 패널 상단에 `최종 MODEL → Sampling Trace Model → 샘플러` 연결 안내가 표시됩니다.

### Step Viewer
- Step 슬라이더
- Preview
- Sigma
- Preview 변화량
- x0 mean/std
- CFG delta
- Control residual summary

### Node Timeline
- 노드 실행 시작/종료
- 캐시 사용
- 진행률
- 실행 시간
- 오류/중단

### Sampler Positive / Negative Conditions
- 표준·커스텀 sampler의 `positive` / `negative` 소켓을 역추적한 역할
- `Advanced + persist_tensor_stats=true` 실행의 각 step에서 실제 Q/K로 관측한 positive/negative CONDITIONING 단어별 교차 주의 평균
- 부분 토큰은 실제 원문과 CLIP 단어 경계에 맞춰 사람이 읽는 단어로 합치고, 같은 단어의 반복 출현은 하나로 합산
- 상단 이미지 미리보기에서 선택한 step과 자동 연동되는 전체 단어 막대와, 고급 펼침의 읽기 전용 전체 step×단어 흐름. 긴 목록은 내부 세로 스크롤로 확인하며 텍스트 구역에는 별도 step 선택기를 두지 않습니다.
- `Sampling Trace CLIP`을 한쪽 Text Encode에만 연결한 실행은 반대쪽 주의 수치를 잘못된 단어에 붙이지 않고, 해당 `positive` 또는 `negative` 연결 안내를 표시합니다.

프롬프트의 token ID와 CONDITIONING 입력은 실행 중 고정되어 있고, latent·sigma가 변하면서 각 단어 위치를 참조하는 교차 주의 비중이 step마다 달라집니다. 단계별 관측은 일부 공간 query를 표본화하고 모든 text key와 cross-attention layer를 평균한 근사 비중입니다. 화면에서는 특수·padding·구두점을 제외하고 부분 토큰과 반복 출현을 단어별로 합산하지만, 특정 단어가 화질을 몇 % 만들었다는 인과적 기여율은 아닙니다. 샘플러 `positive` 조건은 옅은 파랑, `negative` 조건은 옅은 빨강으로 같은 화면에 표시합니다.

실제 호출 원문, encoder chunk, token ID, 부분 조각, 입력 가중치와 특수·padding 토큰은 계산·저장 증거로 보존하되 일반 패널에는 중복 표시하지 않습니다.

### A/B Compare
- 실행 A/B 설정 차이
- workflow hash·node 수와 요청 sampler → 실제 sampler 비교
- 같은 순번 step Preview·x0·CFG·Control 수치 비교
- MODEL patch snapshot 비교
- `Build A/B reports`로 Markdown/HTML 저장
- Run의 backend `promptId`로 동시 실행 연결 확인

비교 수치는 관측 증거이며 품질 원인의 인과 비율을 뜻하지 않습니다.

### Notes
- Observation (관찰)
- Hypothesis (가설)
- Decision (결정)
- Issue (문제)
- 선택한 Run 안에서 저장된 노트를 다시 보고, 내용·분류를 수정하거나 개별 삭제할 수 있습니다.
- 우측 전체가 메모 영역은 아닙니다. `Selected Run` 안의 입력줄과 `Notes` 목록만 선택한 Run에 귀속되는 메모입니다.
- 메모 화면은 `관찰 / 가설 / 결정 / 문제`로 표시하지만 저장 스키마는 호환성을 위해 `observation / hypothesis / decision / issue`를 유지합니다.
- 노트 추가·수정·삭제 시 기존 `report.md`와 `report.html`이 함께 갱신됩니다.

---

## 9. 저장 위치

기본적으로 ComfyUI 사용자 디렉터리 아래에 저장합니다.

```text
ComfyUI/user/trace_inspector/runs/<run_id>/
├─ run.json
├─ steps.jsonl
├─ probes.jsonl
├─ frontend_events.jsonl
├─ report.md
├─ report.html
└─ artifacts/
   ├─ segment_00_step_0000.jpg
   ├─ segment_00_step_0001.jpg
   └─ ...
```

`run.json`의 `promptTokenization`에는 지원되는 표준 프롬프트의 원문과 실제 토큰 기록이 들어갑니다. 프롬프트와 모델 파일명은 민감할 수 있으므로 GitHub에 Run 폴더를 함께 공개하기 전 내용을 확인하세요.

`folder_paths.get_user_directory()`를 사용할 수 없으면 플러그인 내부 `data/runs/`로 fallback합니다.
노트와 Run은 사용자 실행 데이터이며 소스 배포 파일이 아닙니다. fallback `data/`도 `.gitignore`에 포함되어 GitHub 저장소에 기본적으로 커밋되지 않습니다.

---

## 10. Probe 노드

### Trace Image
IMAGE (이미지)의 shape, 범위, 평균, 표준편차를 기록하고 그대로 통과시킵니다.

### Trace Latent
LATENT 내부 `samples` Tensor (다차원 숫자 배열)를 요약하고 그대로 통과시킵니다.

### Trace Conditioning
CONDITIONING (생성 조건 정보)의 Tensor 구조와 metadata key를 요약합니다.

### Trace Model Snapshot
MODEL의 weight patch 수, transformer patch 종류, wrapper/callback 수를 기록합니다.

Probe는 원본 데이터를 변경하지 않는 passthrough 노드입니다.

---

## 11. 성능 정책

- Tensor 전체 값을 저장하지 않습니다.
- 최대 65,536개 원소만 균등 표본으로 통계를 계산합니다.
- Control residual은 그룹별 통계만 저장합니다.
- Preview 간 변화량은 128×128 축소 이미지로 계산합니다.
- 추적 오류가 generation 실패로 전파되지 않도록 wrapper 내부에서 격리합니다.
- Preview 저장 간격과 Mode로 비용을 조절합니다.

---

## 12. 테스트

독립 환경 테스트:

```bash
pytest -q
python scripts/static_check.py
```

ComfyUI 설치 환경 통합 확인:

```bash
python scripts/comfy_integration_smoke.py
```

실제 생성 검증은 `docs/TEST_PLAN.md` 순서로 진행합니다.

---

## 13. 현재 지원 범위

### 구현됨
- 공식 WebSocket 실행 이벤트 수집
- Step callback wrapping
- Preview 저장
- x / x0 / Sigma 기록
- CFG delta 요약
- Control residual 요약
- LoRA / IPAdapter / ControlNet / KSampler semantic adapter
- Run 저장·보고서·A/B 비교
- 하단 패널
- 실제 CLIP 호출 기반 Positive/Negative 원문·CLIP-L/G 토큰 보기와 보고서 요약

### 실제 설치본에서 검증됨
- frontend bottom panel·확대 보기·독립 수직 스크롤·가변 우측 패널·Notes
- 표준 KSampler Trace On/Off decoded pixel 동일성
- SDXL / Illustrious XL Preview
- OpenPose·Depth ControlNet residual과 A/B Preview
- `comfyui_ipadapter_plus` attention patch와 A/B
- `comfyui-easy-use`, `Comfyui-EasyIllustrious` custom sampler 경로
- A/B Markdown/HTML과 backend prompt-to-run 연결
- Off / Basic / Advanced 성능·디스크 기준선

### 추가 호환성 검증 필요
- 실제 패널에서 새 프롬프트 토큰 구역 시각 검수
- Flux / Qwen Image처럼 CLIP 이외 tokenizer API를 쓰는 모델 계열
- 여러 KSampler segment가 있는 workflow
- Flux / Qwen Image / Video 모델 계열

현재 로컬 기준선은 WAI Illustrious v17, 512², Euler/normal, 8 steps, CFG 5.0입니다. N=3 paired 측정에서 Basic·Advanced의 decoded output은 같은 seed의 Off와 동일했고, 자세한 수치와 한계는 `docs/LOCAL_VALIDATION.md`에 있습니다.

---

## 14. 문서

- `docs/CUSTOM_NODE_SCAN_GUIDE.md` — 설치된 custom node 비실행 정적 조사
- `docs/CUSTOM_NODE_INVENTORY_SCHEMA.md` — Inventory JSON 계약
- `docs/CODEX_CUSTOM_NODE_INVENTORY_PROMPT.md` — Codex 선행 조사 프롬프트
- `docs/PRODUCT_SPEC.md` — 제품 목표와 범위
- `docs/ARCHITECTURE.md` — 기술 구조와 Hook 지점
- `docs/PHASES.md` — Phase 0~7 상태
- `docs/CODEX_HANDOFF.md` — Codex 인계 기준
- `docs/CODEX_PROMPT.md` — Codex에 바로 붙여넣을 작업 프롬프트
- `docs/TEST_PLAN.md` — 실제 ComfyUI 검증 시나리오
- `docs/BUILD_VALIDATION.md` — 이 패키지에서 통과한 검사와 미검증 범위
- `docs/IMPLEMENTATION_STATUS.md` — Phase별 코드/통합 상태
- `docs/ADAPTER_SDK.md` — 커스텀 노드 Adapter 확장
- `docs/KNOWN_LIMITATIONS.md` — 한계와 위험
- `docs/GLOSSARY_KO.md` — 영문 용어 + 한국어 설명
- `docs/RESEARCH_NOTES_2026-08-12.md` — 공식 자료 조사 기록

---

## 15. 비공개 베타 피드백

재현 가능한 오류·호환성 문제·사용 중 막힌 지점은 [GitHub Issues](https://github.com/lLcrowe/ComfyUI-SamplingTrace-Inspector/issues)에 남깁니다. 모델 파일, 개인 workflow 원본, 생성 이미지처럼 공개하면 안 되는 자료는 Issue에 첨부하지 말고 재현 가능한 최소 조건만 기록합니다.
