import sys
import types
import unittest
from unittest import mock

import torch

sys.modules.setdefault("nodes", types.SimpleNamespace(NODE_CLASS_MAPPINGS={}))
from h3_continuity import refmods  # noqa: E402


class Mod:
    def __init__(self, kind):
        self.kind = kind

    def ref_block(self, strength):
        return {"kind": self.kind, "latent": "z", "strength": strength}


class Vae:
    def __init__(self, frames):
        self.frames = frames

    def decode(self, latent):
        return torch.zeros(1, self.frames, 4, 4, 3)


class PrepareReferencesTest(unittest.TestCase):
    def test_native_helper_wins(self):
        prompt = types.SimpleNamespace(prepare_references=lambda mods, vae: (["native"], []))
        self.assertEqual(refmods.prepare_references(prompt, [], None), (["native"], []))

    def test_fallback_when_backend_lacks_helper(self):
        mods = [(Mod("video"), 1.0), (Mod("image"), 0.0), (Mod("image"), 0.5), (Mod("audio"), 1.0)]
        items, blocks = refmods.prepare_references(types.SimpleNamespace(), mods, Vae(49))
        self.assertEqual([i["type"] for i in items], ["video", "image", "audio"])
        self.assertEqual(len(items[0]["data"]), len(items[0]["timestamps"]))
        self.assertEqual(items[0]["timestamps"][:3], [0.0, 0.5, 1.0])
        self.assertEqual(items[1]["data"].shape[0], 1)
        self.assertNotIn("data", items[2])
        self.assertTrue(all(block["refmod"] for block in blocks))
        self.assertEqual(blocks[1]["strength"], 0.5)

    def test_visual_needs_vae_and_valid_strength(self):
        with self.assertRaisesRegex(ValueError, "video VAE"):
            refmods.prepare_references(types.SimpleNamespace(), [(Mod("video"), 1.0)], None)
        with self.assertRaisesRegex(ValueError, "strength"):
            refmods.prepare_references(types.SimpleNamespace(), [(Mod("audio"), 2.0)], None)
        self.assertEqual(refmods.prepare_references(types.SimpleNamespace(), [(Mod("audio"), 0)], None), ([], []))


if __name__ == "__main__":
    unittest.main()
