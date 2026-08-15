from __future__ import annotations

from typing import Any

from .trace_inspector.config import PREVIEW_FORMATS, TRACE_MODES, TraceOptions
from .trace_inspector.events import emit
from .trace_inspector.model_snapshot import snapshot_model_patcher
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


class ComfyTraceModel:
    """Clone a MODEL and attach non-destructive sampling/model wrappers."""

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
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("MODEL", "TRACE_SESSION")
    RETURN_NAMES = ("model", "trace_session")
    FUNCTION = "attach"
    CATEGORY = "SamplingTrace Inspector"
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
        )
        traced_model = model.clone()
        session = TraceSession.create(
            node_id=str(unique_id),
            options=options,
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
            prompt_id=_current_prompt_id(),
        )
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
    CATEGORY = "SamplingTrace Inspector"

    def export(self, trace_session: TraceSession, status: str):
        trace_session.finalize(status=status)
        path = str(trace_session.run_directory())
        return {"ui": {"text": [path]}, "result": (path,)}


class ComfyTraceNote:
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
    CATEGORY = "SamplingTrace Inspector"

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
    RETURN_TYPES: tuple[str, ...] = ()
    RETURN_NAMES: tuple[str, ...] = ()
    FUNCTION = "probe"
    CATEGORY = "SamplingTrace Inspector/Probes"

    @classmethod
    def optional_inputs(cls):
        return {
            "label": ("STRING", {"default": "", "multiline": False}),
            "trace_session": ("TRACE_SESSION",),
        }


class ComfyTraceImage(_ProbeBase):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"image": ("IMAGE",)},
            "optional": cls.optional_inputs(),
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)

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
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"latent": ("LATENT",)},
            "optional": cls.optional_inputs(),
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("latent",)

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
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"mask": ("MASK",)},
            "optional": cls.optional_inputs(),
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)

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
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"conditioning": ("CONDITIONING",)},
            "optional": cls.optional_inputs(),
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("conditioning",)

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
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"model": ("MODEL",)},
            "optional": cls.optional_inputs(),
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("model",)

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
    "ComfyTraceModel": "SamplingTrace Model",
    "ComfyTraceExport": "SamplingTrace Export / Finalize",
    "ComfyTraceNote": "SamplingTrace Note",
    "ComfyTraceImage": "SamplingTrace Image",
    "ComfyTraceLatent": "SamplingTrace Latent",
    "ComfyTraceMask": "SamplingTrace Mask",
    "ComfyTraceConditioning": "SamplingTrace Conditioning",
    "ComfyTraceModelSnapshot": "SamplingTrace Model Snapshot",
}
