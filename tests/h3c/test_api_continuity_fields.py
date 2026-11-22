import unittest

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from jsonschema import Draft202012Validator  # noqa: E402

from h3_continuity.timeline_api import contracts  # noqa: E402

LINE = Draft202012Validator(contracts._SCHEMAS["project"]["properties"]["timeline"])
BOX = {"id": "a", "frames": 124, "prompt": "p"}


class ApiContinuityFieldsTest(unittest.TestCase):
    def test_the_new_timeline_fields_are_accepted(self):
        self.assertTrue(LINE.is_valid({"version": 1, "boxes": [BOX], "context_noise": True, "continuation_guide": False,
                                       "audio_feather": 4, "video_slices": ["video1"]}))

    def test_wrong_values_are_refused(self):
        for bad in ({"audio_feather": 17}, {"context_noise": "yes"}, {"video_slices": ["image1"]},
                    {"video_slices": ["video1", "video1"]}):
            with self.subTest(bad=bad):
                self.assertFalse(LINE.is_valid({"version": 1, "boxes": [BOX], **bad}))


if __name__ == "__main__":
    unittest.main()
