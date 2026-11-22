"""P-H3-Image (Pruna AI, derived from MiniMax H3) as one ready-to-use still generator.

The node expands into the same native ComfyUI graph as the official workflows
(https://huggingface.co/PrunaAI/P-H3-Image-Comfy), so ComfyUI keeps loading, caching and offloading the models.
"""
import math

import folder_paths
from comfy_api.latest import io
from comfy_execution.graph_utils import GraphBuilder


# Same custom type as still_nodes.StillRecipeType; declared here to keep this module free of that import cycle.
StillRecipeType = io.Custom("H3C_STILL_RECIPE")

UPSTREAM = "https://huggingface.co/PrunaAI/P-H3-Image-Comfy"
SIGMAS = "1.0, 0.984753, 0.967905, 0.951688, 0.925372, 0.881923, 0.810083, 0.528718, 0.0"
MULTIPLE = 32
MIN_SIZE = 256
MAX_REFERENCES = 8
REFERENCE_LABEL = "<Picture {index}>"
MISSING = "(none installed)"
OFF = "off"
STUDIO_RESOLUTIONS = ["8 MP", "4 MP", "custom"]
ASPECTS = {"1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "3:2": 3 / 2, "2:3": 2 / 3, "16:9": 16 / 9, "9:16": 9 / 16}

# input -> (ComfyUI model folder, filename must contain, filename must not contain, what to download)
COMPONENTS = {
    "diffusion_model": ("diffusion_models", "p-h3-image_", ("text_encoder", "upsampler", "vae", "lora"),
                        "diffusion_models/p-h3-image_int8_convrot.safetensors"),
    "text_encoder": ("text_encoders", "p-h3-image_text_encoder", (), "text_encoders/p-h3-image_text_encoder_bf16.safetensors"),
    "vae": ("vae", "p-h3-image_vae", (), "vae/p-h3-image_vae_int8_convrot.safetensors"),
    "prompt_upsampler": ("text_encoders", "p-h3-image_prompt_upsampler", (),
                         "text_encoders/p-h3-image_prompt_upsampler_bf16.safetensors"),
}
LABELS = {"diffusion_model": "diffusion model", "text_encoder": "text encoder", "vae": "VAE",
          "prompt_upsampler": "prompt upsampler"}


def installed(component):
    """P-H3-Image files of one component that ComfyUI can see, including extra_model_paths.yaml folders."""
    folder, contains, excludes, _ = COMPONENTS[component]
    names = []
    for name in folder_paths.get_filename_list(folder):
        base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if contains in base and not any(word in base for word in excludes):
            names.append(name)
    return names


def _missing_message(component):
    folder, _, _, example = COMPONENTS[component]
    return (f"P-H3-Image {LABELS[component]} is missing. Download a p-h3-image {LABELS[component]} file from {UPSTREAM} "
            f"(for example {example}) into ComfyUI/models/{folder} (or a folder listed in extra_model_paths.yaml), "
            f"refresh the node list and select it. The MiniMax H3 video files are not interchangeable.")


def choose(component, name):
    """The selected file, or an error that says what to install."""
    found = installed(component)
    if name in found:
        return name
    if not found or name == MISSING:
        raise ValueError(_missing_message(component))
    raise ValueError(f"P-H3-Image {LABELS[component]} {name!r} is not an installed p-h3-image file. Select one of: "
                     + ", ".join(found) + ".")


def require_core(upsampler=False):
    import nodes
    needed = ["PH3ImageConditioning", "MiniMaxH3SigmaShift"] + (["TextGenerateV2"] if upsampler and
                                                                   "TextGenerateV2" not in nodes.NODE_CLASS_MAPPINGS else [])
    gone = [name for name in needed if name not in nodes.NODE_CLASS_MAPPINGS]
    if upsampler and "TextGenerateV2" in gone and "TextGenerate" in nodes.NODE_CLASS_MAPPINGS:
        gone.remove("TextGenerateV2")
    if gone:
        raise ValueError("This ComfyUI cannot run P-H3-Image: missing core node(s) " + ", ".join(gone)
                         + ". Update ComfyUI to a release that includes P-H3-Image support (comfyanonymous/ComfyUI "
                         "pull 17506, ComfyUI 0.44.0 or newer).")


def aspect_name(width, height):
    ratio = width / height
    return min(ASPECTS, key=lambda name: abs(math.log(ratio / ASPECTS[name])))


def check_size(width, height):
    for label, value in (("width", width), ("height", height)):
        if value < MIN_SIZE or value % MULTIPLE:
            raise ValueError(f"P-H3-Image {label} must be a multiple of {MULTIPLE} and at least {MIN_SIZE}; got {value}.")


class H3C_PH3StillSize(io.ComfyNode):
    """Resolve saved dimension links without loading models or changing the video graph."""
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="H3C_PH3StillSize", display_name="P-H3 Still Size", category="H3 Continuity",
                         inputs=[io.Int.Input("width", force_input=True, min=MIN_SIZE, max=8192),
                                 io.Int.Input("height", force_input=True, min=MIN_SIZE, max=8192),
                                 io.Combo.Input("resolution", options=STUDIO_RESOLUTIONS, default="8 MP", optional=True)],
                         outputs=[io.Int.Output("width"), io.Int.Output("height")])

    @classmethod
    def execute(cls, width, height, resolution="8 MP"):
        check_size(width, height)
        if resolution not in STUDIO_RESOLUTIONS:
            raise ValueError("Unknown P-H3 still resolution: " + str(resolution))
        if resolution == "custom":
            return io.NodeOutput(width, height)
        area = 8388608 if resolution == "8 MP" else 4194304
        scale = min(math.sqrt(area / (width * height)), 8192 / max(width, height))
        return io.NodeOutput(*(max(MIN_SIZE, round(side * scale / MULTIPLE) * MULTIPLE) for side in (width, height)))


def build(*, diffusion_model, text_encoder, vae, prompt, instruction, seed, width, height, images, prompt_upsampler=OFF,
          lora_stack=None):
    """(GraphBuilder, image output) of the official P-H3-Image graph. `images` maps image_N to pixels."""
    references = {name: pixels for name, pixels in sorted(images.items(), key=lambda item: int(item[0].rsplit("_", 1)[-1]))
                  if pixels is not None}
    text = prompt.strip() if not instruction.strip() else prompt.strip() + "\n\n" + instruction.strip()
    g = GraphBuilder()
    unet = g.node("UNETLoader", unet_name=diffusion_model, weight_dtype="default")
    clip = g.node("CLIPLoader", clip_name=text_encoder, type="minimax", device="default")
    model_link, clip_link = unet.out(0), clip.out(0)
    for lora_name, strength_model, strength_clip in lora_stack or []:
        if not lora_name or lora_name == "None" or (strength_model == 0 and strength_clip == 0):
            continue
        lora = g.node("LoraLoader", model=model_link, clip=clip_link, lora_name=lora_name,
                      strength_model=strength_model, strength_clip=strength_clip)
        model_link, clip_link = lora.out(0), lora.out(1)
    model = g.node("MiniMaxH3SigmaShift", model=model_link, shift_video=1.0, shift_audio=1.0)
    vae_node = g.node("VAELoader", vae_name=vae)
    positive_text = text
    if prompt_upsampler != OFF:
        upsampler = g.node("CLIPLoader", clip_name=prompt_upsampler, type="minimax", device="default")
        import nodes
        generate = "TextGenerateV2" if "TextGenerateV2" in nodes.NODE_CLASS_MAPPINGS else "TextGenerate"
        written = g.node(generate, clip=upsampler.out(0), prompt=f"Aspect ratio: {aspect_name(width, height)}\nRequest: {text}",
                         max_length=2048, sampling_mode="off", thinking=True, use_default_template=True, mtp="auto")
        positive_text = written.out(0)
    conditioning = g.node("PH3ImageConditioning", clip=clip_link, vae=vae_node.out(0), prompt=positive_text,
                          width=width, height=height,
                          **{f"images.{name}": pixels for name, pixels in references.items()})
    guider = g.node("BasicGuider", model=model.out(0), conditioning=conditioning.out(0))
    noise = g.node("RandomNoise", noise_seed=seed)
    sampler = g.node("KSamplerSelect", sampler_name="euler")
    sigmas = g.node("ManualSigmas", sigmas=SIGMAS)
    run = g.node("SamplerCustomAdvanced", noise=noise.out(0), guider=guider.out(0), sampler=sampler.out(0),
                 sigmas=sigmas.out(0), latent_image=conditioning.out(1))
    decoded = g.node("VAEDecode", samples=run.out(0), vae=vae_node.out(0))
    return g, decoded.out(0)


def recipe():
    """Self-describing still recipe: the Studio binds this node's own inputs (see web/h3c_stills.mjs)."""
    return {"version": 2, "adapter": "pixels", "generator": "H3C_PH3ImageStill", "label": "P-H3-Image",
            "reference_limit": MAX_REFERENCES, "reference_label": REFERENCE_LABEL}


def _options(component, with_off=False):
    found = installed(component)
    return ([OFF] if with_off else []) + (found or ([] if with_off else [MISSING]))


class H3C_PH3ImageStill(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3C_PH3ImageStill", display_name="P-H3-Image Still", category="H3 Continuity",
            description="Generate Timeline stills with P-H3-Image (Pruna AI, based on MiniMax H3). Select the installed "
                        "p-h3-image files, then connect still_recipe to the Timeline.",
            enable_expand=True,
            inputs=[
                io.Combo.Input("diffusion_model", options=_options("diffusion_model"),
                               tooltip="p-h3-image diffusion model: bf16, int8_convrot or w4a8. From ComfyUI/models/diffusion_models."),
                io.Combo.Input("text_encoder", options=_options("text_encoder"),
                               tooltip="p-h3-image text encoder, from ComfyUI/models/text_encoders."),
                io.Combo.Input("vae", options=_options("vae"), tooltip="p-h3-image VAE, from ComfyUI/models/vae."),
                io.String.Input("prompt", multiline=True, default="",
                                tooltip="The still prompt. The Studio fills this for each First, Last or Shot image."),
                io.String.Input("instruction", multiline=True, default="",
                                tooltip="Text added after every prompt, such as a house style."),
                io.Int.Input("seed", default=0, min=0, max=0xffffffffffffffff),
                io.Int.Input("width", default=3872, min=MIN_SIZE, max=8192, step=MULTIPLE,
                             tooltip="Direct image width. Studio stills use this aspect at 8 MP unless an explicit still size is supplied."),
                io.Int.Input("height", default=2176, min=MIN_SIZE, max=8192, step=MULTIPLE),
                io.Combo.Input("prompt_upsampler", options=_options("prompt_upsampler", with_off=True), default=OFF,
                               tooltip="Off sends the prompt as written, which suits the Studio's prepared still prompts. "
                                       "Choose a p-h3-image prompt upsampler file to expand short requests (extra VRAM and time; "
                                       "not available with reference images yet)."),
                io.Combo.Input("studio_resolution", options=STUDIO_RESOLUTIONS, default="8 MP", optional=True,
                               tooltip="Studio still canvas: 8 MP for detail, 4 MP for less memory, or custom to use width and height exactly. Does not change video size or direct image generation."),
                io.Autogrow.Input("images", optional=True, template=io.Autogrow.TemplateNames(
                    io.Image.Input("image"), names=[f"image_{i}" for i in range(1, MAX_REFERENCES + 1)], min=0),
                    tooltip="Reference images. image_1 is the picture the model edits; the Studio puts the scene first."),
                io.Custom("LORA_STACK").Input("lora_stack", optional=True,
                               tooltip="Optional LoRA stack (for example Easy Use): filename, model strength and CLIP strength. Applied in order to direct images and Studio stills. Use LoRAs compatible with P-H3-Image."),
            ],
            outputs=[io.Image.Output("image"), StillRecipeType.Output("still_recipe")],
        )

    @classmethod
    def execute(cls, diffusion_model, text_encoder, vae, prompt, instruction, seed, width, height,
                prompt_upsampler=OFF, images=None, studio_resolution="8 MP", lora_stack=None) -> io.NodeOutput:
        references = {name: pixels for name, pixels in (images or {}).items() if pixels is not None}
        require_core(prompt_upsampler != OFF)
        files = {"diffusion_model": choose("diffusion_model", diffusion_model),
                 "text_encoder": choose("text_encoder", text_encoder), "vae": choose("vae", vae)}
        if prompt_upsampler != OFF:
            files["prompt_upsampler"] = choose("prompt_upsampler", prompt_upsampler)
        check_size(width, height)
        if len(references) > MAX_REFERENCES:
            raise ValueError(f"P-H3-Image takes at most {MAX_REFERENCES} reference images; got {len(references)}.")
        if references and prompt_upsampler != OFF:
            raise ValueError("The P-H3-Image prompt upsampler does not support reference images yet. Set prompt_upsampler to off.")
        if not prompt.strip():
            raise ValueError("P-H3-Image needs a prompt.")
        g, image = build(**files, prompt=prompt, instruction=instruction, seed=seed, width=width, height=height,
                         images=references, lora_stack=lora_stack)
        return io.NodeOutput(image, recipe(), expand=g.finalize())
