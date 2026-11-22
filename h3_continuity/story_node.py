"""H3 Story: plans a linked H3 Timeline's story and writes its box prompts with a model on any OpenAI-compatible
API. The panel's Write button does the work on the server; the node itself never runs in a queued prompt, only the
turn Write queues while it uses a model on this PC."""

from comfy_api.latest import io

from . import nodes as continuity
from . import story_lengths, story_vram
from . import timeline as rules

StoryType = io.Custom("H3C_STORY")
SCOPES = ["empty boxes", "every unrendered box"]
LINKS = "Text, Custom Combo or any other nodes; Write runs those that need it in ComfyUI's queue first."
THINKING = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]
WRITING_MODES = ["fast", "reviewed (slow)", "guide checked (fast)", "guide enforced (experimental)"]


class H3C_Story(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_Story",
            display_name="H3 Story",
            category=continuity.CATEGORY,
            description="Type an idea and press Write: a model on any OpenAI-compatible API plans the story and "
                        "writes the prompts of the linked H3 Timeline's boxes, and on an empty Timeline plans the "
                        "boxes too. Link story to the Timeline's story input; renders never wait for this node.",
            inputs=[
                io.String.Input("idea", default="", multiline=True, tooltip="The raw idea for the whole Timeline."),
                io.String.Input("guide", optional=True, force_input=True,
                                tooltip=f"Creative requirements checked against the final prompts. Write attempts "
                                        f"corrections and keeps unresolved output as drafts. "
                                        f"Link {LINKS}"),
                io.Autogrow.Input("descriptions", optional=True,
                                  template=io.Autogrow.TemplateNames(io.String.Input("description"),
                                                                     names=rules.AUDIO_SLOTS + rules.VIDEO_SLOTS + rules.VIDEO_AUDIO_SLOTS, min=0),
                                  tooltip="Describe Timeline audio or video: video1 describes its motion; "
                                          "video_audio1 describes that video's soundtrack; audio1 describes @audio1. "
                                          "Image descriptions come from RefMods, Vision or the Timeline editor."),
                io.String.Input("base_url", default="https://api.openai.com/v1", advanced=True, display_name="Box API URL",
                                tooltip="OpenAI-compatible API for box prompts and revisions, such as "
                                        "http://localhost:1234/v1 for LM Studio. Also used for the initial story "
                                        "when Story API URL is empty. Keys are saved by host. "
                                        f"Type it, or link {LINKS}"),
                io.String.Input("model", default="", advanced=True, display_name="Box writing model",
                                tooltip="Model ID for box prompts and revisions. Creative writing or roleplay models "
                                        "can work well for vivid action, dialogue and character performance; choose "
                                        "one that follows structured output instructions. Used for the initial story "
                                        f"too when Initial story model is empty. Type it, or link {LINKS}"),
                io.Boolean.Input("pictures", default=True,
                                 tooltip="Send pictures to the writing model and let it describe missing image references. "
                                         "When off, a configured Vision model supplies descriptions instead."),
                io.Combo.Input("scope", options=SCOPES, default=SCOPES[0],
                               tooltip="Write only empty boxes, or also boxes that still hold what Write wrote."),
                io.String.Input("state", default="{}", multiline=True, tooltip="The last Write, kept by the panel."),
                io.Boolean.Input("free_vram", default=True, advanced=True,
                                 tooltip="When the model server runs on this PC, Write takes a turn in ComfyUI's "
                                         "queue: it waits for the prompts queued before it, moves ComfyUI's models "
                                         "out of VRAM, keeps later prompts waiting while the model writes, and "
                                         "unloads the model before they run. Turn it off if your GPU fits both."),
                io.Int.Input("total_seconds", default=0, min=0, max=story_lengths.MAX_TOTAL_SECONDS, step=1,
                             tooltip="How long the story runs when Write plans the boxes of an empty Timeline. 0 lets "
                                     f"the model choose, up to {story_lengths.AUTO_MAX_SECONDS} s."),
                io.Combo.Input("thinking", options=THINKING, default="medium", advanced=True,
                               tooltip="Reasoning effort for writing box prompts and revisions. Off sends none. "
                                       "Try off or low for creative/roleplay models; increase it when the model "
                                       "needs help following the plan. Supported levels depend on the model."),
                io.Combo.Input("writing_mode", options=WRITING_MODES, default=WRITING_MODES[0],
                               tooltip="Retired. Every Write uses Fast; this setting is kept only so saved workflows "
                                       "still load."),
                io.String.Input("vision_base_url", default="", advanced=True,
                                tooltip="OpenAI-compatible Vision API URL. Empty uses base_url. Keys are saved by host."),
                io.String.Input("vision_model", default="", advanced=True,
                                tooltip="Describes references when Send pictures is off; checks also use this model. "
                                        "Empty disables separate Vision."),
                io.String.Input("template", default="", advanced=True,
                                tooltip="The template Write follows, chosen on the Studio's Story page. Empty writes "
                                        "without one."),
                io.Combo.Input("story_thinking", options=["same as boxes", *THINKING], default="same as boxes",
                               advanced=True, tooltip="Reasoning effort for the initial story plan and writer image "
                                                      "descriptions. Higher effort can help with complex plots, "
                                                      "pacing and continuity. Same as boxes uses Box writing thinking. "
                                                      "Supported levels depend on the initial story model."),
                io.String.Input("idea_images", default="[]", optional=True, advanced=True,
                                tooltip="Idea images added on the Studio's Story page. Creative context for the "
                                        "writer or Vision model; these do not occupy Timeline reference slots."),
                io.String.Input("story_model", default="", optional=True, advanced=True,
                                display_name="Initial story model",
                                tooltip="Model ID for the initial story plan and writer image descriptions. Prefer "
                                        "a strong planning/reasoning model for plot, pacing and continuity. Empty "
                                        "uses Box writing model. Uses Story API URL; enable image support "
                                        f"when Send pictures is on. Type it, or link {LINKS}"),
                io.String.Input("story_base_url", default="", optional=True, advanced=True,
                                display_name="Story API URL",
                                tooltip="OpenAI-compatible API for the initial story plan and writer image "
                                        "descriptions. Empty uses Box API URL. Set a different URL to use another "
                                        f"provider; keys are saved separately by host. Type it, or link {LINKS}"),
            ],
            outputs=[StoryType.Output(display_name="story")],
        )

    @classmethod
    def execute(cls, idea, base_url, model, pictures, scope, state, free_vram=True, total_seconds=0,
                thinking="medium", guide=None, descriptions=None, writing_mode=WRITING_MODES[0],
                vision_base_url="", vision_model="", template="", story_thinking="same as boxes",
                idea_images="[]", story_model="", story_base_url="") -> io.NodeOutput:
        return io.NodeOutput(None)


class H3C_StoryTurn(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id=story_vram.TURN,
            display_name="H3 Story turn",
            category=continuity.CATEGORY,
            description="Holds ComfyUI's queue while H3 Story writes with a model on this PC. Write queues it; cancel "
                        "it to stop that Write.",
            inputs=[io.String.Input("write")],
            is_output_node=True,
            is_dev_only=True,
        )

    @classmethod
    async def execute(cls, write) -> io.NodeOutput:
        await story_vram.hold(write)
        return io.NodeOutput()
