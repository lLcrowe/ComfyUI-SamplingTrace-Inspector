# Local Validation — Actual ComfyUI Integration

## Status

`FEATURE-PATH PASS / PACKAGED INTERNAL ACCEPTANCE PASS` — 기존 실제 설치본에서 Plugin import, Bottom panel, 최소 KSampler, Trace On/Off 무간섭, Depth·OpenPose ControlNet, P1 Adapter 3종, A/B Compare·Report·동시 prompt 연결, 성능 예산을 확인했습니다. 비공개 저장소 fresh clone도 격리 ComfyUI에서 설치·실제 생성·UI/API·재시작 수용 테스트를 통과했습니다. 외부 clean install과 첫 사용자 검증은 별도입니다.

## Environment

- Date: 2026-08-15 (Asia/Seoul)
- ComfyUI path: `<local ComfyUI root>`
- ComfyUI commit/release: `7fe8a6138504f90ff7be82f3babf416da32876b1` / `0.33.0` / `master`
- Frontend version: `1.48.7`
- Python: `3.12.10` (embedded)
- PyTorch: `2.13.0+cu130`
- CUDA device: `cuda:0`
- GPU: NVIDIA GeForce RTX 5070 Ti, 17,094,475,776 bytes VRAM
- Relevant custom nodes: `docs/CUSTOM_NODE_INVENTORY.json` 참조

## Installed Custom Node Inventory

- Inventory generated at: `2026-08-12T16:18:57+00:00` (`2026-08-13 01:18:57 KST`)
- Scanner version: `0.3.0`
- Inventory JSON: `docs/CUSTOM_NODE_INVENTORY.json`
- Package count / static node mappings: `36 / 657`
- Priority A static candidates: `11`
- Workflow usage scan: `36 packages / 21 observed / 52,723 evidence records / 0 errors`
- Usage state: `ACTIVE 4 / UNKNOWN 32`; 미관찰은 미사용이 아니라 `UNKNOWN`
- Trace priority: `P1_ACTIVE 3 / P2_NEAR_TERM 6 / P3_GENERIC 12 / P5_UNKNOWN 15`
- P1_ACTIVE: `comfyui-easy-use`, `comfyui-easyillustrious`, `comfyui-ipadapter-plus`
- Adapter assessment: `required 4 / recommended 7 / manual_review 2 / not_needed 23`
- Dynamic mapping / scan errors / parse errors: `7 / 0 / 0`
- `LOCAL_ADAPTER_PLAN.md`: generated; actual-use column remains `TODO`

## Static checks

```text
python scripts/static_check.py: PASS (Python + JavaScript)
pytest -q: 46 passed
python scripts/comfy_integration_smoke.py: PASS — embedded Python import 확인
live server: PASS — nodes 8/8, route/web extension, Bottom panel, KSampler, Trace identity, ControlNet, P1 Adapter 3종, A/B reports, concurrent prompt linkage
```

## Minimum workflow

- Workflow: Checkpoint → Prompt → Latent → Trace Model → KSampler → VAE Decode → Save Image
- Run ID: `328359db-171d-4f95-b0ea-a1aa9c6d69a6`
- Result: 8 steps / 8 previews / sampling begin-step-end / x-x0-Sigma / errors 0
- Report path: `user/trace_inspector/runs/328359db-171d-4f95-b0ea-a1aa9c6d69a6/report.md` and `report.html`

## Trace On/Off identity

- Seed: `2608140226`, Euler/normal, 8 steps, CFG 7.0
- Trace Off PNG / decoded RGBA SHA-256: `26117196...923f` / `273f9b62...d973`
- Trace On PNG / decoded RGBA SHA-256: `26117196...923f` / `273f9b62...d973`
- Equal: Yes — separate metadata-free cold/cold restarts; decoded pixel difference 0

## ControlNet

| Type | Strength | Range | Run ID | Result |
|---|---:|---|---|---|
| Depth | 0.8 | 0.0–1.0 | `8fdc05a2-102a-4b7e-b404-fd70c69965e7` | PASS — active/numeric residual 8/8 |
| OpenPose | 0.8 | 0.0–1.0 | `f0796c79-b3b7-4b71-9623-d169f39ff402` | PASS — active/numeric residual 8/8 |

OpenPose strength 0.0/0.8 cold/cold A/B runs are `716f1aa5-3a89-40e5-b200-083808d4cf1e` and `3a628645-3a60-41eb-a4a8-ea73ef99cd86`. The compare API aligns all 8 decoded x0 previews and exposes x0 summaries and observed ControlNet residuals. These are observational signals, not causal percentages.

## LoRA / IPAdapter

- `comfyui_ipadapter_plus`: `IPAdapterAdvanced(weight 0.65)`의 최종 MODEL 뒤에 Trace를 배치했습니다. Run `4dc4a7b7-eef6-4ac1-9f40-4cd138d455fd`는 8 steps/previews, errors 0, snapshot `patches_replace.attn2` callable 70개, runtime `attn2` 8/8입니다.
- IPAdapter bypass/on: run `f00d97e5-8e11-48c1-b554-9447377b5bf0` / `4dc4a7b7-eef6-4ac1-9f40-4cd138d455fd`, step 1 x0 mean absolute delta `0.058573`; decoded final output 393,216/393,216 pixels changed, RGB mean absolute difference `52.2594`.
- IPAdapter Trace identity: cold Off/On decoded RGBA SHA-256 both `7c6dfc2a...2167`, pixel difference 0.
- `comfyui-easy-use`: `easy fullLoader → Trace Model → easy pipeIn → easy fullkSampler`, run `726ea1c3-e58e-457a-910d-6fe20f1c13f5`, actual `sample_euler`, 8 steps/previews, errors 0. Cold Off/On decoded RGBA SHA-256 both `5abff762...6569`, pixel difference 0.
- `Comfyui-EasyIllustrious`: run `427727b0-7e9d-4fa1-84dd-f11928fade58`, 8 steps/previews, errors 0. Requested `euler/normal` was actually executed as `sample_euler_ancestral`; Trace preserved and exposed the package's runtime override. Cold Off/On decoded RGBA SHA-256 both `ff36a991...b793`, pixel difference 0.
- Adapter and Control differences are observational evidence, not causal percentages.

## Compare / Report

- OpenPose strength 0/0.8 and IPAdapter bypass/on reports align 8 step pairs and include workflow hashes, settings, requested/actual sampler, model patch summaries, x0/Control differences, and both Preview links.
- EasyUse/EasyIllustrious report records requested `euler/normal` and actual `sample_euler` / `sample_euler_ancestral` separately.
- `Build A/B reports` writes `compare_{rightRunId}.md/.html` under the left run. Live Markdown and HTML routes returned HTTP 200.
- Concurrent prompt test: two independent client IDs submitted prompt IDs `...0001` and `...0002` together. Runs `e930f034-12ce-4f1f-b317-5f8a96762176` and `5127e7a0-bc1f-4a14-9e42-27d9158cc1ae` retained the exact prompt IDs, labels, seeds, histories, and outputs without cross-linking.
- Prompt linkage is captured from ComfyUI's backend execution context and persisted as `promptId`; it does not rely on a particular frontend tab receiving events.

## Performance

| Mode | Time | VRAM peak | Disk | Output hash |
|---|---:|---:|---:|---|
| Off | mean `1697.7ms`, range `1344–2275` | max `12991.2MiB` | 0 | per-seed decoded RGBA reference |
| Basic | mean `1526.3ms`; paired median `+57ms / +4.24%` | max `12995.2MiB` | mean `101,302B` | equal |
| Advanced (`persist_tensor_stats=false`) | mean `1550.0ms`; paired median `+153ms / +10.38%` | max `12993.5MiB` | mean `106,929B` | equal |
| Advanced (`persist_tensor_stats=true`) | mean `1654.0ms`; paired median `+323ms / +21.91%` | max `12991.2MiB` | mean `117,406B` | equal |

Conditions: WAI Illustrious v17, 512×512, Euler/normal, 8 steps, CFG 5.0, warmup 1, paired seeds `2608151001–3`, N=3. The first same-seed attempt contained a 24ms Off cache hit and was discarded. NVML reports whole-device used memory, so these values are an observed upper bound rather than isolated Trace allocation. Re-run with `python scripts/benchmark_live.py --repeats 3`.

## Fixed

- File: `trace_inspector/custom_node_inventory.py`
- Cause: whole-file 문자열과 프런트엔드·보조 테스트 코드가 Runtime 신호로 합쳐져 Priority A와 필수 Adapter를 과대분류함
- Change: AST 선언·심볼·실제 호출 기반 분류, 보조 경로 기본 제외, sampler 설정/실행 분리, UTF-8 BOM 처리, parse-error summary 추가
- Test: 당시 Inventory 회귀 `17 passed`; 당시 전체 package tests `33 passed`; 실제 설치본 `36 packages`, Priority A `24 → 11`, required `15 → 4`, parse errors `2 → 0`

## Packaged internal acceptance — 2026-08-15 PASS

- 별도 ComfyUI root·user/output/input/temp·port `8891`, Trace Inspector만 allowlist로 로드
- health·노드 8/8·웹 자산, checksum 75/75, static check, pytest 48 passed
- health route와 새 실제 Run의 `pluginVersion` 모두 `0.4.0b1`
- Off·Basic·Advanced standard·Advanced influence decoded RGBA 동일
- browser-linked Run: 8 steps, frontend events 18, Trace step → original progress `8/8`, status `success`
- UI Runs/Preview/Workflow/A/B·step interaction·수직 scroll, Notes, compare/report, 400/404, Run delete PASS
- 서버 재시작 후 Run·steps·frontend events·Markdown/HTML·A/B report·UI 복구 PASS
- `benchmark_live.py`의 고정 output 경로와 health/Run의 옛 `0.2.0` 버전 결함을 수정하고 회귀 테스트를 추가

## Remaining

### Structural

- Priority A 정적 판정은 Runtime 실행 증명이 아니므로 실제 workflow 사용 여부를 확인해야 함
- Workflow 사용 증거는 확인했으나 저장 workflow만 있는 패키지는 `ACTIVE/HISTORICAL` 사용자 결정이 필요함
- Dynamic mapping 7개 중 `comfyui-impact-subpack`, `tts_audio_suite`는 수동 검토 상태

### Local

- Clean ComfyUI installation outside this machine
- External first-user Quick Start completion

### Cosmetic

- 없음

## Final status

- Readable: Yes
- Structured: Yes
- Established: Static inventory + workflow usage + live Plugin/panel + KSampler identity + Depth/OpenPose ControlNet + P1 Adapter 3종 + A/B reports + concurrent prompt linkage
- Local integration ready: Yes — current machine and isolated packaged build
- Public beta ready: No — clean install and an external first-user pass remain
