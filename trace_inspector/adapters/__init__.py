from .base import NodeSemanticAdapter
from .registry import ADAPTER_REGISTRY, AdapterRegistry


def register_adapter(adapter: NodeSemanticAdapter) -> None:
    ADAPTER_REGISTRY.register(adapter)


__all__ = [
    "NodeSemanticAdapter",
    "AdapterRegistry",
    "ADAPTER_REGISTRY",
    "register_adapter",
]
