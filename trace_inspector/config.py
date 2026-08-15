from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


TRACE_MODES = ("basic", "advanced")
PREVIEW_FORMATS = ("JPEG", "PNG")
PREVIEW_DECODERS = ("clear", "fast")


@dataclass(frozen=True, slots=True)
class TraceOptions:
    """Runtime capture settings attached to one traced MODEL."""

    mode: str = "advanced"
    label: str = ""
    preview_every: int = 1
    preview_max_side: int = 768
    preview_format: str = "JPEG"
    preview_quality: int = 85
    preview_decoder: str = "clear"
    persist_previews: bool = True
    persist_tensor_stats: bool = True
    max_tensor_samples: int = 65_536

    def __post_init__(self) -> None:
        # Old workflows may still submit the removed "deep" value. Preserve
        # their intent by folding it into Advanced instead of rejecting them.
        normalized_mode = "advanced" if self.mode == "deep" else self.mode
        if normalized_mode not in TRACE_MODES:
            normalized_mode = "advanced"
        object.__setattr__(self, "mode", normalized_mode)

    @classmethod
    def from_node_inputs(
        cls,
        *,
        mode: str,
        label: str,
        preview_every: int,
        preview_max_side: int,
        preview_format: str,
        preview_quality: int,
        persist_previews: bool,
        persist_tensor_stats: bool,
        preview_decoder: str = "clear",
    ) -> "TraceOptions":
        normalized_mode = "advanced" if mode == "deep" else mode
        if normalized_mode not in TRACE_MODES:
            normalized_mode = "advanced"
        normalized_format = preview_format.upper()
        if normalized_format not in PREVIEW_FORMATS:
            normalized_format = "JPEG"
        normalized_decoder = str(preview_decoder or "clear").lower()
        if normalized_decoder not in PREVIEW_DECODERS:
            normalized_decoder = "clear"

        return cls(
            mode=normalized_mode,
            label=(label or "").strip()[:160],
            preview_every=max(1, int(preview_every)),
            preview_max_side=max(128, min(4096, int(preview_max_side))),
            preview_format=normalized_format,
            preview_quality=max(40, min(100, int(preview_quality))),
            preview_decoder=normalized_decoder,
            persist_previews=bool(persist_previews),
            persist_tensor_stats=bool(persist_tensor_stats),
        )

    @property
    def captures_statistics(self) -> bool:
        return self.mode == "advanced" and self.persist_tensor_stats

    @property
    def captures_cfg(self) -> bool:
        return self.mode == "advanced"

    @property
    def captures_control_residuals(self) -> bool:
        return self.mode == "advanced" and self.persist_tensor_stats

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
