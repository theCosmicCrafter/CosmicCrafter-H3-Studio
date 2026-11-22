"""The ComfyUI extension listing the H3 Continuity nodes."""

from comfy_api.latest import ComfyExtension, io

from .nodes import H3C_Continue, H3C_ContinuationModel, H3C_SaveSegment, H3C_Sequence, H3C_SigmasTail
from .story_node import H3C_Story, H3C_StoryTurn
from .timeline_node import H3C_Timeline
from .timeline_images import H3C_TimelineImage
from .ph3_image_nodes import H3C_PH3ImageStill, H3C_PH3StillSize
from .minimax_image_nodes import H3C_MiniMaxH3ImageStill, H3C_MiniMaxPromptCaption
from .still_nodes import H3C_StillRecipe, H3C_StillConditioning, H3C_StillImageSource
from .windows import H3C_ContextWindows, H3C_JoinChain
from .disk_cache import H3C_DiskCache


class H3ContinuityExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [H3C_Sequence, H3C_Continue, H3C_ContinuationModel, H3C_SigmasTail, H3C_SaveSegment, H3C_Timeline, H3C_Story, H3C_StoryTurn, H3C_StillRecipe, H3C_StillConditioning, H3C_StillImageSource, H3C_PH3ImageStill, H3C_TimelineImage,
                H3C_ContextWindows, H3C_JoinChain, H3C_PH3StillSize, H3C_DiskCache, H3C_MiniMaxH3ImageStill,
                H3C_MiniMaxPromptCaption]


async def comfy_entrypoint() -> H3ContinuityExtension:
    return H3ContinuityExtension()
