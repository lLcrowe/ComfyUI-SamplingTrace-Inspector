# Local Validation — Template

## Environment

- Date:
- ComfyUI path:
- ComfyUI commit/release:
- Frontend version:
- Python:
- PyTorch:
- CUDA:
- GPU:
- Relevant custom nodes:

## Installed Custom Node Inventory

- Inventory generated at:
- Scanner version:
- Inventory JSON:
- Package count:
- Priority A packages actually used:
- Dynamic mapping / parse errors:
- `LOCAL_ADAPTER_PLAN.md`:

## Static checks

```text
python scripts/static_check.py:
pytest -q:
python scripts/comfy_integration_smoke.py:
```

## Minimum workflow

- Workflow path:
- Run ID:
- Result:
- Report path:

## Trace On/Off identity

- Seed:
- Trace Off hash:
- Trace On hash:
- Equal:

## ControlNet

| Type | Strength | Range | Run ID | Result |
|---|---:|---|---|---|
| Depth | | | | |
| OpenPose | | | | |

## LoRA / IPAdapter

- Implementation:
- Patch keys:
- Adapter changes:

## Performance

| Mode | Time | VRAM peak | Disk | Output hash |
|---|---:|---:|---:|---|
| Off | | | | |
| Basic | | | | |
| Advanced (`persist_tensor_stats=false`) | | | | |
| Advanced (`persist_tensor_stats=true`) | | | | |

## Fixed

- File:
- Cause:
- Change:
- Test:

## Remaining

### Structural

### Local

### Cosmetic

## Final status

- Readable / Structured / Established / Production Ready:
