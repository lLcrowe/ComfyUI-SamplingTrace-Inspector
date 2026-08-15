# Build Validation — 2026-08-15

## 판정

현재 패키지는 **독립 정적 검사와 실제 로컬 ComfyUI 통합 게이트를 통과한 공개 베타 후보**입니다. 표준 KSampler 무간섭, ControlNet, P1 Adapter 3종, A/B reports, 동시 prompt 연결, N=3 성능 기준선을 실제 서버에서 확인했습니다. Clean install과 외부 첫 사용자 Quick Start는 아직 수행하지 않았습니다.

---

## 실행 환경

```text
Date: 2026-08-15
Python: 3.12.10 (ComfyUI embedded Python; ComfyUI modules were not imported)
Node.js: v24.11.1
pytest: 8.4.1
```

이 환경은 패키지 자체 검증용이며, 사용자의 실제 ComfyUI Python/PyTorch/CUDA 환경을 대체하지 않습니다.

---

## 실행 명령과 결과

```bash
python scripts/static_check.py
pytest -q
python -m compileall -q .
node --check web/trace_inspector.js
python scripts/scan_custom_nodes.py --custom-nodes <synthetic fixture> --output-dir <temp reports>
```

결과:

```text
Static check: PASS
Python compile: PASS
JavaScript syntax: PASS
Pytest: 46 passed
Custom Node Inventory CLI smoke: PASS
Workflow Usage Inventory tests/CLI: PASS
ComfyUI embedded Python integration smoke: PASS (separate process; live server unchanged)
Generated inventory/report files: 5/5
Actual installed package scan: 36 packages / 657 static node mappings
Priority A: 11 (previous scanner: 24)
Required adapters: 4 (previous scanner: 15)
Scan errors / parse errors: 0 / 0
Package checksum entries: 75/75 PASS after current release-candidate update
Private beta archive: 76 files including `SHA256SUMS.txt`; local inventory, Run data, image/model binaries, and private path/token patterns excluded
Workflow usage scan: 36 packages / 21 observed / 52,723 evidence records / 0 errors
Trace priority: P1 3 / P2 6 / P3 12 / P5 15
```

`comfy_integration_smoke.py`는 portable embedded Python의 `server`, `folder_paths`, `comfy.patcher_extension`, `latent_preview`와 package import를 통과했습니다. 이어 실제 8888 서버에서 Plugin route/UI, 생성, report, 동시 prompt, benchmark를 검증했습니다.

---

## 자동 검증된 범위

### Installed Custom Node Inventory

- 조사 대상 package를 import/실행하지 않음
- import 시 파일을 생성하는 fixture가 실제로 실행되지 않음
- `NODE_CLASS_MAPPINGS` / display mapping 정적 추출
- IMAGE/MASK/LATENT/CONDITIONING/MODEL/CONTROL_NET 타입 탐지
- Data Transform / Conditioning / Model Patching / Sampler-Pipeline / Frontend Utility 분류
- ModelPatcher, wrapper, callback, sampler, ControlNet, IPAdapter, LoRA 신호 탐지
- Detailer, Regional, Tiled Diffusion, Qwen 신호 탐지
- server route / WebSocket / frontend extension 신호 탐지
- network/download, subprocess, module-object mutation 검토 플래그
- Dynamic mapping / Python parse error 기록
- UTF-8 BOM Python source 파싱
- 보조 테스트·예제·데모 경로 기본 제외
- sampler 구성 참조와 실제 sampler 실행 분리
- 프런트엔드 라벨·주석을 Python Runtime 분류에서 제외
- Git remote/branch/commit 정적 읽기
- `pyproject.toml` name/version/dependency 읽기
- source fingerprint 기반 이전 inventory diff
- Priority A/B/C와 adapter 필요도 판정
- Inventory JSON/Markdown, compatibility matrix, adapter priority, local adapter plan 생성
- 일반 ComfyUI root / Windows Portable root / direct custom_nodes 경로 해석
- Trace Inspector 자체 package 기본 제외

### Workflow Usage Inventory

- custom node import/실행 없이 saved workflow JSON의 API/UI graph node type 추출
- PNG `tEXt`/`zTXt`/`iTXt`의 `prompt`, `workflow`, `extra_pnginfo`만 읽고 image pixel(IDAT)은 건너뜀
- localhost history API를 read-only로 조회
- subgraph/embedded workflow 재귀 탐색
- prompt 원문을 결과에 저장하지 않음
- package/node/evidence/source/workflow/시각/저장·출력·간접 여부 기록
- `ACTIVE/HISTORICAL` 후보와 `P0~P5` 추적 우선순위 분리
- 미관찰 package를 `UNKNOWN`으로 유지

### Package loading

- ComfyUI `PromptServer`, `folder_paths` stub 환경에서 custom node package import
- node mapping 노출
- route registration
- `WEB_DIRECTORY` 노출

### Runtime wrapper

- `OUTER_SAMPLE` wrapper 등록
- 원본 sampling callback 보존
- Trace callback 실행 후 원본 callback 호출
- sampling begin/step/end 순서

### Trace session

- Run 생성
- Sampling segment 생성
- x/x0/Sigma 저장
- CFG delta 집계
- Control residual 집계
- Step Preview 이미지 저장
- Markdown/HTML report 생성
- finalize 및 persistence

### Tensor summary

- shape/dtype/device/statistics
- aligned bounded difference
- nested Tensor 탐색
- `max_tensors` 도달 시 실제 순회 중단

### Prompt/Adapter

- KSampler 설정 추출
- ControlNet/LoRA/IPAdapter 분류
- workflow hash 안정성
- graph 등록과 runtime influence 설명 분리

### Diagnostics

- 후기 Preview 불안정 탐지
- ControlNet 구성은 있으나 runtime control 미관찰 탐지
- 인과 단정 대신 A/B 실험 후보 생성

### Store/Report

- Run round-trip
- Step JSONL
- report generation
- A/B 데이터 구조
- workflow/runtime/model patch/step evidence 비교
- A/B Markdown/HTML 생성·HTTP 제공
- backend promptId 기반 concurrent prompt 연결

### Live performance

- WAI Illustrious v17 / 512² / Euler normal / 8 steps / CFG 5.0
- warmup 1 + paired seed 3개
- Off / Basic / Advanced standard / Advanced influence decoded output 동일
- history wall time, NVML whole-device peak, run directory bytes 측정
- first cache-hit attempt 폐기 후 seed-per-pair 방식으로 재측정

---

## 공개 베타 전에 남은 검증

1. 이 작업 머신 밖의 clean ComfyUI 설치·제거·재설치
2. 외부 첫 사용자 1명의 README Quick Start 완주
3. 실제 GitHub repository URL과 Issues/지원 경로 확정
4. P2 package와 Flux/Qwen/Video/multi-segment는 지원 범위 확장 시 별도 검증

---

## 현재 완료 등급

```text
Code Draft: Complete
Static Validation: Passed
Installed Node Scanner: Passed on synthetic fixtures
Actual Installed Node Static Scan: Passed (36 packages, no imports/execution)
Simulated Runtime Integration: Passed
Actual Custom Node Inventory: Generated; workflow usage review complete
Actual Workflow Usage Inventory: Generated; user-only state decisions pending
Actual ComfyUI Integration: Passed (022-1~10)
Local Production Ready: Yes
Public Beta Ready: No — clean install / external first user / real repository-support URLs pending
```
