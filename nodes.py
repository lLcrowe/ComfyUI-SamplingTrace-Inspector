from __future__ import annotations

from typing import Any

from .trace_inspector.config import PREVIEW_DECODERS, PREVIEW_FORMATS, TRACE_MODES, TraceOptions
from .trace_inspector.events import emit
from .trace_inspector.model_snapshot import snapshot_model_patcher
from .trace_inspector.prompt_capture import PromptTokenCapture, TracingClipProxy
from .trace_inspector.prompt_analysis import extract_standard_prompt_tokenization
from .trace_inspector.runtime_hooks import install_runtime_hooks
from .trace_inspector.session import TraceSession, utc_now
from .trace_inspector.tensor_stats import conditioning_summary, recursive_tensor_summary, tensor_summary


def _current_prompt_id() -> str | None:
    try:
        from comfy_execution.utils import get_executing_context

        context = get_executing_context()
        prompt_id = getattr(context, "prompt_id", None)
        return str(prompt_id) if prompt_id else None
    except Exception:
        return None


def _probe_payload(
    *,
    node_id: str,
    probe_type: str,
    label: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "nodeId": str(node_id),
        "probeType": probe_type,
        "label": (label or "").strip()[:160],
        "summary": summary,
        "timestamp": utc_now(),
    }


def _record_probe(session: TraceSession | None, payload: dict[str, Any]) -> None:
    if isinstance(session, TraceSession):
        session.add_probe(payload)
    else:
        emit("trace_inspector.probe", payload)


class ComfyTraceOneNode:
    """Start MODEL and prompt tracing from one workflow node."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "final_model": ("MODEL", {"display_name": "① 최종 MODEL"}),
                "checkpoint_clip": ("CLIP", {"display_name": "② 체크포인트 CLIP"}),
            },
            "optional": {
                "trace_preset": (TRACE_MODES, {"default": "basic"}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("MODEL", "CLIP", "TRACE_SESSION")
    RETURN_NAMES = ("③ 샘플러로", "④ 긍정·부정 Text Encode로", "선택 · 고급 연동")
    FUNCTION = "attach"
    CATEGORY = "Sampling Trace Inspector"
    DESCRIPTION = (
        "Recommended one-node setup. Connect the final MODEL and Checkpoint CLIP here, "
        "then send MODEL to the sampler and fan CLIP out to both Positive and Negative Text Encode nodes. "
        "Use the Trace Settings popup to choose Basic or Advanced capture. MODEL sampling and actual CLIP "
        "tokenize calls are recorded in the same Run without a prompt_trace wire."
    )

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def attach(
        self,
        final_model: Any,
        checkpoint_clip: Any,
        unique_id: str,
        prompt: Any = None,
        extra_pnginfo: Any = None,
        trace_preset: str = "basic",
    ):
        preset = "advanced" if str(trace_preset).strip().lower() == "advanced" else "basic"
        capture = PromptTokenCapture(prompt, trace_node_id=str(unique_id))
        traced_model, session = ComfyTraceModel().attach(
            model=final_model,
            mode=preset,
            label="",
            preview_every=1,
            preview_max_side=768,
            preview_format="JPEG",
            preview_quality=85,
            persist_previews=True,
            persist_tensor_stats=preset == "advanced",
            unique_id=unique_id,
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
            preview_decoder="clear",
            prompt_trace=capture,
        )
        return traced_model, TracingClipProxy(checkpoint_clip, capture), session


class ComfyTraceClip:
    """Pass CLIP through a non-mutating proxy and capture its actual tokenize calls."""

    DEPRECATED = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP", {"display_name": "① 체크포인트 CLIP"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID", "prompt": "PROMPT"},
        }

    RETURN_TYPES = ("CLIP", "PROMPT_TRACE")
    # Output links are index-based, so these visible labels remain workflow-compatible.
    # Korean is the compatibility fallback for older frontends that ignore custom
    # socket i18n. Newer frontends and slot_localization.js switch these per locale.
    RETURN_NAMES = ("② 긍정·부정 Text Encode", "③ CLIP 프롬프트 추적 보내기")
    FUNCTION = "attach"
    CATEGORY = "Sampling Trace Inspector"
    DESCRIPTION = (
        "Connect Checkpoint CLIP here, then fan the CLIP output out to both Positive and Negative Text Encode nodes. "
        "Connect prompt_trace to the Sampling Trace Model prompt_trace input, not the Inspector panel or trace_session. "
        "The original CLIP values pass through unchanged."
    )

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def attach(self, clip: Any, unique_id: str, prompt: Any = None):
        capture = PromptTokenCapture(prompt, trace_node_id=str(unique_id))
        return TracingClipProxy(clip, capture), capture


class ComfyTraceModel:
    """Clone a MODEL and attach non-destructive sampling/model wrappers."""

    DEPRECATED = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "mode": (TRACE_MODES, {"default": "advanced"}),
                "label": ("STRING", {"default": "", "multiline": False}),
                "preview_every": ("INT", {"default": 1, "min": 1, "max": 100, "step": 1}),
                "preview_max_side": ("INT", {"default": 768, "min": 128, "max": 4096, "step": 64}),
                "preview_format": (PREVIEW_FORMATS, {"default": "JPEG"}),
                "preview_quality": ("INT", {"default": 85, "min": 40, "max": 100, "step": 1}),
                "persist_previews": ("BOOLEAN", {"default": True}),
                "persist_tensor_stats": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "preview_decoder": (PREVIEW_DECODERS, {"default": "clear"}),
                "prompt_trace": (
                    "PROMPT_TRACE",
                    {"display_name": "③ CLIP 프롬프트 추적 받기"},
                ),
                "clip": (
                    "CLIP",
                    {"display_name": "이전 방식 · 새 연결 금지"},
                ),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("MODEL", "TRACE_SESSION")
    RETURN_NAMES = ("model", "trace_session")
    FUNCTION = "attach"
    CATEGORY = "Sampling Trace Inspector"
    DESCRIPTION = (
        "Attach Preview (중간 미리보기), Latent (잠재 표현), CFG, and ControlNet tracing "
        "to a cloned MODEL without replacing KSampler."
    )

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # A fresh run/session is required for every queue execution even when all inputs are cached.
        return float("nan")

    def attach(
        self,
        model: Any,
        mode: str,
        label: str,
        preview_every: int,
        preview_max_side: int,
        preview_format: str,
        preview_quality: int,
        persist_previews: bool,
        persist_tensor_stats: bool,
        unique_id: str,
        prompt: Any = None,
        extra_pnginfo: Any = None,
        preview_decoder: str = "clear",
        prompt_trace: Any = None,
        clip: Any = None,
    ):
        options = TraceOptions.from_node_inputs(
            mode=mode,
            label=label,
            preview_every=preview_every,
            preview_max_side=preview_max_side,
            preview_format=preview_format,
            preview_quality=preview_quality,
            persist_previews=persist_previews,
            persist_tensor_stats=persist_tensor_stats,
            preview_decoder=preview_decoder,
        )
        traced_model = model.clone()
        prompt_tokenization = (
            prompt_trace.snapshot()
            if isinstance(prompt_trace, PromptTokenCapture)
            else extract_standard_prompt_tokenization(prompt, clip)
        )
        session = TraceSession.create(
            node_id=str(unique_id),
            options=options,
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
            prompt_tokenization=prompt_tokenization,
            prompt_id=_current_prompt_id(),
        )
        if isinstance(prompt_trace, PromptTokenCapture):
            prompt_trace.bind(session)
        session.attach_model_snapshot(traced_model)
        try:
            install_runtime_hooks(traced_model, session)
        except Exception as exc:
            # Preserve the original MODEL behavior even when tracing cannot attach.
            session.record_error("install_runtime_hooks", exc)
            try:
                session.finalize(status="error")
            except Exception as finalize_exc:
                session.record_error("install_runtime_hooks_finalize", finalize_exc)
        return traced_model, session


class ComfyTraceExport:
    """Finalize a trace run and expose its report directory."""

    DEPRECATED = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "trace_session": ("TRACE_SESSION",),
                "status": (("success", "interrupted", "error"), {"default": "success"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("report_directory",)
    FUNCTION = "export"
    OUTPUT_NODE = True
    CATEGORY = "Sampling Trace Inspector"
    DESCRIPTION = (
        "Finish the connected Sampling Trace run, write its report files, "
        "and return the saved run directory."
    )

    def export(self, trace_session: TraceSession, status: str):
        trace_session.finalize(status=status)
        path = str(trace_session.run_directory())
        return {"ui": {"text": [path]}, "result": (path,)}


class ComfyTraceNote:
    """Save a user note into the connected trace run."""

    DEPRECATED = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "trace_session": ("TRACE_SESSION",),
                "note": ("STRING", {"default": "", "multiline": True}),
                "category": (("observation", "hypothesis", "decision", "issue"), {"default": "observation"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("TRACE_SESSION",)
    RETURN_NAMES = ("trace_session",)
    FUNCTION = "add_note"
    CATEGORY = "Sampling Trace Inspector"
    DESCRIPTION = (
        "Add an observation, hypothesis, decision, or issue note to the connected "
        "Sampling Trace run."
    )

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def add_note(self, trace_session: TraceSession, note: str, category: str, unique_id: str):
        trace_session.add_probe(
            _probe_payload(
                node_id=str(unique_id),
                probe_type="note",
                label=category,
                summary={"text": note[:8000]},
            )
        )
        return (trace_session,)


class _ProbeBase:
    DEPRECATED = True
    RETURN_TYPES: tuple[str, ...] = ()
    RETURN_NAMES: tuple[str, ...] = ()
    FUNCTION = "probe"
    CATEGORY = "Sampling Trace Inspector/Probes"

    @classmethod
    def optional_inputs(cls):
        return {
            "label": ("STRING", {"default": "", "multiline": False}),
            "trace_session": ("TRACE_SESSION",),
        }


class ComfyTraceImage(_ProbeBase):
    """Record IMAGE tensor metadata without changing the image."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"image": ("IMAGE",)},
            "optional": cls.optional_inputs(),
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    DESCRIPTION = (
        "Inspect IMAGE shape, type, range, and statistics, then pass the image through unchanged."
    )

    def probe(self, image: Any, unique_id: str, label: str = "", trace_session: TraceSession | None = None):
        payload = _probe_payload(
            node_id=unique_id,
            probe_type="image",
            label=label,
            summary=tensor_summary(image, include_statistics=True),
        )
        _record_probe(trace_session, payload)
        return (image,)


class ComfyTraceLatent(_ProbeBase):
    """Record LATENT tensor metadata without changing the latent."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"latent": ("LATENT",)},
            "optional": cls.optional_inputs(),
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("latent",)
    DESCRIPTION = (
        "Inspect LATENT shape, keys, range, and statistics, then pass the latent through unchanged."
    )

    def probe(self, latent: Any, unique_id: str, label: str = "", trace_session: TraceSession | None = None):
        samples = latent.get("samples") if isinstance(latent, dict) else latent
        summary = tensor_summary(samples, include_statistics=True)
        if isinstance(latent, dict):
            summary["latentKeys"] = sorted(str(key) for key in latent.keys())
        payload = _probe_payload(
            node_id=unique_id,
            probe_type="latent",
            label=label,
            summary=summary,
        )
        _record_probe(trace_session, payload)
        return (latent,)


class ComfyTraceMask(_ProbeBase):
    """Record MASK tensor metadata without changing the mask."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"mask": ("MASK",)},
            "optional": cls.optional_inputs(),
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    DESCRIPTION = (
        "Inspect MASK shape, type, range, and statistics, then pass the mask through unchanged."
    )

    def probe(self, mask: Any, unique_id: str, label: str = "", trace_session: TraceSession | None = None):
        payload = _probe_payload(
            node_id=unique_id,
            probe_type="mask",
            label=label,
            summary=tensor_summary(mask, include_statistics=True),
        )
        _record_probe(trace_session, payload)
        return (mask,)


class ComfyTraceConditioning(_ProbeBase):
    """Record CONDITIONING metadata without changing conditioning."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"conditioning": ("CONDITIONING",)},
            "optional": cls.optional_inputs(),
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("conditioning",)
    DESCRIPTION = (
        "Inspect prompt conditioning tensors and metadata, then pass the conditioning through unchanged."
    )

    def probe(
        self,
        conditioning: Any,
        unique_id: str,
        label: str = "",
        trace_session: TraceSession | None = None,
    ):
        payload = _probe_payload(
            node_id=unique_id,
            probe_type="conditioning",
            label=label,
            summary=conditioning_summary(
                conditioning,
                include_statistics=True,
                max_samples=65_536,
            ),
        )
        _record_probe(trace_session, payload)
        return (conditioning,)


class ComfyTraceModelSnapshot(_ProbeBase):
    """Record a point-in-time MODEL patch summary."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"model": ("MODEL",)},
            "optional": cls.optional_inputs(),
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)
    DESCRIPTION = (
        "Capture a point-in-time summary of MODEL patches and options, then pass the model through unchanged. "
        "This does not start sampling trace capture by itself."
    )

    def probe(self, model: Any, unique_id: str, label: str = "", trace_session: TraceSession | None = None):
        payload = _probe_payload(
            node_id=unique_id,
            probe_type="model",
            label=label,
            summary=snapshot_model_patcher(model),
        )
        _record_probe(trace_session, payload)
        return (model,)


NODE_CLASS_MAPPINGS = {
    "ComfyTraceOneNode": ComfyTraceOneNode,
    "ComfyTraceClip": ComfyTraceClip,
    "ComfyTraceModel": ComfyTraceModel,
    "ComfyTraceExport": ComfyTraceExport,
    "ComfyTraceNote": ComfyTraceNote,
    "ComfyTraceImage": ComfyTraceImage,
    "ComfyTraceLatent": ComfyTraceLatent,
    "ComfyTraceMask": ComfyTraceMask,
    "ComfyTraceConditioning": ComfyTraceConditioning,
    "ComfyTraceModelSnapshot": ComfyTraceModelSnapshot,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ComfyTraceOneNode": "Sampling Trace · One Node Setup",
    "ComfyTraceClip": "Sampling Trace CLIP · Connect Both Prompts",
    "ComfyTraceModel": "Sampling Trace Model",
    "ComfyTraceExport": "Sampling Trace Export / Finalize",
    "ComfyTraceNote": "Sampling Trace Note",
    "ComfyTraceImage": "Sampling Trace Image",
    "ComfyTraceLatent": "Sampling Trace Latent",
    "ComfyTraceMask": "Sampling Trace Mask",
    "ComfyTraceConditioning": "Sampling Trace Conditioning",
    "ComfyTraceModelSnapshot": "Sampling Trace Model Snapshot",
}
