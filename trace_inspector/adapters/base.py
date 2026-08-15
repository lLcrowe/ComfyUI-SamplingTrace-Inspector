from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any


class NodeSemanticAdapter(ABC):
    """Turn a generic ComfyUI prompt node into a human-readable semantic record."""

    adapter_id: str = "base"
    priority: int = 0

    @abstractmethod
    def matches(self, class_type: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def summarize(self, node: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def selected_inputs(node: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        inputs = node.get("inputs", {})
        if not isinstance(inputs, Mapping):
            return {}
        return {key: inputs[key] for key in keys if key in inputs}
