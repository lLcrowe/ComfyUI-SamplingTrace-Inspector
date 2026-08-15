from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from . import PLUGIN_VERSION, TRACE_SCHEMA_VERSION
from .config import TraceOptions
from .events import emit
from .model_snapshot import snapshot_model_patcher
from .preview_capture import (
    decode_preview,
    preview_difference,
    preview_thumbnail,
    save_preview,
)
from .prompt_analysis import analyze_prompt, extract_generation_settings
from .store import STORE
from .tensor_stats import (
    recursive_tensor_summary,
    tensor_difference_summary,
    tensor_summary,
)

LOGGER = logging.getLogger("comfy.trace_inspector")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scalar(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if hasattr(value, "detach"):
            value = value.detach()
        if hasattr(value, "reshape"):
            value = value.reshape(-1)[0]
        if hasattr(value, "item"):
            value = value.item()
        return float(value)
    except Exception:
        return None


def _sigmas_to_list(sigmas: Any, limit: int = 4096) -> list[float]:
    try:
        if hasattr(sigmas, "detach"):
            values = sigmas.detach().to(device="cpu").reshape(-1).tolist()
        else:
            values = list(sigmas)
        return [float(value) for value in values[:limit]]
    except Exception:
        return []


def _sampler_name(sampler: Any) -> str:
    if sampler is None:
        return "unknown"
    function = getattr(sampler, "sampler_function", None)
    if function is not None:
        return getattr(function, "__name__", type(function).__name__)
    return f"{type(sampler).__module__}.{type(sampler).__name__}"


def _aggregate_cfg(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {"eventCount": 0}
    latest = events[-1]
    deltas = [
        event.get("delta", {}).get("meanAbs")
        for event in events
        if isinstance(event.get("delta"), dict)
        and isinstance(event.get("delta", {}).get("meanAbs"), (int, float))
    ]
    result = {
        "eventCount": len(events),
        "condScale": latest.get("condScale"),
        "sigma": latest.get("sigma"),
        "delta": latest.get("delta"),
        "deltaMeanAbs": (sum(deltas) / len(deltas)) if deltas else None,
    }
    if "conditional" in latest:
        result["conditional"] = latest["conditional"]
    if "unconditional" in latest:
        result["unconditional"] = latest["unconditional"]
    return result


def _aggregate_control(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {"eventCount": 0, "active": False}
    active_events = [event for event in events if event.get("active")]
    latest = active_events[-1] if active_events else events[-1]
    residuals = [
        event.get("residual")
        for event in active_events
        if isinstance(event.get("residual"), dict)
    ]
    weighted = [
        residual.get("weightedMeanAbs")
        for residual in residuals
        if isinstance(residual.get("weightedMeanAbs"), (int, float))
    ]
    max_abs = [
        residual.get("maxAbs")
        for residual in residuals
        if isinstance(residual.get("maxAbs"), (int, float))
    ]
    result: dict[str, Any] = {
        "eventCount": len(events),
        "activeEventCount": len(active_events),
        "active": bool(active_events),
        "sigma": latest.get("sigma"),
        "condOrUncond": latest.get("condOrUncond"),
        "controlKeys": latest.get("controlKeys", []),
        "transformerPatchKeys": latest.get("transformerPatchKeys", []),
        "weightedMeanAbs": (sum(weighted) / len(weighted)) if weighted else None,
        "maxAbs": max(max_abs) if max_abs else None,
    }
    if residuals:
        result["latestResidual"] = residuals[-1]
    return result


class TraceSession:
    """Thread-safe state for one workflow execution and one traced MODEL chain."""

    def __init__(
        self,
        *,
        node_id: str,
        options: TraceOptions,
        prompt: Any,
        extra_pnginfo: Any,
        prompt_tokenization: Mapping[str, Any] | None = None,
        prompt_id: str | None = None,
    ) -> None:
        self.run_id = str(uuid.uuid4())
        self.node_id = str(node_id)
        self.prompt_id = str(prompt_id) if prompt_id else None
        self.options = options
        self.workflow_name: str | None = None
        self.prompt_analysis = analyze_prompt(prompt)
        self.prompt_tokenization = dict(prompt_tokenization or {})
        self.generation_settings = extract_generation_settings(self.prompt_analysis)
        self.extra_metadata = self._sanitize_extra_metadata(extra_pnginfo)
        self.model_snapshot: dict[str, Any] = {}
        self.created_at = utc_now()
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.status = "armed"
        self.segments: list[dict[str, Any]] = []
        self.step_count = 0
        self.probe_count = 0
        self.errors: list[dict[str, Any]] = []
        self.frontend_completion: dict[str, Any] | None = None

        self._lock = threading.RLock()
        self._current_segment_index: int | None = None
        self._pending_cfg: list[dict[str, Any]] = []
        self._pending_control: list[dict[str, Any]] = []
        self._previous_preview_thumb: Image.Image | None = None
        self._last_control_stats_sigma: float | None = None
        self._finalized = False
        self._sampling_started_monotonic: float | None = None

    @classmethod
    def create(
        cls,
        *,
        node_id: str,
        options: TraceOptions,
        prompt: Any,
        extra_pnginfo: Any,
        prompt_tokenization: Mapping[str, Any] | None = None,
        prompt_id: str | None = None,
    ) -> "TraceSession":
        session = cls(
            node_id=node_id,
            options=options,
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
            prompt_tokenization=prompt_tokenization,
            prompt_id=prompt_id,
        )
        STORE.register_session(session)
        emit(
            "trace_inspector.session_ready",
            {
                "runId": session.run_id,
                "nodeId": session.node_id,
                "promptId": session.prompt_id,
                "label": session.options.label,
                "options": session.options.to_dict(),
                "generationSettings": session.generation_settings,
            },
        )
        return session

    @staticmethod
    def _sanitize_extra_metadata(extra_pnginfo: Any) -> dict[str, Any]:
        if not isinstance(extra_pnginfo, dict):
            return {}
        result: dict[str, Any] = {}
        for key, value in extra_pnginfo.items():
            if key == "workflow":
                # The API prompt is already normalized and analyzed separately.
                result["workflowPresent"] = True
                continue
            if value is None or isinstance(value, (str, bool, int, float)):
                result[str(key)] = value
        return result

    def attach_model_snapshot(self, model: Any) -> None:
        with self._lock:
            self.model_snapshot = snapshot_model_patcher(model)
            STORE.persist_run(self.to_run_payload())

    def update_prompt_tokenization(self, payload: Mapping[str, Any]) -> None:
        with self._lock:
            self.prompt_tokenization = dict(payload)
            STORE.persist_run(self.to_run_payload())

    def to_run_payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schemaVersion": TRACE_SCHEMA_VERSION,
                "pluginVersion": PLUGIN_VERSION,
                "runId": self.run_id,
                "nodeId": self.node_id,
                "promptId": self.prompt_id,
                "workflowName": self.workflow_name,
                "label": self.options.label,
                "status": self.status,
                "createdAt": self.created_at,
                "startedAt": self.started_at,
                "finishedAt": self.finished_at,
                "workflowHash": self.prompt_analysis.get("workflowHash"),
                "promptAnalysis": self.prompt_analysis,
                "promptTokenization": self.prompt_tokenization,
                "generationSettings": self.generation_settings,
                "extraMetadata": self.extra_metadata,
                "modelSnapshot": self.model_snapshot,
                "options": self.options.to_dict(),
                "segments": list(self.segments),
                "stepCount": self.step_count,
                "probeCount": self.probe_count,
                "errors": list(self.errors),
                "frontendCompletion": self.frontend_completion,
            }

    def set_workflow_name(self, workflow_name: str) -> None:
        with self._lock:
            self.workflow_name = workflow_name
            STORE.persist_run(self.to_run_payload())

    def begin_sampling(
        self,
        *,
        noise: Any,
        latent_image: Any,
        sampler: Any,
        sigmas: Any,
        seed: Any,
    ) -> int:
        with self._lock:
            if self._finalized:
                # A traced model may be reused after an explicit export. Re-arm locally.
                self._finalized = False
                STORE.register_session(self)
            if self.started_at is None:
                self.started_at = utc_now()
            self.status = "running"
            segment_index = len(self.segments)
            sigma_values = _sigmas_to_list(sigmas)
            segment = {
                "segmentIndex": segment_index,
                "status": "running",
                "startedAt": utc_now(),
                "finishedAt": None,
                "durationMs": None,
                "seed": int(seed) if isinstance(seed, int) else _scalar(seed),
                "sampler": _sampler_name(sampler),
                "sigmaCount": len(sigma_values),
                "expectedSteps": max(0, len(sigma_values) - 1),
                "sigmas": sigma_values,
                "noise": tensor_summary(noise, include_statistics=False),
                "latentInput": tensor_summary(latent_image, include_statistics=False),
            }
            self.segments.append(segment)
            self._current_segment_index = segment_index
            self._pending_cfg.clear()
            self._pending_control.clear()
            self._previous_preview_thumb = None
            self._last_control_stats_sigma = None
            self._sampling_started_monotonic = time.perf_counter()
            STORE.persist_run(self.to_run_payload())

        emit(
            "trace_inspector.run_started",
            {
                "runId": self.run_id,
                "nodeId": self.node_id,
                "segmentIndex": segment_index,
                "segment": segment,
            },
        )
        return segment_index

    def _current_sigma(self, step: int) -> float | None:
        if self._current_segment_index is None:
            return None
        segment = self.segments[self._current_segment_index]
        sigmas = segment.get("sigmas") or []
        if not sigmas:
            return None
        index = max(0, min(int(step), len(sigmas) - 1))
        try:
            return float(sigmas[index])
        except (TypeError, ValueError):
            return None

    def record_cfg(self, args: dict[str, Any]) -> None:
        if not self.options.captures_cfg:
            return
        try:
            conds_out = args.get("conds_out")
            if conds_out is None:
                conds_out = []
            sigma_value = args.get("sigma")
            if sigma_value is None:
                sigma_value = args.get("timestep")
            event: dict[str, Any] = {
                "timestamp": utc_now(),
                "sigma": _scalar(sigma_value),
                "condScale": _scalar(args.get("cond_scale")),
            }
            if len(conds_out) >= 2:
                event["delta"] = tensor_difference_summary(
                    conds_out[0],
                    conds_out[1],
                    max_samples=self.options.max_tensor_samples,
                )
                if self.options.captures_statistics:
                    event["conditional"] = tensor_summary(
                        conds_out[0],
                        include_statistics=True,
                        max_samples=self.options.max_tensor_samples,
                    )
                    event["unconditional"] = tensor_summary(
                        conds_out[1],
                        include_statistics=True,
                        max_samples=self.options.max_tensor_samples,
                    )
            with self._lock:
                self._pending_cfg.append(event)
                if len(self._pending_cfg) > 256:
                    del self._pending_cfg[:-256]
        except Exception as exc:
            self.record_error("cfg", exc)

    def record_control(
        self,
        *,
        timestep: Any,
        control: Any,
        transformer_options: Any,
    ) -> None:
        try:
            options = transformer_options if isinstance(transformer_options, dict) else {}
            patches = options.get("patches", {}) if isinstance(options, dict) else {}
            patches_replace = options.get("patches_replace", {}) if isinstance(options, dict) else {}
            sigma_scalar = _scalar(timestep)
            capture_residual_stats = False
            if control is not None and self.options.captures_control_residuals:
                with self._lock:
                    if self._last_control_stats_sigma is None or sigma_scalar is None or abs(self._last_control_stats_sigma - sigma_scalar) > 1e-12:
                        capture_residual_stats = True
                        self._last_control_stats_sigma = sigma_scalar
            event: dict[str, Any] = {
                "timestamp": utc_now(),
                "sigma": sigma_scalar,
                "active": control is not None,
                "controlKeys": sorted(str(k) for k in control.keys()) if isinstance(control, dict) else [],
                "condOrUncond": options.get("cond_or_uncond"),
                "transformerPatchKeys": sorted(
                    set(str(k) for k in patches.keys()) | set(str(k) for k in patches_replace.keys())
                )
                if isinstance(patches, dict) and isinstance(patches_replace, dict)
                else [],
            }
            if control is not None and capture_residual_stats:
                event["residual"] = recursive_tensor_summary(
                    control,
                    include_statistics=True,
                    max_samples=min(self.options.max_tensor_samples, 4_096),
                    max_tensors=128,
                )
            elif control is not None and self.options.captures_control_residuals:
                event["residual"] = {"statisticsSkipped": "duplicate_sigma"}
            elif control is not None:
                event["residual"] = recursive_tensor_summary(
                    control,
                    include_statistics=False,
                    max_samples=1,
                    max_tensors=256,
                )
            with self._lock:
                self._pending_control.append(event)
                if len(self._pending_control) > 512:
                    del self._pending_control[:-512]
        except Exception as exc:
            self.record_error("control", exc)

    def capture_step(
        self,
        *,
        step: int,
        x0: Any,
        x: Any,
        total_steps: int,
        previewer: Any,
    ) -> dict[str, Any]:
        with self._lock:
            segment_index = self._current_segment_index if self._current_segment_index is not None else 0
            cfg_events = list(self._pending_cfg)
            control_events = list(self._pending_control)
            self._pending_cfg.clear()
            self._pending_control.clear()

        include_statistics = self.options.captures_statistics
        record: dict[str, Any] = {
            "runId": self.run_id,
            "segmentIndex": segment_index,
            "step": int(step),
            "totalSteps": int(total_steps),
            "sigma": self._current_sigma(step),
            "timestamp": utc_now(),
            "x": tensor_summary(
                x,
                include_statistics=include_statistics,
                max_samples=self.options.max_tensor_samples,
            ),
            "x0": tensor_summary(
                x0,
                include_statistics=include_statistics,
                max_samples=self.options.max_tensor_samples,
            ),
            "cfg": _aggregate_cfg(cfg_events),
            "control": _aggregate_control(control_events),
        }

        should_preview = self.options.persist_previews and (
            step % self.options.preview_every == 0 or step + 1 >= total_steps
        )
        if should_preview:
            image = decode_preview(previewer, x0, self.options.preview_max_side)
            if image is not None:
                extension = "png" if self.options.preview_format == "PNG" else "jpg"
                filename = f"segment_{segment_index:02d}_step_{int(step):04d}.{extension}"
                path = STORE.artifact_directory(self.run_id) / filename
                save_preview(
                    image,
                    path,
                    image_format=self.options.preview_format,
                    quality=self.options.preview_quality,
                )
                record["previewFile"] = filename
                record["previewUrl"] = f"/trace-inspector/runs/{self.run_id}/artifact/{filename}"
                record["previewSize"] = [image.width, image.height]
                record["previewChange"] = preview_difference(self._previous_preview_thumb, image)
                self._previous_preview_thumb = preview_thumbnail(image)

        with self._lock:
            self.step_count += 1
            STORE.append_step(self.run_id, record)
            if self.step_count % 5 == 0 or step + 1 >= total_steps:
                STORE.persist_run(self.to_run_payload())

        emit(
            "trace_inspector.step",
            {
                "runId": self.run_id,
                "segmentIndex": segment_index,
                "step": record["step"],
                "totalSteps": record["totalSteps"],
                "sigma": record["sigma"],
                "previewUrl": record.get("previewUrl"),
                "previewChange": record.get("previewChange"),
                "cfg": {
                    "eventCount": record["cfg"].get("eventCount"),
                    "deltaMeanAbs": record["cfg"].get("deltaMeanAbs"),
                    "condScale": record["cfg"].get("condScale"),
                },
                "control": {
                    "active": record["control"].get("active"),
                    "eventCount": record["control"].get("eventCount"),
                    "weightedMeanAbs": record["control"].get("weightedMeanAbs"),
                },
            },
        )
        return record

    def end_sampling(self, *, status: str, error: Exception | None = None) -> None:
        with self._lock:
            if self._current_segment_index is None:
                return
            segment = self.segments[self._current_segment_index]
            segment["status"] = status
            segment["finishedAt"] = utc_now()
            if self._sampling_started_monotonic is not None:
                segment["durationMs"] = round(
                    (time.perf_counter() - self._sampling_started_monotonic) * 1000.0,
                    3,
                )
            if error is not None:
                segment["error"] = f"{type(error).__name__}: {error}"
                self.record_error("sampling", error)
            self.status = "sampling_complete" if status == "success" else status
            current_index = self._current_segment_index
            self._current_segment_index = None
            self._sampling_started_monotonic = None
            STORE.persist_run(self.to_run_payload())

        try:
            STORE.generate_reports(self.run_id)
        except Exception as exc:
            self.record_error("segment_report", exc)

        emit(
            "trace_inspector.segment_finished",
            {
                "runId": self.run_id,
                "segmentIndex": current_index,
                "status": status,
                "segment": segment,
            },
        )

    def add_probe(self, probe: dict[str, Any]) -> None:
        payload = {"runId": self.run_id, "timestamp": utc_now(), **probe}
        with self._lock:
            self.probe_count += 1
            STORE.append_probe(self.run_id, payload)
            STORE.persist_run(self.to_run_payload())
        emit("trace_inspector.probe", payload)

    def record_error(self, stage: str, error: Exception) -> None:
        payload = {
            "stage": stage,
            "type": type(error).__name__,
            "message": str(error)[:1000],
            "timestamp": utc_now(),
        }
        with self._lock:
            self.errors.append(payload)
            if len(self.errors) > 100:
                del self.errors[:-100]
        LOGGER.debug("Trace error at %s: %s", stage, error)

    def finalize(
        self,
        *,
        status: str = "success",
        frontend_event: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            if self._finalized:
                return
            self._finalized = True
            self.status = status
            self.finished_at = utc_now()
            self.frontend_completion = frontend_event
            STORE.persist_run(self.to_run_payload())
            try:
                report_files = STORE.generate_reports(self.run_id)
            except Exception as exc:
                self.record_error("report", exc)
                report_files = {}
            payload = self.to_run_payload()
            payload["reportFiles"] = report_files
            STORE.persist_run(payload)

        emit(
            "trace_inspector.run_finished",
            {
                "runId": self.run_id,
                "status": status,
                "finishedAt": self.finished_at,
                "stepCount": self.step_count,
                "reportFiles": report_files,
            },
        )
        STORE.release_session(self.run_id)

    def run_directory(self) -> Path:
        return STORE.run_directory(self.run_id)
