"""The P-H3-Image node runs only when a still is requested, never for a Timeline video.

These tests run ComfyUI's real scheduler on the CPU with stand-ins for the model nodes, so they load nothing.
"""
import asyncio
import types
import unittest
from unittest import mock

import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

import execution  # noqa: E402
import folder_paths  # noqa: E402
import nodes  # noqa: E402
from comfy_api.latest import io  # noqa: E402

from h3_continuity import ph3_image_nodes as ph3  # noqa: E402

RAN = []
SEEN = {}
FILES = {"diffusion_models": ["p-h3-image_int8_convrot.safetensors"],
         "text_encoders": ["p-h3-image_text_encoder_bf16.safetensors"], "vae": ["p-h3-image_vae_int8_convrot.safetensors"]}


def stand_in(name, returns, takes=None, accepts=()):
    """A legacy node class named like a native one that records that it ran."""
    def call(self, **inputs):
        RAN.append(name)
        SEEN[name] = inputs
        return returns(inputs) if callable(returns) else returns
    return type(name, (), {
        "INPUT_TYPES": classmethod(lambda cls: {"required": {}, "optional": {key: ("*",) for key in accepts}}),
        "RETURN_TYPES": tuple(takes or ()), "FUNCTION": "go", "CATEGORY": "test", "go": call})


class Timeline(io.ComfyNode):
    """Declares still_recipe exactly like H3C_Timeline does, and is the video output."""
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="PH3TestTimeline", is_output_node=True,
                         inputs=[ph3.StillRecipeType.Input("still_recipe", optional=True, raw_link=True, lazy=True)], outputs=[])

    @classmethod
    def check_lazy_status(cls, **kwargs):
        return []

    @classmethod
    def execute(cls, still_recipe=None):
        RAN.append("timeline")
        SEEN["timeline"] = still_recipe
        return io.NodeOutput()


class Preview(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(node_id="PH3TestPreview", is_output_node=True, inputs=[io.Image.Input("image")], outputs=[])

    @classmethod
    def execute(cls, image):
        RAN.append("preview")
        SEEN["preview"] = image
        return io.NodeOutput()


def stand_ins():
    image = torch.zeros(1, 8, 8, 3)
    table = {
        "UNETLoader": (("MODEL",), lambda i: ("model",)),
        "MiniMaxH3SigmaShift": (("MODEL",), lambda i: ("shifted",)),
        "CLIPLoader": (("CLIP",), lambda i: ("clip",)),
        "VAELoader": (("VAE",), lambda i: ("vae",)),
        "PH3ImageConditioning": (("CONDITIONING", "LATENT"), lambda i: ("cond", "latent")),
        "BasicGuider": (("GUIDER",), lambda i: ("guider",)),
        "RandomNoise": (("NOISE",), lambda i: ("noise",)),
        "KSamplerSelect": (("SAMPLER",), lambda i: ("sampler",)),
        "ManualSigmas": (("SIGMAS",), lambda i: ("sigmas",)),
        "SamplerCustomAdvanced": (("LATENT", "LATENT"), lambda i: ("out", "out")),
        "VAEDecode": (("IMAGE",), lambda i: (image,)),
    }
    with mock.patch("nodes.NODE_CLASS_MAPPINGS", {"PH3ImageConditioning": object, "MiniMaxH3SigmaShift": object}):
        graph, _ = ph3.build(diffusion_model="a", text_encoder="b", vae="c", prompt="p", instruction="", seed=1, width=64,
                             height=64, images={"image_1": image}, prompt_upsampler="off")
    names = {}
    for node in graph.finalize().values():
        names.setdefault(node["class_type"], set()).update(node["inputs"])
    return {name: stand_in(name, result, outputs, sorted(names[name])) for name, (outputs, result) in table.items()}


def prompt_with(**inputs):
    node = {"class_type": "H3C_PH3ImageStill",
            "inputs": {"diffusion_model": "p-h3-image_int8_convrot.safetensors",
                       "text_encoder": "p-h3-image_text_encoder_bf16.safetensors",
                       "vae": "p-h3-image_vae_int8_convrot.safetensors", "prompt": "A kitchen at dawn.", "instruction": "",
                       "seed": 3, "width": 1024, "height": 576, "prompt_upsampler": "off", **inputs}}
    return {"1": node}


def execute(prompt, outputs):
    async def go():
        server = types.SimpleNamespace(client_id=None, last_node_id=None, last_prompt_id=None,
                                       send_sync=lambda *a, **k: None, prompt_queue=None)
        executor = execution.PromptExecutor(server, cache_type=execution.CacheType.CLASSIC,
                                            cache_args={"ram": 8, "ram_inactive": 8, "lru": 0})
        valid = await execution.validate_prompt("test", prompt, None)
        assert valid[0], valid
        await executor.execute_async(prompt, "test", {}, outputs)
        return executor.success
    return asyncio.run(go())


class OnDemandTest(unittest.TestCase):
    def setUp(self):
        RAN.clear()
        SEEN.clear()
        patches = [mock.patch.dict(nodes.NODE_CLASS_MAPPINGS, {**stand_ins(), "H3C_PH3ImageStill": ph3.H3C_PH3ImageStill,
                                                               "PH3TestTimeline": Timeline, "PH3TestPreview": Preview}),
                   mock.patch.object(folder_paths, "get_filename_list", lambda folder: list(FILES.get(folder, [])))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_timeline_video_run_executes_no_part_of_the_generator(self):
        prompt = {**prompt_with(), "2": {"class_type": "PH3TestTimeline", "inputs": {"still_recipe": ["1", 1]}}}
        self.assertTrue(execute(prompt, ["2"]))
        self.assertEqual(RAN, ["timeline"])
        self.assertEqual(SEEN["timeline"], ["1", 1])

    def test_a_still_request_runs_the_official_graph_and_returns_the_decoded_image(self):
        prompt = {**prompt_with(), "2": {"class_type": "PH3TestPreview", "inputs": {"image": ["1", 0]}}}
        self.assertTrue(execute(prompt, ["2"]))
        for name in ("UNETLoader", "MiniMaxH3SigmaShift", "CLIPLoader", "VAELoader", "PH3ImageConditioning", "BasicGuider",
                     "SamplerCustomAdvanced", "VAEDecode", "preview"):
            self.assertIn(name, RAN)
        self.assertEqual(SEEN["PH3ImageConditioning"]["prompt"], "A kitchen at dawn.")
        self.assertEqual((SEEN["PH3ImageConditioning"]["width"], SEEN["PH3ImageConditioning"]["height"]), (1024, 576))
        self.assertEqual(SEEN["RandomNoise"]["noise_seed"], 3)
        self.assertEqual(tuple(SEEN["preview"].shape), (1, 8, 8, 3))

    def test_a_reference_image_reaches_the_conditioning_unchanged(self):
        source = torch.ones(1, 4, 4, 3)
        loader = stand_in("PH3TestLoad", (source,), ("IMAGE",))
        with mock.patch.dict(nodes.NODE_CLASS_MAPPINGS, {"PH3TestLoad": loader}):
            prompt = {**prompt_with(**{"images.image_1": ["3", 0]}), "3": {"class_type": "PH3TestLoad", "inputs": {}},
                      "2": {"class_type": "PH3TestPreview", "inputs": {"image": ["1", 0]}}}
            self.assertTrue(execute(prompt, ["2"]))
        self.assertTrue(torch.equal(SEEN["PH3ImageConditioning"]["images.image_1"], source))

    def test_studio_size_node_resolves_real_links_before_the_expanded_sampler(self):
        size = stand_in('PH3TestVideoSize', (736, 992), ('INT', 'INT'))
        with mock.patch.dict(nodes.NODE_CLASS_MAPPINGS, {'H3C_PH3StillSize': ph3.H3C_PH3StillSize, 'PH3TestVideoSize': size}):
            prompt = {**prompt_with(width=['size', 0], height=['size', 1]),
                      'size': {'class_type':'H3C_PH3StillSize', 'inputs':{'width':['video',0], 'height':['video',1]}},
                      'video': {'class_type':'PH3TestVideoSize', 'inputs':{}},
                      '2': {'class_type':'PH3TestPreview', 'inputs':{'image':['1',0]}}}
            self.assertTrue(execute(prompt, ['2']))
        self.assertEqual((SEEN['PH3ImageConditioning']['width'], SEEN['PH3ImageConditioning']['height']), (2496, 3360))

    def test_a_timeline_video_run_still_validates_and_runs_without_any_p_h3_image_files(self):
        video = {**prompt_with(vae=ph3.MISSING, diffusion_model=ph3.MISSING, text_encoder=ph3.MISSING),
                 "3": {"class_type": "PH3TestTimeline", "inputs": {"still_recipe": ["1", 1]}}}
        with mock.patch.dict(FILES, {"diffusion_models": [], "text_encoders": [], "vae": []}):
            self.assertTrue(execute(video, ["3"]))
        self.assertEqual(RAN, ["timeline"])


if __name__ == "__main__":
    unittest.main()
