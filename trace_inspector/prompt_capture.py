from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from .prompt_analysis import _prompt_role_map, serialize_clip_tokens


def _current_node_id() -> str | None:
    try:
        from comfy_execution.utils import get_executing_context

        context = get_executing_context()
        node_id = getattr(context, "node_id", None)
        return str(node_id) if node_id is not None else None
    except Exception:
        return None


class PromptTokenCapture:
    """Thread-safe record of actual tokenize calls made through one CLIP branch."""

    def __init__(self, prompt: Any, *, trace_node_id: str | None = None) -> None:
        self.prompt = prompt if isinstance(prompt, Mapping) else {}
        self.trace_node_id = str(trace_node_id) if trace_node_id is not None else None
        self.roles = _prompt_role_map(self.prompt)
        self.calls_by_node: dict[str, list[dict[str, Any]]] = {}
        self.errors: list[str] = []
        self._session: Any = None
        self._lock = threading.RLock()

    def _node(self, node_id: str) -> Mapping[str, Any]:
        raw = self.prompt.get(node_id)
        if raw is None and node_id.isdigit():
            raw = self.prompt.get(int(node_id))
        return raw if isinstance(raw, Mapping) else {}

    def _source_field(self, node_id: str, text: str, call_index: int) -> tuple[str, bool]:
        node = self._node(node_id)
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs") if isinstance(node.get("inputs"), Mapping) else {}
        for key in ("text", "text_g", "text_l"):
            if key in inputs and str(inputs.get(key) or "") == text:
                return key, False
        if class_type == "CLIPTextEncodeSDXL":
            if call_index == 0:
                return "text_g", False
            if call_index == 1:
                return "text_l", False
            if text == "":
                return "chunk_padding", True
        if class_type in {"CLIPTextEncode", "CLIPTextEncodeSDXLRefiner"} and call_index == 0:
            return "text", False
        return f"tokenize_call_{call_index + 1}", False

    def record(self, clip: Any, text: Any, tokenized: Any, *, node_id: str | None = None) -> None:
        resolved_node_id = str(node_id) if node_id is not None else _current_node_id() or "unknown"
        text_value = str(text)[:8000]
        with self._lock:
            calls = self.calls_by_node.setdefault(resolved_node_id, [])
            call_index = len(calls)
            source_field, internal = self._source_field(resolved_node_id, text_value, call_index)
            try:
                encoders = serialize_clip_tokens(clip, tokenized)
                error = None
            except Exception as exc:
                encoders = []
                error = f"{type(exc).__name__}: {exc}"[:1000]
                self.errors.append(error)
            encoder_names = [str(encoder.get("name")) for encoder in encoders]
            used_encoders = (
                ["g"] if source_field == "text_g" and "g" in encoder_names
                else ["l"] if source_field == "text_l" and "l" in encoder_names
                else encoder_names
            )
            calls.append(
                {
                    "callIndex": call_index,
                    "sourceField": source_field,
                    "internal": internal,
                    "text": text_value,
                    "encoders": encoders,
                    "usedEncoders": used_encoders,
                    **({"error": error} if error else {}),
                }
            )
            session = self._session
            snapshot = self._snapshot_unlocked()
        if session is not None:
            session.update_prompt_tokenization(snapshot)

    def record_error(self, exc: BaseException) -> None:
        with self._lock:
            self.errors.append(f"{type(exc).__name__}: {exc}"[:1000])
            session = self._session
            snapshot = self._snapshot_unlocked()
        if session is not None:
            session.update_prompt_tokenization(snapshot)

    def _snapshot_unlocked(self) -> dict[str, Any]:
        prompts: list[dict[str, Any]] = []
        lanes: set[str] = set()
        for node_id, calls in self.calls_by_node.items():
            node = self._node(node_id)
            for call in calls:
                lanes.update(str(encoder.get("name")) for encoder in call.get("encoders", []))
            prompts.append(
                {
                    "nodeId": node_id,
                    "classType": str(node.get("class_type", "Unknown")),
                    "roles": sorted(self.roles.get(node_id, {"unknown"})),
                    "calls": [dict(call) for call in calls],
                }
            )
        prompts.sort(key=lambda item: (int(item["nodeId"]) if item["nodeId"].isdigit() else 10**12, item["nodeId"]))
        call_count = sum(len(prompt["calls"]) for prompt in prompts)
        return {
            "status": "captured" if call_count and not self.errors else "partial" if call_count else "waiting_for_calls",
            "source": "traced_clip",
            "traceClipNodeId": self.trace_node_id,
            "modelFamily": "sdxl" if {"g", "l"}.issubset(lanes) else "single_encoder" if lanes else None,
            "callCount": call_count,
            "prompts": prompts,
            "messages": list(self.errors),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked()

    def bind(self, session: Any) -> None:
        with self._lock:
            self._session = session
            snapshot = self._snapshot_unlocked()
        session.update_prompt_tokenization(snapshot)


class TracingClipProxy:
    """Delegate CLIP operations while observing tokenize results without mutation."""

    def __init__(self, clip: Any, capture: PromptTokenCapture) -> None:
        object.__setattr__(self, "_clip", clip)
        object.__setattr__(self, "_capture", capture)

    def tokenize(self, text: Any, *args: Any, **kwargs: Any) -> Any:
        result = self._clip.tokenize(text, *args, **kwargs)
        try:
            self._capture.record(self._clip, text, result)
        except Exception as exc:
            # Token observation must never change the original CLIP call result.
            try:
                self._capture.record_error(exc)
            except Exception:
                pass
        return result

    def clone(self) -> "TracingClipProxy":
        clone = self._clip.clone() if hasattr(self._clip, "clone") else self._clip
        return TracingClipProxy(clone, self._capture)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._clip, name)

    def __repr__(self) -> str:
        return f"TracingClipProxy({self._clip!r})"
