"""H3 prompt toolkit: Promptor, Vision Analyzer, Video Forensics.

This is the pack's own implementation (originally written for Cosmic Nodes V2,
moved here when H3-Studio became the single home for everything MiniMax-H3).
It replaces the retired GPL ``h3_promptor`` subtree; the legacy node IDs
``H3_Promptor`` and ``H3_Vision_Analyzer`` now map onto these classes so old
workflows keep working.
"""

from .cosmic_h3_prompt import (
    CosmicH3Promptor,
    CosmicH3VideoForensics,
    CosmicH3VisionAnalyzer,
)
from ._routes import init_routes as _init_prompt_routes

_init_prompt_routes()

NODE_CLASS_MAPPINGS = {
    "CosmicH3Promptor": CosmicH3Promptor,
    "CosmicH3VisionAnalyzer": CosmicH3VisionAnalyzer,
    "CosmicH3VideoForensics": CosmicH3VideoForensics,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CosmicH3Promptor": "Cosmic MiniMax-H3 Promptor",
    "CosmicH3VisionAnalyzer": "Cosmic MiniMax-H3 Vision Analyzer",
    "CosmicH3VideoForensics": "Cosmic MiniMax-H3 Video Forensics",
}

__all__ = [
    "CosmicH3Promptor",
    "CosmicH3VideoForensics",
    "CosmicH3VisionAnalyzer",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
