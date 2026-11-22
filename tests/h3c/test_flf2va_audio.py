import json
import unittest
from unittest import mock

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from comfy_extras import nodes_minimax_h3  # noqa: E402
from h3_continuity import frame_refmods, refmods, timeline  # noqa: E402

VOICE = {"slot": "audio2", "name": "voice", "member": -1, "kind": "audio", "strength": 1}


def slots(prompt, **keys):
    box = {"id": "a", "frames": 107, "seed": 1, "prompt": prompt, "first": "image1", "flf_refmods": True}
    return timeline.box_slots(timeline.parse(json.dumps({"version": 1, "boxes": [box], **keys})), 0)


class SlotsTest(unittest.TestCase):
    def test_raw_audio_keeps_flf2va_and_numbers_before_audio_refmods(self):
        result = slots("@image3 sings @audio1 in @audio2's voice.", refmods=[VOICE])
        self.assertEqual(result.mode, "flf2va")
        self.assertEqual(result.audio_inputs, ["audio1"])
        self.assertEqual(result.audios, ["audio1", "audio2"])
        self.assertEqual((result.tags["audio1"], result.tags["audio2"]), ("<Audio 1>", "<Audio 2>"))

    def test_raw_video_still_needs_ref2va(self):
        self.assertEqual(slots("@image3 dances like @video1.").mode, "ref2va")


class PrepareTest(unittest.TestCase):
    def test_raw_audio_blocks_sit_between_cached_images_and_refmods(self):
        self.assertTrue(callable(nodes_minimax_h3._encode_ref_audio))

        class Prompt:
            @staticmethod
            def prepare_references(mods, vae):
                return [{"type": kind} for kind, _ in mods], [{"kind": kind} for kind, _ in mods]

        with mock.patch.object(refmods, "backend", return_value=(None, Prompt)), \
                mock.patch.object(frame_refmods, "cached_image", return_value=("image", 1.0)), \
                mock.patch.object(refmods, "load", return_value=[("audio", 1.0)]), \
                mock.patch.object(refmods, "ReferenceClip", side_effect=lambda clip, items: items), \
                mock.patch.object(nodes_minimax_h3, "_encode_ref_audio", return_value=("z", 7)):
            items, blocks = frame_refmods.prepare("clip", "vae", ["first", "image3"], [VOICE], ["audio1"], "audio vae")
        self.assertEqual([item["type"] for item in items], ["image", "image", "audio", "audio"])
        self.assertEqual(blocks[2], {"kind": "audio", "ref_audio_t": 7, "audio_latent": "z"})
        self.assertEqual(blocks[3], {"kind": "audio"})

    def test_raw_audio_needs_the_audio_vae(self):
        with mock.patch.object(refmods, "backend", return_value=(None, mock.Mock(prepare_references=lambda m, v: ([], [])))), \
                mock.patch.object(refmods, "load", return_value=[]):
            with self.assertRaisesRegex(ValueError, "audio VAE"):
                frame_refmods.prepare("clip", "vae", [], [], ["audio1"], None)


if __name__ == "__main__":
    unittest.main()
