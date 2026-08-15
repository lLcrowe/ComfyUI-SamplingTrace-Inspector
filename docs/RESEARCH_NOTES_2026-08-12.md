# Research Notes — 2026-08-12

## 조사 기준

- 기준일: **2026-08-12 (KST)**
- 우선순위: ComfyUI 공식 문서와 `Comfy-Org/ComfyUI` 공식 GitHub 저장소
- 코드 검색이 가리킨 snapshot commit: `26d7f8556822d9d08c2d3e1878636ac3b4969af9`
- 실제 사용자 설치본은 Codex가 별도로 commit을 고정해야 합니다.

---

## 1. ComfyUI Server API

공식 문서:
- https://docs.comfy.org/development/comfyui-server/comms_overview
- https://docs.comfy.org/development/comfyui-server/comms_routes
- https://docs.comfy.org/development/comfyui-server/comms_messages

확인:
- 기본 로컬 서버 주소는 `127.0.0.1:8188`
- REST와 WebSocket 사용 가능
- 주요 route:
  - `/ws`
  - `/prompt`
  - `/history`
  - `/object_info`
  - `/view`
  - `/system_stats`
- 기본 message:
  - execution_start
  - execution_error
  - execution_interrupted
  - execution_cached
  - execution_success
  - executing
  - executed
  - progress
  - status
- `PromptServer.instance.send_sync(custom_type, payload)`로 custom message 전송 가능

설계 반영:
- Node Timeline은 공식 message 사용
- Step metric은 custom message 사용

---

## 2. Preview callback

공식 소스:
- https://github.com/Comfy-Org/ComfyUI/blob/master/latent_preview.py
- 조사 시 file SHA: `6bf2c18698468eb77fbb8b2cd865cb47a36b83b8`

확인:

```python
callback(step, x0, x, total_steps)
```

`prepare_callback`은:
- `get_previewer(model.load_device, model.model.latent_format)`
- x0를 Preview decoder에 전달
- ProgressBar로 preview bytes 전송

Previewer:
- TAESDPreviewerImpl
- Latent2RGBPreviewer

조사 시 `Auto`는 Latent2RGB로 전환됩니다.

설계 반영:
- 원본 callback을 감싸서 x0/x를 기록
- 원본 callback은 그대로 호출
- 저장 Preview도 같은 previewer 계층 사용

---

## 3. ModelPatcher Wrapper API

공식 소스:
- https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/patcher_extension.py
- 조사 시 file SHA: `189ee84caa353a0ba869d287d931a78e70faca06`
- https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/model_patcher.py

확인한 wrapper type:

```text
OUTER_SAMPLE
PREPARE_SAMPLING
SAMPLER_SAMPLE
PREDICT_NOISE
CALC_COND_BATCH
APPLY_MODEL
DIFFUSION_MODEL
```

`WrapperExecutor`는 wrapper가 받은 executor를 호출하면 다음 wrapper 또는 원본 함수로 진행합니다.

`ModelPatcher` 제공 메서드:
- `add_wrapper_with_key`
- `set_model_sampler_pre_cfg_function`
- clone 시 wrapper/callback 구조 보존

설계 반영:
- Trace Model에서 cloned ModelPatcher에 keyed wrapper 등록
- 다른 custom node wrapper를 덮어쓰지 않음

---

## 4. OUTER_SAMPLE 계약

공식 소스:
- https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/samplers.py

확인한 호출 형태:

```text
executor.execute(
  noise,
  latent_image,
  sampler,
  sigmas,
  denoise_mask,
  callback,
  disable_pbar,
  seed,
  latent_shapes=...
)
```

설계 반영:
- 위치 인자와 이름 인자를 모두 처리하는 `_argument` compatibility helper 사용
- callback 위치만 교체

---

## 5. CFG hook

공식 `samplers.py`에서 pre-CFG 함수에 전달되는 주요 값:

```text
conds
conds_out
cond_scale
timestep
input
sigma
model
model_options
```

pre-CFG 함수는 수정 또는 원본 `conds_out`을 반환합니다.

설계 반영:
- `conds_out[0] - conds_out[1]` bounded sample summary
- 원본 `conds_out` 반환

---

## 6. ControlNet runtime

공식 소스:
- https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/samplers.py
- https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/controlnet.py

확인:

```text
control.get_control(input_x, timestep, conditioning, ...)
  ↓
model.apply_model(..., control=control_features)
```

ControlNet 내부는 일반적으로:

```text
current noisy latent
control hint
current timestep
text context
  ↓
control model
  ↓
residual feature structures
```

설계 반영:
- APPLY_MODEL wrapper에서 실제 전달된 control 구조를 계측
- Deep mode에서 residual Tensor statistics

---

## 7. Frontend extension

공식 문서/소스:
- https://docs.comfy.org/custom-nodes/overview
- https://docs.comfy.org/custom-nodes/js/javascript_overview
- https://docs.comfy.org/custom-nodes/js/javascript_hooks
- https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/types/comfy.ts
- https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/types/extensionTypes.ts
- https://github.com/Comfy-Org/ComfyUI_frontend/blob/main/src/stores/workspace/bottomPanelStore.ts
- 코드 검색이 가리킨 frontend snapshot commit: `202634826285348aacf31bdfd8ab42dce5ea09ba`

확인한 현재 계약:

```text
ComfyExtension.bottomPanelTabs[]
  id
  title
  type = "custom"
  render(container) -> void
  destroy?() -> void
  targetPanel? = "terminal" | "shortcuts"
```

`targetPanel`을 생략하면 현재 store 구현은 `terminal`을 기본값으로 사용합니다. 이 초안은 의도를 명확히 하기 위해 `targetPanel: "terminal"`을 지정합니다. `render`는 반환값을 사용하지 않고, 정리는 tab의 `destroy` callback에서 처리합니다.

설계 반영:
- `WEB_DIRECTORY = "./web"`
- `app.registerExtension`
- `api.addEventListener`
- current custom bottom panel tab contract

실제 사용자 설치본이 이 snapshot보다 이전이면 frontend compatibility shim이 필요할 수 있으므로 Codex 통합 검증 대상으로 남깁니다.

---

## 8. 결론

현재 공식 구조에서는 다음이 가능합니다.

1. 모든 노드 실행 Timeline
2. 기존 KSampler를 교체하지 않은 Step callback 추적
3. x/x0/Sigma Preview 저장
4. pre-CFG delta 계측
5. Control residual 계측
6. MODEL patch semantic summary

자료만으로 판정하기 어려워 실제 테스트로 남긴 항목:
- custom sampler 호환 범위
- IPAdapter 구현별 patch key
- 모델 계열별 Preview 품질
- Deep mode 비용
- multi-browser/multi-user event mapping
