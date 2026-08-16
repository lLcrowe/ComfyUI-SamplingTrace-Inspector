# Build Validation — 2026-08-15

## 판정

현재 패키지는 **0.4.0b1 비공개 베타 후보**입니다. 독립 정적 검사와 기존 로컬 ComfyUI의 주요 기능 경로에 더해, 비공개 저장소 fresh clone을 별도 ComfyUI root·사용자·출력·포트에서 내부 수용 테스트했습니다. 이 결과는 현재 머신의 비공개 후보 증거이며, 외부 clean install이나 공개 베타 준비 완료를 뜻하지 않습니다.

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
Pytest: 48 passed
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
- Sampling Trace Inspector 자체 package 기본 제외

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

## Packaged-build internal acceptance

비공개 저장소의 패키지를 추적 대상 외부의 새 ComfyUI clone에 설치하고, 별도 user/output/input/temp 디렉터리와 포트 `8891`에서 검사했습니다. 임베디드 Python의 기존 ComfyUI 경로가 섞인 첫 두 부팅은 격리 증거에서 폐기했고, `--base-directory`와 Custom Node allowlist로 Sampling Trace Inspector만 로드된 세 번째 부팅부터 채택했습니다.

- package source: private repository fresh clone; plugin-only Custom Node import
- boot: health route, 9/9 Trace nodes, JavaScript/CSS assets HTTP 200
- package: checksum `75/75`, static check PASS, pytest `48 passed`
- version diagnostics: health route and a newly persisted live Run both report `0.4.0b1`
- sampling: WAI Illustrious v17, 512², Euler/normal, 8 steps, CFG 5.0, seed `2608151001`
- identity: Off·Basic·Advanced standard·Advanced influence decoded RGBA SHA-256 all `05C031D6...F38D1`
- callback/frontend: Trace step persisted before original progress `8/8`; browser-linked Run stored 18 frontend events and completed as `success`
- UI: Runs/Preview/Workflow/Visual A/B rendered; step 1/8 selection and A/B pair interaction PASS; vertical body scroll `662 → 1292`, `overflow-y: scroll`
- storage/API: note create/edit/delete, UI note add, 8-step compare, Markdown/HTML HTTP 200, expected 400/404 responses, isolated Run deletion PASS
- restart: 5 Runs, 8 steps, 18 frontend events, base reports and A/B reports restored; UI reloaded without Sampling Trace Inspector console errors
- regressions found and fixed: `benchmark_live.py` assumed `<ComfyUI>/output`; `--output-root` now covers custom output directories. Health and persisted Runs also used stale `0.2.0`; both now share the `0.4.0b1` package version constant.

The isolated server was stopped after verification. The original ComfyUI process and queue remained unchanged at `0/0`.

---

## Sampling Trace CLIP prompt capture

- proxy invariance: the original `CLIP.tokenize()` return object is passed through by identity; capture failure cannot replace or mutate it
- attribution: executing Text Encode node ID is captured and every upstream node of named `positive` / `negative` inputs is role-linked, including a synthetic `IllustriousKSamplerPresets` graph
- lifecycle: calls before and after Trace Model session binding are both persisted; cloned CLIP proxies retain capture
- real tokenizer: ComfyUI `SDXLTokenizer` returned matching CLIP-G / CLIP-L 77-token lanes through the proxy
- package checks: embedded pytest `67 passed`, Python/JavaScript static check PASS, `node --check` PASS, `git diff --check` PASS
- live server: Trace nodes `9/9`; `ComfyTraceClip` outputs `clip,prompt_trace`; Trace Model optional inputs include `prompt_trace`; served panel asset and existing-run empty-state layout rendered; queue `0/0`
- actual Run: `ac98c768-5edc-42e3-b351-39e89f58c3bc`; Positive/Negative actual calls and CLIP-G/L lanes persisted and rendered
- cold/cold identity: metadata-free PNG and decoded RGBA hashes match; differing pixels 0; callback order preserved 8/8
- pending: user visual acceptance on their own workflow

## Per-step prompt attention

- correctness: sampled observer equals a full QK-softmax reference when every query is selected; positive/negative CFG batches stay separate
- non-interference: the attention override returns the original attention function result by identity in the hook test and never mutates q/k/v
- live Run: `d27a0d2c-5946-4030-84a1-6a8161616a27`, 8/8 steps, each step positive 70 layers + negative 70 layers, 77 tokens per role, each role vector sum `1.0`
- cold/cold identity: seed `2608160222`, Euler/normal, 8 steps, CFG 5.0; Off/On decoded RGBA SHA-256 `285BD1199AF62E9753BD723B0C33A7D4526E4DA5485559973B13A5B7DB39892C`, callback order preserved 8/8
- live UI: 8 step selectors, 8 positive + 8 negative bars, 2 heatmaps / 160 cells; computed positive tint `rgba(... / 0.14)` with blue border and negative tint with red border; Sampling Trace console errors 0
- performance N=3 paired: Advanced standard (`persist_tensor_stats=false`) median `+126ms / +11.732%`; Advanced influence (`true`) median `+318ms / +30.695%`; all Off/Basic/Advanced decoded RGBA hashes matched per seed
- package checks: embedded pytest `72 passed`, Python/JavaScript static check, `node --check`, `git diff --check`, plugin import smoke and node 9/9 PASS

The UI and reports call this an approximate observed attention share, not a causal quality contribution. Basic and Advanced standard do not install the Q/K observer.

---

## 공개 베타 전에 남은 검증

1. 이 작업 머신 밖의 clean ComfyUI 설치·제거·재설치
2. 외부 첫 사용자 1명의 README Quick Start 완주
3. P2 package와 Flux/Qwen/Video/multi-segment는 지원 범위 확장 시 별도 검증

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
Packaged-build Internal Acceptance: Passed
Local Production Ready: No — evidence is still limited to the current machine
Public Beta Ready: No — clean install / external first user pending
```
