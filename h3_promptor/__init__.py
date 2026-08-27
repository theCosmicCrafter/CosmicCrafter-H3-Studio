from .h3_promptor import H3_Promptor
from .h3_vision_analyzer import H3_Vision_Analyzer
from .dynamic_discovery import init_routes

init_routes()

NODE_CLASS_MAPPINGS = {
    "H3_Promptor": H3_Promptor,
    "H3_Vision_Analyzer": H3_Vision_Analyzer,
    "CosmicH3Promptor": H3_Promptor,
    "CosmicH3VisionAnalyzer": H3_Vision_Analyzer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "H3_Promptor": "Cosmic MiniMax-H3 Promptor (Dynamic LLM)",
    "H3_Vision_Analyzer": "Cosmic MiniMax-H3 Vision Analyzer (Dynamic VLM)",
    "CosmicH3Promptor": "Cosmic MiniMax-H3 Promptor",
    "CosmicH3VisionAnalyzer": "Cosmic MiniMax-H3 Vision Analyzer",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
