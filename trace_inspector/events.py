from __future__ import annotations

import logging
from typing import Any

from .json_utils import json_safe

LOGGER = logging.getLogger("comfy.trace_inspector")


def emit(event_type: str, payload: dict[str, Any]) -> None:
    """Send a custom ComfyUI WebSocket message without affecting generation."""
    try:
        from server import PromptServer

        server = getattr(PromptServer, "instance", None)
        if server is None:
            return
        server.send_sync(event_type, json_safe(payload))
    except Exception as exc:
        LOGGER.debug("Trace event emission failed: %s", exc)
