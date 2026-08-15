# Installed Custom Node Static Scan Guide

## 목적

사용자의 실제 `ComfyUI/custom_nodes`를 기준으로 다음을 먼저 확정합니다.

- 어떤 커스텀 노드 패키지가 설치되어 있는가
- 각 패키지는 Data Transform, Conditioning, Model Patching, Sampler/Pipeline Replacement, Frontend Utility 중 어디에 속하는가
- Generic Trace만으로 충분한가
- Runtime Hook이 필요한가
- 전용 Adapter를 먼저 만들어야 하는가

이 단계가 완료되어야 Phase 5가 추상적인 “IPAdapter/LoRA 대응”이 아니라 **실제 설치된 노드 팩 대응**으로 바뀝니다.

---

## 안전 경계

스캐너는 다음을 하지 않습니다.

- 커스텀 노드 import
- `__init__.py` 실행
- `install.py` 실행
- requirements 설치
- subprocess 실행
- 외부 다운로드/네트워크 요청
- 기존 파일 수정

읽는 대상:

- Python/JavaScript/TypeScript/Vue source
- `pyproject.toml`, `package.json`, `requirements*.txt`, `comfyui-node.json`
- `.git/config`, `.git/HEAD`, refs

분석 방법:

- Python AST (구문 트리)
- `INPUT_TYPES`/`RETURN_TYPES` 선언과 실제 호출 지점 추출
- 네트워크·subprocess 위험 플래그의 제한된 정규식 탐색
- Git/manifest 정적 metadata

기본 스캔은 `tests`, `browser_tests`, `examples`, `demo`, `fixtures`, `benchmarks` 계열 보조 디렉터리를 제외합니다. 이 경로까지 조사하려면 `--include-tests`를 명시합니다.

따라서 생성 결과를 바꾸지 않고 설치본을 조사할 수 있습니다.

---

## 실행

### ComfyUI 일반 설치

```bash
cd ComfyUI/custom_nodes/ComfyUI-SamplingTrace-Inspector
python scripts/scan_custom_nodes.py \
  --comfy-root "C:\\Path\\To\\ComfyUI" \
  --output-dir docs
```

### ComfyUI Windows Portable

```powershell
cd C:\Path\To\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-SamplingTrace-Inspector
.\scripts\scan_custom_nodes.ps1 \
  -ComfyRoot "C:\Path\To\ComfyUI_windows_portable" \
  -OutputDir ".\docs"
```

또는:

```cmd
scripts\scan_custom_nodes.cmd "C:\Path\To\ComfyUI_windows_portable" "docs"
```

### `custom_nodes` 직접 지정

```bash
python scripts/scan_custom_nodes.py \
  --custom-nodes "D:\\AI\\ComfyUI\\custom_nodes" \
  --output-dir docs
```

---

## 생성 파일

```text
docs/
├─ CUSTOM_NODE_INVENTORY.json
├─ CUSTOM_NODE_INVENTORY.md
├─ TRACE_COMPATIBILITY_MATRIX.md
├─ ADAPTER_PRIORITY.md
└─ LOCAL_ADAPTER_PLAN.md
```

### `CUSTOM_NODE_INVENTORY.json`

기계가 읽는 정본입니다.

포함:

- 설치 경로
- 폴더명 / 선언된 패키지명 / 버전
- Git remote / commit / branch
- 정적으로 읽힌 `NODE_CLASS_MAPPINGS`
- ComfyUI 입출력 타입
- source fingerprint
- ModelPatcher/Sampler/ControlNet/IPAdapter/LoRA 관련 신호
- frontend/server route/monkey patch 의심 신호
- 추적 난이도와 우선순위

### `CUSTOM_NODE_INVENTORY.md`

사람이 읽는 전체 요약입니다.

### `TRACE_COMPATIBILITY_MATRIX.md`

각 패키지를 다음으로 판정합니다.

- Generic Trace 가능
- Runtime Hook 필요
- Dedicated Adapter 필요
- 권장 Hook 지점

### `ADAPTER_PRIORITY.md`

Codex가 실제로 어떤 패키지부터 분석·구현할지 Priority A/B/C로 정리합니다.

### `LOCAL_ADAPTER_PLAN.md`

Priority A package를 표로 미리 채운 작업 골격입니다. Codex가 실제 workflow 사용 여부, missing signal, Adapter task, test workflow를 채웁니다.

---

## 분류 기준

### Data Transform

```text
IMAGE / MASK / LATENT → 변환 → IMAGE / MASK / LATENT
```

보통 Generic input/output Probe로 충분합니다.

### Conditioning

```text
CONDITIONING / CONTROL_NET → 조건 변경
```

Conditioning snapshot, `CALC_COND_BATCH`, Control residual 확인이 필요합니다.

### Model Patching

```text
MODEL → LoRA / IPAdapter / PuLID / 기타 Patch → MODEL
```

그래프 실행 시점과 Sampling Runtime을 분리해야 합니다.

### Sampler/Pipeline Replacement

```text
기본 KSampler/CFGGuider 경로를 직접 호출하거나 우회
```

샘플러 이름·스케줄러 목록을 UI에 노출하는 구성 참조는 이 분류에 포함하지 않습니다. AST에서 실제 sampler 호출이 확인될 때만 승격합니다.

전용 Adapter 우선순위가 가장 높습니다.

### Frontend/Workflow Utility

```text
Switch / Reroute / UI / Queue / Workflow 보조
```

노드 실행·Cache·Branch 표시가 핵심입니다.

---

## 판정값

### Dedicated Adapter

- `not_needed`: Generic Trace로 충분할 가능성이 높음
- `recommended`: 표준 Runtime Hook은 잡히지만 의미 해석 Adapter가 유용함
- `required`: 자체 Sampler/Pipeline 또는 침습적 Patch 가능성이 있어 전용 대응 필요
- `manual_review`: Dynamic mapping 또는 parse 오류로 정적 판정 불완전

### Priority

- **A**: Conditioning/MODEL/Sampling을 직접 변경. 먼저 검증
- **B**: Detector/Preprocessor/Image transform. Generic Trace 후 필요 시 확장
- **C**: Workflow/UI/Utility. 실행 흐름 중심

Priority는 위험도나 인기도가 아니라 **생성 결과에 개입하는 깊이** 기준입니다.

---

## 이전 결과와 비교

업데이트 후 무엇이 바뀌었는지 확인할 수 있습니다.

```bash
python scripts/scan_custom_nodes.py \
  --comfy-root "D:\\AI\\ComfyUI" \
  --output-dir docs \
  --previous-json "docs\\CUSTOM_NODE_INVENTORY.previous.json"
```

비교 기준은 package별 source fingerprint입니다.

- added
- removed
- changed
- unchanged

---

## 해석 한계

정적 신호는 “이 코드가 실제 workflow에서 실행됐다”는 증명이 아닙니다.

다음은 실제 Runtime 검증이 필요합니다.

- 동적으로 생성되는 `NODE_CLASS_MAPPINGS`
- compiled extension / custom CUDA
- import 시 monkey patch
- 표준 `CFGGuider`를 우회하는 sampler
- 외부 라이브러리 내부 동작
- 실제 transformer patch key

따라서 순서는 다음입니다.

```text
Static Inventory
  ↓
Priority A source review
  ↓
실제 workflow Runtime Trace
  ↓
Trace On/Off 결과 불변성
  ↓
전용 Adapter 확정
```

---

## Symlink와 Disabled 폴더

기본값은 symlink package를 따라가지 않고 `Skipped Entries`에 기록합니다. 개발용 symlink까지 조사하려면 다음을 명시합니다.

```bash
python scripts/scan_custom_nodes.py \
  --custom-nodes "<path>" \
  --output-dir docs \
  --follow-symlinks
```

폴더명에 `disabled`가 포함된 package는 `likely_disabled=true`로 기록하지만 Inventory에는 남깁니다. 실제 ComfyUI Manager 활성 상태는 로컬 설정과 Runtime에서 다시 확인합니다.
