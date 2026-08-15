# Codex Prompt — Installed Custom Node Inventory First

아래 내용을 실제 ComfyUI 설치본에 접근 가능한 Codex 세션의 첫 작업으로 사용하세요.

---

## 목표

`ComfyUI-SamplingTrace-Inspector`를 실제 workflow에 장착하기 전에, 현재 설치된 `custom_nodes` 전체를 **비실행 정적 조사**하고 Trace 호환성 및 Adapter 우선순위를 확정하세요.

## 절대 금지

첫 조사 단계에서는 다음을 하지 마세요.

- 다른 custom node Python module import
- `__init__.py` / `install.py` 실행
- requirements 설치
- pip/npm 실행
- 외부 다운로드
- ComfyUI core 수정
- 다른 custom node 수정
- workflow/model 파일 수정

## 먼저 실행

SamplingTrace Inspector 폴더에서:

```bash
python scripts/scan_custom_nodes.py \
  --comfy-root "<ACTUAL_COMFYUI_OR_PORTABLE_ROOT>" \
  --output-dir docs
```

Windows Portable이면:

```powershell
.\scripts\scan_custom_nodes.ps1 \
  -ComfyRoot "<ACTUAL_COMFYUI_WINDOWS_PORTABLE_ROOT>" \
  -OutputDir ".\docs"
```

## 생성 파일 확인

- `docs/CUSTOM_NODE_INVENTORY.json`
- `docs/CUSTOM_NODE_INVENTORY.md`
- `docs/TRACE_COMPATIBILITY_MATRIX.md`
- `docs/ADAPTER_PRIORITY.md`
- `docs/LOCAL_ADAPTER_PLAN.md`

## 검토 작업

### 1. 스캔 신뢰성

- Scan error 확인
- Dynamic `NODE_CLASS_MAPPINGS` 확인
- Parse error 확인
- Symlink/Worktree 여부 확인
- Git commit/remote 누락 확인

### 2. Priority A 수동 검토

각 Priority A 패키지에 대해 실제 source에서 다음을 확인하세요.

- 표준 KSampler/CFGGuider 경로 사용 여부
- `ModelPatcher.clone()`과 wrapper 보존 여부
- `model_options` / `transformer_options` 변경 지점
- `add_wrapper`, `add_callback`, `sampler_pre/post_cfg` 사용
- `comfy.sample` / `comfy.samplers` 직접 호출
- `apply_model` 직접 호출
- Control object 생성·연결 방식
- IPAdapter/LoRA/Detailer/Regional/Tiled/Qwen 관련 patch key
- imported/module object attribute mutation 및 monkey patch 여부

정적 스캐너의 판정이 틀리면 JSON을 손으로 고치지 말고 scanner rule 또는 별도 review 문서에 근거를 기록하세요.

### 3. 실제 Adapter 계획 작성

`docs/ADAPTER_PRIORITY.md`와 scanner가 생성한 `docs/LOCAL_ADAPTER_PLAN.md` 골격을 검토한 뒤 실제 workflow 사용 여부와 Runtime 검증 항목을 채우세요.

| Package | Installed commit | Actual workflow usage | Generic coverage | Missing signal | Adapter task | Test workflow |
|---|---|---|---|---|---|---|

### 4. Phase 5 범위 고정

다음 순서로 범위를 닫으세요.

1. 사용자가 실제 사용하는 Priority A 패키지
2. 표준 Runtime Hook을 우회하는 패키지
3. 결과 원인 추적에 직접 필요한 패키지
4. 나머지는 Generic Trace fallback

## 완료 조건

- [ ] Static scanner 실행 완료
- [ ] 5개 inventory/plan 문서 생성
- [ ] 모든 Scan/Parse error 검토
- [ ] Priority A package source review
- [ ] `docs/LOCAL_ADAPTER_PLAN.md` 작성
- [ ] 실제 테스트 workflow 목록 작성
- [ ] 다른 custom node/core/workflow 무수정 확인

이 작업이 끝난 뒤에만 `docs/CODEX_PROMPT.md`의 Plugin 장착과 Runtime 검증 단계로 이동하세요.
