"""A user's own image workflow, bound by the names of its inputs (web/h3c_stills.mjs captureWorkflow)."""
import unittest
from unittest import mock

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

import nodes  # noqa: E402

from h3_continuity import image_recipe, story_context  # noqa: E402


def node_class(required=(), optional=()):
    return type("Node", (), {"INPUT_TYPES": classmethod(lambda cls: {
        "required": {name: (kind,) for name, kind in required}, "optional": {name: (kind,) for name, kind in optional}})})


CLASSES = {
    "Encode": node_class([("text", "STRING")], [("image1", "IMAGE"), ("image2", "IMAGE")]),
    "Scale": node_class([("image", "IMAGE")]),
    "Grow": type("Grow", (), {"INPUT_TYPES": classmethod(lambda cls: {"required": {"prompt": ("STRING",)}, "optional": {"images": (
        "COMFY_AUTOGROW_V3", {"template": {"input": {"required": {"image": ("IMAGE", {})}}, "prefix": "image_", "min": 0, "max": 100}})}})}),
    "MiniMaxH3ImageConditioning": node_class([("prompt", "STRING")], [("image1", "IMAGE"), ("image2", "IMAGE")]),
}


def at(node, input):
    return {"node": node, "input": input}


def recipe(references, size=True, label="image {index}"):
    return {"version": 2, "adapter": "pixels", "auto": True, "label": "Mine", "reference_limit": len(references),
            "reference_label": label, "output": ["9:5", 0],
            "bindings": {"prompt": at("9:3", "text"), "seed": at("9:4", "seed"),
                         "size": {"width": [at("9:4", "width")] if size else [], "height": [at("9:4", "height")] if size else []},
                         "references": references}}


def workflow(encoder="Encode"):
    return {"api": {
        "9:3": {"class_type": encoder, "inputs": {"text" if encoder == "Encode" else "prompt": "old"}},
        "9:2": {"class_type": "Scale", "inputs": {}},
        "9:4": {"class_type": "Sample", "inputs": {"seed": 1, "width": 1024, "height": 576, "steps": 30,
                                                   "positive": ["9:3", 0], "extra": ["9:2", 0]}},
        "9:5": {"class_type": "Decode", "inputs": {"samples": ["9:4", 0]}}}}


def reference(slot, roles, digest):
    return {"slot": slot, "roles": roles, "sha256": digest, "file": {"type": "input", "filename": slot + ".png"}}


def prepare(made, references=(), graph=None, **request):
    body = {"request_id": "r1", "target": {"kind": "first"}, "prompt": "She pours coffee near @image17.", "seed": 42,
            "size": {"width": 1280, "height": 704}, "frame": 0, **request}
    with mock.patch.dict(nodes.NODE_CLASS_MAPPINGS, CLASSES):
        return image_recipe.prepare(made, graph or workflow(), body, list(references))


class StillWorkflowTest(unittest.TestCase):
    def test_the_users_settings_are_left_alone(self):
        result = prepare(recipe([at("9:3", "image1"), at("9:3", "image2")]), [reference("image17", ["image17"], "a" * 64)])
        graph = result["prompt"]
        self.assertEqual((graph["9:4"]["inputs"]["seed"], graph["9:4"]["inputs"]["width"], graph["9:4"]["inputs"]["height"]), (42, 1280, 704))
        self.assertEqual(graph["9:4"]["inputs"]["steps"], 30)
        self.assertEqual(graph["9:3"]["inputs"]["image1"], ["h3c_still_source_0", 0])
        self.assertNotIn("image2", graph["9:3"]["inputs"])
        self.assertIn("image 1", graph["9:3"]["inputs"]["text"])
        self.assertNotIn("@image17", graph["9:3"]["inputs"]["text"])
        self.assertEqual(result["provenance"]["generator"], "Mine")
        self.assertEqual(result["outputs"], ["h3c_still_output"])

    def test_a_workflow_without_size_inputs_keeps_its_own_size(self):
        result = prepare(recipe([], size=False), size=None)
        self.assertEqual((result["prompt"]["9:4"]["inputs"]["width"], result["provenance"]["width"]), (1024, None))
        with self.assertRaisesRegex(ValueError, "no width and height inputs"):
            prepare(recipe([], size=False))

    def test_one_input_feeding_several_nodes_sets_them_all(self):
        port = {**at("9:3", "image1"), "more": [at("9:2", "image")]}
        graph = prepare(recipe([port]), [reference("image17", ["image17"], "a" * 64)])["prompt"]
        self.assertEqual(graph["9:2"]["inputs"]["image"], ["h3c_still_source_0", 0])
        self.assertEqual(graph["9:3"]["inputs"]["image1"], ["h3c_still_source_0", 0])

    def test_an_empty_required_picture_is_reported_before_comfyui_refuses_it(self):
        ports = [at("9:3", "image1"), at("9:2", "image")]
        with self.assertRaisesRegex(ValueError, "needs 2 reference pictures, and this still has 1"):
            prepare(recipe(ports), [reference("image17", ["image17"], "a" * 64)])
        with self.assertRaisesRegex(ValueError, "needs 2 reference pictures, and this still has 0"):
            prepare(recipe(ports), prompt="She pours coffee.")
        # An optional picture input may stay empty.
        prepare(recipe([at("9:3", "image1"), at("9:3", "image2")]), prompt="She pours coffee.")

    def test_native_minimax_nodes_get_the_scene_prompt_without_the_ready_made_node(self):
        made = recipe([at("9:3", "image1"), at("9:3", "image2")], label="<Picture {index}>")
        made["bindings"]["prompt"] = at("9:3", "prompt")
        result = prepare(made, [reference("image17", ["image17", "location: Kitchen"], "a" * 64)], workflow("MiniMaxH3ImageConditioning"))
        text = result["prompt"]["9:3"]["inputs"]["prompt"]
        self.assertIn("<Picture 1>", text)
        self.assertIn("Requested visible state:", text)
        self.assertEqual(result["provenance"]["environment_reference"], "<Picture 1>")
        self.assertNotIn("reference_resize_megapixels", result["provenance"])
        self.assertNotIn("h3c_ph3_size", result["prompt"])

    def test_numbered_autogrow_sockets_are_optional_reference_inputs(self):
        made = recipe([at("9:3", "images.image_0"), at("9:3", "images.image_1")])
        made["bindings"]["prompt"] = at("9:3", "prompt")
        graph = prepare(made, [reference("image17", ["image17"], "a" * 64)], workflow("Grow"))["prompt"]
        self.assertEqual(graph["9:3"]["inputs"]["images.image_0"], ["h3c_still_source_0", 0])
        made["bindings"]["references"] = [at("9:3", "images.other_0")]
        with self.assertRaisesRegex(ValueError, "must be a native IMAGE input"):
            prepare(made, graph=workflow("Grow"))

    def test_story_recognises_a_connected_workflow_and_its_native_model(self):
        prompt = {"1": {"class_type": "H3C_Timeline", "inputs": {"still_image": ["9:5", 0]}}, **workflow("MiniMaxH3ImageConditioning")["api"]}
        self.assertEqual(story_context.renderer_for(prompt, "1"), "image")
        self.assertEqual(story_context.still_model_for(prompt, "1"), "MiniMax H3 Image")
        self.assertEqual(story_context.still_model_for({"1": prompt["1"], **workflow()["api"]}, "1"), "")
        self.assertEqual(story_context.renderer_for({"1": {"class_type": "H3C_Timeline", "inputs": {}}}, "1"), "video")


if __name__ == "__main__":
    unittest.main()
