"""ComfyUI custom-node entry point.

Pytest may import this file as a standalone top-level module because the
repository directory contains a hyphen. In that tooling-only case we avoid
loading ComfyUI-specific modules. ComfyUI itself loads custom-node folders as
packages, so the normal relative-import branch is used there.
"""

if __package__:
    from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
    from .trace_inspector.server_routes import register_routes

    WEB_DIRECTORY = "./web"
    register_routes()
else:  # Tooling-only fallback; not used by ComfyUI's package loader.
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}
    WEB_DIRECTORY = "./web"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
