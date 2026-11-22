"""MiniMax H3 Motion Context / MultiRef / latent-masking custom nodes.

Also vendors the H3 Continuity authoring layer (MIT, upstream
ComfyUI-H3-Continuity-Studio @ 16cc1779): its 19 V3 nodes register through
``comfy_entrypoint`` below, its ``/h3c/*`` routes self-register here, and its
Studio frontend ships under ``js/`` alongside this pack's own extensions.

ComfyUI provides ``folder_paths`` before loading custom nodes.  Keeping the
package import harmless when that module is absent lets the repository's
standalone CPU/static tests run without pretending a full ComfyUI installation
is available.
"""

try:
    import folder_paths as _folder_paths  # noqa: F401
except ModuleNotFoundError:
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}
else:
    from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
    from .h3_continuity import routes as _h3c_routes
    _h3c_routes.register()

WEB_DIRECTORY = "./js"


async def comfy_entrypoint():
    """V3 extension surface: the 19 H3C_* nodes (V1 mappings coexist)."""
    from .h3_continuity.extension import comfy_entrypoint as _ep
    return await _ep()


__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
    "comfy_entrypoint",
]
