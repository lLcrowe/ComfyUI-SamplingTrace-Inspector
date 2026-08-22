# Changelog

## Unreleased

## 0.4.0b3 — One-node batch trace — 2026-08-23

- Added the zero-configuration `Sampling Trace · One Node Setup`, which exposes only final MODEL and Checkpoint CLIP sockets while applying recommended advanced trace settings internally. It records MODEL sampling and actual positive/negative CLIP tokenization in one Run without a separate `prompt_trace` wire. Existing split MODEL/CLIP nodes remain workflow-compatible.
- Kept only `Sampling Trace · One Node Setup` visible in normal node search. The other nine classes are deprecated and hidden without removing their mappings, preserving saved-workflow compatibility and internal typed diagnostics. Run completion owns report finalization and the bottom panel owns Notes, so separate Export and Note nodes are no longer part of the public workflow surface.
- Added a workflow-persisted Basic/Advanced capture popup to the one-node setup. The node now starts in Basic mode, shows the active level on a compact settings button, and enables high-cost tensor statistics only when Advanced is selected.
- Added automatic per-item batch tracing. Multi-image sampler batches now persist separate x/x0 summaries, decoded step previews, and visual-change histories for every batch index while retaining the legacy first-item fields for compatibility. The trace panel exposes a direct `1/N` selector, and older runs show unavailable batch items as disabled until the workflow is run again.

## 0.4.0b2 — Public preview

- Published the source repository for public preview without claiming 1.0 or external clean-install validation.
- Changed new releases from MIT to `GPL-3.0-only`; copies already received under MIT retain those granted rights.
- Added GPL-aligned package metadata, third-party notices, bilingual public installation and sponsorship guidance, and a security policy.

- Split the guide into an English default `README.md` and a complete Korean `README.ko.md`, with bidirectional language links and matching installation, wiring, panel, storage, privacy, support, and limitation sections.
- Kept the denoise step range control mounted while it is being dragged, so the preview image, selected thumbnail, raw step data, and prompt-attention cards now follow every intermediate slider value instead of stopping after the first movement.
- Made CLIP wiring self-explanatory with a “connect both prompts” node title, numbered input/output labels, explicit fan-out tooltips, and a clearly deprecated legacy CLIP input on Sampling Trace Model. Canvas slot display names now follow the active Korean/English ComfyUI locale without changing their internal types, indexes, or workflow links; the third output and target input use a matching `Send → Receive CLIP Prompt Trace` pair rather than naming the Inspector panel or `trace_session`.
- Added per-step positive/negative sampled cross-attention observation for Advanced runs with tensor statistics enabled.
- Added blue positive and red negative all-word cards plus an Advanced step-by-word heatmap to the panel; BPE fragments and repeated occurrences are combined into readable words.
- Relabeled the word analysis around the sampler `positive` and `negative` CONDITIONING sockets, with socket-specific card titles and tooltips.
- Fixed nested sampler role traversal leaking positive and negative prompt labels into each other; uncaptured socket tokens now show a connection notice instead of attaching attention values to the wrong words.
- Unified prompt-attention selection with the denoise preview step and removed the redundant text-side step picker.
- Removed raw prompt-source and CLIP-token diagnostics from the normal panel while retaining their captured data for calculation and persisted evidence.
- Added prompt-attention evidence to `steps.jsonl` and Markdown/HTML reports while retaining an explicit non-causal boundary.
- Verified cold/cold decoded output identity, callback order, 8-step SDXL role vectors, live UI rendering, and the paired performance budget.

## 0.4.0b1 — Private beta candidate

- Reduced the public capture modes to Basic and Advanced; legacy Deep workflow values now normalize to Advanced.
- Folded high-cost x/x0, detailed CFG, and ControlNet residual statistics into Advanced behind `persist_tensor_stats`.
- Added x/x0 summaries and observed ControlNet residuals to aligned A/B step comparison and the decoded x0 preview difference UI.
- Added persisted A/B Markdown/HTML reports with workflow, requested/actual sampler, model patch, x0, Control, and Preview evidence.
- Persisted ComfyUI backend prompt IDs on runs so concurrent clients and queued prompts retain an exact prompt-to-run link.
- Validated ControlNet, IPAdapter, easy-use, EasyIllustrious, and two-client concurrent prompt/report flows on the live local installation.
- Added a repeatable live benchmark with cache avoidance, history wall time, NVML peak, run disk size, and decoded pixel identity checks.
- Validated Off, Basic, Advanced standard, and Advanced influence modes across three paired seeds with identical decoded output per seed.
- Validated metadata-free cold/cold Trace identity plus OpenPose and Depth ControlNet residual capture on the live local installation.
- Added per-run note history with inline create, edit, and confirmed delete actions.
- Added stable note IDs and atomic JSONL updates, with automatic Markdown/HTML report refresh.
- Kept run notes in ComfyUI user data (or ignored `data/` fallback) so personal observations are excluded from source publication by default.
- Added a read-only workflow usage scanner for saved JSON, PNG structural metadata, embedded/subgraph workflows, and localhost ComfyUI history.
- Separated usage state from trace priority and kept unobserved packages as `UNKNOWN`.
- Added usage-based adapter planning, four-package runtime source review, and a user decision queue.
- Completed the local performance baseline after the KSampler, ControlNet, P1 Adapter, and A/B report runtime gates passed.
- Kept local workflow inventories out of the release archive without making the packaged static check fail.
- Connected private-beta installation and issue reporting to the private GitHub repository.
- Fixed repository text checkouts to LF so packaged source checksums stay portable across Windows clones.
- Added custom output-root support to the live benchmark so isolated ComfyUI output directories are verified correctly.
- Unified the health and persisted Run plugin version with the `pyproject.toml` version (`0.4.0b1`).
- Passed packaged-build internal acceptance in an isolated ComfyUI root: install, plugin-only boot, actual sampling, UI, notes, compare/report, error responses, deletion, and restart persistence.

## 0.3.0 — Static inventory precision

- Replaced whole-file runtime classification with Python AST symbol, declared input/output type, and call-site evidence.
- Separated sampler API/configuration references from actual sampler execution signals.
- Ignored frontend labels/comments and auxiliary test/example/demo directories for runtime classification by default.
- Added UTF-8 BOM-safe Python parsing and top-level parse-error counts in JSON and Markdown reports.
- Kept non-ComfyUI `sys`/`torch` mutations as review flags without automatically requiring a Trace adapter.
- Added regression coverage for known false positives, including manager/UI, tagger, detector, audio, and sampler-configuration patterns.
- Verified the corrected scanner against 36 installed packages: Priority A `24 → 11`, required adapters `15 → 4`, parse errors `2 → 0`.

## 0.2.0 — Installed custom-node inventory

- Added a static-only scanner for the user's installed `custom_nodes`.
- Added AST extraction for `NODE_CLASS_MAPPINGS`, ComfyUI types, and frontend declarations.
- Added evidence flags for ModelPatcher, sampler, ControlNet, IPAdapter, LoRA, Detailer, Regional, Tiled, Qwen, server routes, WebSocket events, network/download code, subprocesses, and suspected monkey patches.
- Added Priority A/B/C, trace compatibility, recommended hook points, and dedicated-adapter assessment.
- Added Git/version/dependency metadata and source fingerprints for update comparison.
- Added JSON/Markdown inventory, compatibility matrix, adapter priority, Windows wrappers, tests, and Codex-first inventory workflow.

## 0.1.0 — Implementation draft

- Added `Trace Model` wrapper node.
- Added sampling-step capture for `x`, `x0`, Sigma, Preview, CFG, and ControlNet summaries.
- Added generic Image / Latent / Mask / Conditioning probes.
- Added WebSocket-driven node execution timeline panel.
- Added local run persistence, Markdown/HTML reports, and A/B comparison endpoint.
- Added Codex handoff, test plan, phase map, and compatibility notes.
- Added Basic/Advanced/Deep capture modes and bounded Tensor traversal.
- Added observation-based diagnostics that propose one-variable A/B experiments.
- Matched the current ComfyUI frontend custom bottom-panel render/destroy contract.
- Added 16 independent/simulated tests and build-validation documentation.
