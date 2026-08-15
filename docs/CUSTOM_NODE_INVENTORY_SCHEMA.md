# Custom Node Inventory Schema

## 정본

`CUSTOM_NODE_INVENTORY.json`

```json
{
  "schema_version": "1.0",
  "scanner_version": "0.3.0",
  "generated_at": "ISO-8601",
  "scan_mode": "static_only_no_import_no_execution",
  "custom_nodes_path": "...",
  "safety": {},
  "summary": {
    "scan_error_count": 0,
    "parse_error_count": 0,
    "packages_with_parse_errors": 0
  },
  "diff": {},
  "packages": [],
  "scan_errors": []
}
```

---

## Package 주요 필드

### Identity

```json
{
  "package_id": "normalised-id",
  "folder_name": "ComfyUI-Example",
  "relative_path": "ComfyUI-Example",
  "declared_name": "...",
  "version": "...",
  "repository": "...",
  "is_symlink": false,
  "likely_disabled": false,
  "git": {
    "remote_origin": "...",
    "commit": "...",
    "branch": "..."
  }
}
```

### Static Node Definition

```json
{
  "node_count_static": 12,
  "node_mappings": {
    "Display Node Name": "PythonClassName"
  },
  "dynamic_node_mapping": false,
  "web_directories": ["./web"]
}
```

`node_count_static`는 AST로 확인한 수치입니다. Runtime 등록 수와 다를 수 있습니다.

### Type Surface

```json
{
  "comfy_types": [
    "MODEL",
    "CONDITIONING",
    "IMAGE"
  ]
}
```

Python의 `INPUT_TYPES`/`RETURN_TYPES` 선언에서 ComfyUI 타입을 수집합니다. 임의 문자열, 주석, 프런트엔드 라벨은 타입 증거로 사용하지 않습니다.

### Feature Evidence

```json
{
  "features": {
    "uses_sampler_api": {
      "detected": true,
      "hit_count": 4,
      "files": ["nodes.py"]
    }
  }
}
```

Feature는 증거 신호입니다. Runtime 실행 여부를 확정하지 않습니다.

지원 Feature:

- `uses_model_patcher`
- `uses_model_options`
- `uses_transformer_options`
- `uses_wrappers`
- `uses_callbacks`
- `uses_sampler_api`
- `uses_sampler_execution`
- `uses_apply_model`
- `uses_controlnet`
- `uses_ipadapter`
- `uses_lora`
- `uses_detailer`
- `uses_regional`
- `uses_tiled_diffusion`
- `uses_qwen_image`
- `uses_server_routes`
- `uses_ws_messages`
- `frontend_extension`
- `network_or_download_code`
- `subprocess_code`
- `monkey_patch_suspected`

분류 경계:

- `uses_sampler_api`: 샘플러 모듈·설정 표면을 참조함
- `uses_sampler_execution`: 샘플러 호출 지점이 AST에서 확인됨
- Python 런타임 분류는 AST 심볼·호출 증거를 사용하며, 네트워크·subprocess 위험 플래그만 원문 패턴을 함께 사용함
- JavaScript/TypeScript/Vue는 WebSocket과 프런트엔드 확장 신호만 분류에 사용함

### Trace Assessment

```json
{
  "assessment": {
    "categories": ["Model Patching"],
    "primary_category": "Model Patching",
    "generic_trace": true,
    "runtime_hook_required": true,
    "dedicated_adapter": "recommended",
    "trace_difficulty": "medium",
    "priority": "A",
    "current_coverage": "...",
    "recommended_hook_points": [
      "ModelPatcher snapshot",
      "APPLY_MODEL",
      "DIFFUSION_MODEL"
    ],
    "reasons": []
  }
}
```

---

## Source Fingerprint

`source_fingerprint_sha256`는 스캔한 source/manifest 텍스트의 상대 경로와 내용을 순서대로 hash한 값입니다.

용도:

- Custom Node update 감지
- 이전 Inventory와 비교
- 검증한 commit/source와 실제 설치본 불일치 확인

제한:

- Skip 대상 디렉터리는 포함하지 않음
- 최대 파일 크기를 넘긴 파일은 포함하지 않음
- Binary/compiled extension은 포함하지 않음

---

## Skipped Entries

기본 설정에서 symlink는 따라가지 않습니다. Inventory 최상위 `skipped_entries`에 path와 이유를 기록합니다. `--follow-symlinks`를 명시하면 조사합니다.
