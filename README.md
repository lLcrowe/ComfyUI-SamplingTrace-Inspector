# ComfyUI Sampling Trace Inspector

**English** | [한국어](README.ko.md)

Inspect how a ComfyUI image forms over time: execution flow, sampling steps, latent state, predicted x0, sigma, CFG behavior, ControlNet residuals, model patches, and prompt-word attention in one panel.

> Current status: **0.4.0b1 private beta candidate**. The package has passed internal acceptance in a separate ComfyUI, user, input, output, and temporary environment cloned from the private repository. A clean installation outside the development machine and a first external user's Quick Start remain unverified. See `docs/LOCAL_VALIDATION.md` and `docs/BUILD_VALIDATION.md`.

---

## 1. Why this exists

A typical debugging loop looks like this:

```text
Inspect the final image
  → Notice a problem
  → Guess whether CFG, ControlNet, LoRA, or IPAdapter caused it
  → Change a setting and generate again
```

Sampling Trace Inspector changes the loop:

```text
Inspect step previews
  → Find the step where the result first changes or breaks
  → Check Sigma, CFG delta, Control residuals, and prompt attention
  → Narrow down the settings worth changing
  → Compare two runs with the same seed
```

This is a sampling debugger for locating turning points in the generation process. It does not claim that one observed signal caused a specific percentage of the final image.

---

## 2. How it fits into a workflow

Sampling Trace Inspector does not replace KSampler. Insert `Sampling Trace Model` after the final MODEL patch and before the first sampler.

```text
Checkpoint
   ↓
LoRA
   ↓
IPAdapter / other MODEL patches
   ↓
Sampling Trace Model
   ↓
Existing KSampler or standard ComfyUI sampler path
```

Keep ControlNet on the existing CONDITIONING path:

```text
Positive / Negative Conditioning
   ↓
ControlNet Apply
   ↓
KSampler
```

`Sampling Trace Model` registers observers on a cloned `ModelPatcher`:

```text
OUTER_SAMPLE wrapper
  ├─ sampling begin / end
  └─ step callback around the existing callback

APPLY_MODEL wrapper
  ├─ Control residuals passed to the real model call
  └─ active transformer patch types

Pre-CFG hook
  └─ conditional / unconditional output difference
```

Samplers that follow the standard `CFGGuider → ModelPatcher` path can be traced without replacing the sampler node.

---

## 3. Inspect installed custom nodes first

Use the static inventory before deciding which adapters are required. The scanner reads source and metadata without importing or executing other custom nodes.

```bash
python scripts/scan_custom_nodes.py \
  --comfy-root "<ComfyUI or Windows Portable root>" \
  --output-dir docs
```

Generated local files:

```text
docs/CUSTOM_NODE_INVENTORY.json
docs/CUSTOM_NODE_INVENTORY.md
docs/TRACE_COMPATIBILITY_MATRIX.md
docs/ADAPTER_PRIORITY.md
docs/LOCAL_ADAPTER_PLAN.md
```

These files help determine whether installed ControlNet, IPAdapter, LoRA, Detailer, Regional Prompt, Tiled Diffusion, and Qwen-related nodes use standard hooks or need a dedicated adapter. See `docs/CUSTOM_NODE_SCAN_GUIDE.md`.

---

## 4. Installation

1. Private beta users must authenticate with GitHub and clone the repository into `custom_nodes`. If you receive a ZIP, extract it with the same final folder name.

```bash
git clone https://github.com/lLcrowe/ComfyUI-SamplingTrace-Inspector.git ComfyUI/custom_nodes/ComfyUI-SamplingTrace-Inspector
```

Final location:

```text
ComfyUI/custom_nodes/ComfyUI-SamplingTrace-Inspector/
```

2. Optionally run the static package check with the Python environment used by ComfyUI.

```bash
cd ComfyUI/custom_nodes/ComfyUI-SamplingTrace-Inspector
python scripts/static_check.py
```

3. Restart ComfyUI.

4. Search for these nodes:

```text
Sampling Trace CLIP · Connect Both Prompts
Sampling Trace Model
Sampling Trace Export / Finalize
Sampling Trace Note
Sampling Trace Image
Sampling Trace Latent
Sampling Trace Mask
Sampling Trace Conditioning
Sampling Trace Model Snapshot
```

5. Connect `Sampling Trace Model` after the final MODEL patch and before the first sampler.

6. Open the `Sampling Trace Inspector` bottom panel.

---

## 5. Recommended wiring

```text
[Checkpoint Loader]
  ① CLIP ──→ [Sampling Trace CLIP · Connect Both Prompts]
                   ② CLIP ──┬──→ Positive Text Encode
                            └──→ Negative Text Encode
                   ③ Send CLIP Prompt Trace ─────────────┐
       MODEL                                             │
         ↓                                               │
[LoRA Loader]                                             │
         ↓                                               │
[IPAdapter Advanced]                                      │
         ↓                                               │
[Sampling Trace Model] ←──────────────────────────────────┘
    MODEL ↓       └── TRACE_SESSION ──→ [Export / Finalize] (optional)
[KSampler]
```

Connect the CLIP output from `Sampling Trace CLIP` to both positive and negative Text Encode nodes. Connect its `③ Send CLIP Prompt Trace` output to `③ Receive CLIP Prompt Trace` on `Sampling Trace Model`.

The CLIP proxy forwards the original `tokenize()` result unchanged and records the calling node, prompt text, CLIP-L/G token IDs, input weights, and readable word groups in the same run. The legacy `clip` input on `Sampling Trace Model` remains only for compatibility with older workflows; do not use it for new connections.

### Why the trace node comes after the last MODEL patch

- The snapshot includes LoRA, IPAdapter, and other patches already registered on the final MODEL.
- Runtime patch keys are easier to associate with the actual sampling call.
- Wrappers may survive if the node is placed earlier, but patch interpretation can become incomplete.

---

## 6. Trace modes

| Mode | Captured data | Cost | Recommended use |
|---|---|---:|---|
| **Basic** | Steps, previews, shape/dtype/device, node timeline | Low | Follow the overall generation flow |
| **Advanced** | Basic plus CFG delta and Control structure. With `persist_tensor_stats=true`, also captures x/x0 details, Control residuals, and step-level positive/negative prompt-word attention | Medium to high | Tuning and ControlNet, prompt, or custom-node research |

Start with `Basic`. Use `Advanced` when internal signals are necessary. Set `persist_tensor_stats=false` when the high-cost tensor statistics are not needed. Legacy workflow values using `Deep` are automatically treated as `Advanced`.

---

## 7. Preview settings

### `preview_every`

Controls how often a preview image is stored.

```text
1 = every step
2 = every second step
5 = every fifth step
```

All numeric step records are still captured. The filmstrip shows only stored preview steps.

### `preview_max_side`

Limits the longest side of a stored preview. The default is 768.

### `preview_decoder`

- `clear` (default): uses the model-family TAESD when available, producing a preview closer to the final image dimensions.
- `fast`: uses Latent2RGB. It is faster, but enlargement can reveal the low latent resolution.

If TAESD is unavailable or fails to load, `clear` falls back to `fast`. This setting affects only trace previews and does not modify ComfyUI's existing Live Preview setting.

### `persist_previews`

Disable it to save numeric traces without image files.

### What a preview means

```text
Current step x0
  ↓
Trace preview decoder
  ├─ clear → model-family TAESD → Latent2RGB fallback
  └─ fast  → Latent2RGB
  ↓
Fast approximate preview
```

A trace preview helps identify when composition and structure appear or collapse. It is not the final VAE Decode and should not be used as exact evidence for final texture, color, or fine detail.

---

## 8. Panel guide

### Runs

- Displays the active workflow filename, label, status, and step count.
- Selects the latest stored run.
- Keeps the header fixed while the run list scrolls vertically.

Only the workflow filename is stored in `run.json` and reports; local absolute paths are removed. Unsaved workflows and API runs fall back to the label or run ID.

Drag the divider between the center workspace and `Selected Run / Compare Runs` to resize the right panel. The width is saved in the current browser. Double-click the divider to restore its default width.

If generation succeeds without `Sampling Trace Model` in the executed graph, the panel explains that the required path is `final MODEL → Sampling Trace Model → sampler`.

### Denoise step viewer

- Continuously draggable step slider
- Approximate x0 preview
- Sigma
- Preview change
- x0 mean and standard deviation
- CFG delta
- Control residual summary

Changing the image step also changes the positive and negative prompt-word views. The text section intentionally has no second step selector.

### Node timeline

- Node execution start and end
- Cache use
- Progress
- Execution time
- Errors and interruptions

### Sampler positive and negative conditions

- Traces the graph role connected to the sampler's `positive` and `negative` inputs.
- With `Advanced + persist_tensor_stats=true`, observes the average cross-attention for each CONDITIONING word from the actual sampled Q/K values at each step.
- Combines partial tokens using the original text and CLIP word boundaries.
- Combines repeated occurrences into one readable word entry.
- Shows positive conditions in a light blue panel and negative conditions in a light red panel.
- Shows a connection guide instead of assigning measurements to the wrong words when only one Text Encode path was connected through `Sampling Trace CLIP`.

Prompt token IDs and CONDITIONING inputs remain fixed during a run. Their observed attention changes because the latent state and sigma change at each step. Values are approximate averages over sampled spatial queries, text keys, and cross-attention layers. They are not causal percentages such as “this word produced 30% of the image.”

Raw prompt calls, encoder chunks, token IDs, partial pieces, input weights, special tokens, and padding remain in the stored evidence but are not duplicated in the normal panel.

### Visual A/B

- Compares workflow hashes, node counts, settings, and requested versus actual sampler.
- Aligns step previews, x0, CFG, and Control metrics.
- Compares MODEL patch snapshots.
- Builds Markdown and HTML reports.
- Uses the backend `promptId` to associate concurrent executions with the correct run.

The comparison is observational evidence, not an absolute attribution of image quality.

### Notes

- Observation
- Hypothesis
- Decision
- Issue

Notes belong to the selected run. They can target the whole run or a specific sampler segment and step, and can be edited, focused, or deleted. The Korean UI localizes the labels while the stored schema retains `observation / hypothesis / decision / issue` for compatibility. Updating a note also refreshes `report.md` and `report.html`.

---

## 9. Data storage and privacy

Run data is stored under the ComfyUI user directory by default:

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

`run.json.promptTokenization` can contain supported prompt text and actual token records. Prompt text, model filenames, workflow snapshots, notes, and preview images may be sensitive. Review a run before sharing it.

If `folder_paths.get_user_directory()` is unavailable, storage falls back to `data/runs/` inside the plugin. Run and note data are not source files. The fallback `data/` directory is ignored by Git and is not committed unless someone explicitly bypasses `.gitignore`.

---

## 10. Probe nodes

| Node | What it records | Passthrough |
|---|---|---|
| `Sampling Trace Image` | IMAGE shape, range, mean, and standard deviation | IMAGE unchanged |
| `Sampling Trace Latent` | LATENT keys and `samples` tensor summary | LATENT unchanged |
| `Sampling Trace Mask` | MASK shape, range, and statistics | MASK unchanged |
| `Sampling Trace Conditioning` | CONDITIONING tensors and metadata keys | CONDITIONING unchanged |
| `Sampling Trace Model Snapshot` | MODEL patch count, transformer patch types, wrappers, and callbacks | MODEL unchanged |

Probe nodes do not start sampling trace by themselves. Connect `Sampling Trace Model` before the sampler to create a traced run.

---

## 11. Performance policy

- Never stores complete tensor values.
- Samples at most 65,536 elements for tensor statistics.
- Stores grouped summaries for Control residuals.
- Computes preview change on images reduced to 128×128.
- Isolates observer failures so a trace error does not intentionally fail generation.
- Lets users control disk and decode cost through trace mode and preview interval.

Local WAI Illustrious v17 testing at 512², Euler/normal, 8 steps, CFG 5.0, N=3 found identical decoded output for Off, Basic, and Advanced runs with the same seed. Step-level prompt attention is a higher-cost Advanced option. See `docs/LOCAL_VALIDATION.md` for measured results and limits.

---

## 12. Tests

Package tests:

```bash
pytest -q
python scripts/static_check.py
```

Installed ComfyUI integration smoke test:

```bash
python scripts/comfy_integration_smoke.py
```

Follow `docs/TEST_PLAN.md` for real generation validation.

---

## 13. Support status

### Implemented

- Official WebSocket execution-event collection
- Sampling begin, step, and end observation
- Preview persistence
- x, x0, and Sigma records
- CFG delta summary
- Control residual summary
- LoRA, IPAdapter, ControlNet, and KSampler semantic adapters
- Run storage, reports, and A/B comparison
- Bottom panel
- Actual CLIP-call prompt text, CLIP-L/G token evidence, and sampler positive/negative word attention

### Verified in the current local installation

- Bottom panel, expanded view, independent vertical scrolling, resizable right panel, and Notes
- Standard KSampler Trace Off/On decoded-pixel identity
- SDXL and Illustrious XL previews
- OpenPose and Depth ControlNet residuals and A/B previews
- `comfyui_ipadapter_plus` attention patch observation and A/B
- `comfyui-easy-use` and `Comfyui-EasyIllustrious` custom sampling paths
- Impact Pack FaceDetailer sampling path
- A/B Markdown/HTML reports and backend prompt-to-run association
- Off, Basic, and Advanced performance and disk baselines
- Korean/English node and panel localization

### Still requires compatibility validation

- Flux and Qwen Image model families using tokenizer APIs other than the validated CLIP path
- More workflows containing multiple KSampler segments
- AnimateDiff, CogVideoX, Wan, and other video-model paths
- A clean install outside the development machine
- First external user's Quick Start

---

## 14. Documentation

| Document | Purpose |
|---|---|
| `docs/CUSTOM_NODE_SCAN_GUIDE.md` | Static inspection of installed custom nodes |
| `docs/CUSTOM_NODE_INVENTORY_SCHEMA.md` | Inventory JSON contract |
| `docs/CODEX_CUSTOM_NODE_INVENTORY_PROMPT.md` | Codex prompt for the pre-integration inventory |
| `docs/PRODUCT_SPEC.md` | Product goals and boundaries |
| `docs/ARCHITECTURE.md` | Hooks and technical structure |
| `docs/PHASES.md` | Implementation phases |
| `docs/CODEX_HANDOFF.md` | Integration handoff criteria |
| `docs/CODEX_PROMPT.md` | Ready-to-use Codex integration prompt |
| `docs/TEST_PLAN.md` | Real ComfyUI validation scenarios |
| `docs/BUILD_VALIDATION.md` | Package checks and unverified boundaries |
| `docs/IMPLEMENTATION_STATUS.md` | Phase-by-phase implementation status |
| `docs/ADAPTER_SDK.md` | Custom-node adapter extension guide |
| `docs/KNOWN_LIMITATIONS.md` | Known limits and risks |
| `docs/GLOSSARY_KO.md` | English terms with Korean explanations |
| `docs/RESEARCH_NOTES_2026-08-12.md` | Primary-source research notes |

---

## 15. Private beta feedback

Use [GitHub Issues](https://github.com/lLcrowe/ComfyUI-SamplingTrace-Inspector/issues) for reproducible defects, compatibility problems, and unclear setup steps.

Do not attach model files, private workflow originals, generated images, prompt text, or complete run folders. Share only the minimum reproducible configuration.

---

## License

Released under the [MIT License](LICENSE).
