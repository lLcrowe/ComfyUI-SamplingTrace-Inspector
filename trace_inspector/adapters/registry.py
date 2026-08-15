from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from .base import NodeSemanticAdapter
from .builtins import BUILTIN_ADAPTERS


class AdapterRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._adapters: list[NodeSemanticAdapter] = []
        for adapter in BUILTIN_ADAPTERS:
            self.register(adapter)

    def register(self, adapter: NodeSemanticAdapter) -> None:
        with self._lock:
            self._adapters = [existing for existing in self._adapters if existing.adapter_id != adapter.adapter_id]
            self._adapters.append(adapter)
            self._adapters.sort(key=lambda item: item.priority, reverse=True)

    def unregister(self, adapter_id: str) -> None:
        with self._lock:
            self._adapters = [adapter for adapter in self._adapters if adapter.adapter_id != adapter_id]

    def summarize(self, node: Mapping[str, Any]) -> dict[str, Any] | None:
        class_type = str(node.get("classType") or node.get("class_type") or "")
        with self._lock:
            for adapter in self._adapters:
                if adapter.matches(class_type):
                    summary = adapter.summarize(node)
                    summary["classType"] = class_type
                    return summary
        return None

    def adapter_ids(self) -> list[str]:
        with self._lock:
            return [adapter.adapter_id for adapter in self._adapters]


ADAPTER_REGISTRY = AdapterRegistry()
