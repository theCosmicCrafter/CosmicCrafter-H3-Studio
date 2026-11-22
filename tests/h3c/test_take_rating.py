import json
import os
import tempfile
import unittest

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

from h3_continuity import takes  # noqa: E402


class TakeRatingTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def test_rate_tag_clear_and_keep_others(self):
        takes.mark(self.folder, "2026-11-04T07:30:46", 4, "keeper")
        takes.mark(self.folder, "2026-11-04T07:32:35", 2, "")
        self.assertEqual(takes.marks(self.folder), {"2026-11-04T07:30:46": {"rating": 4, "tag": "keeper"},
                                                    "2026-11-04T07:32:35": {"rating": 2, "tag": ""}})
        takes.mark(self.folder, "2026-11-04T07:32:35", 0, "")
        self.assertEqual(list(takes.marks(self.folder)), ["2026-11-04T07:30:46"])
        with open(os.path.join(self.folder, takes.MARKS), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["version"], 1)

    def test_invalid_marks_fail(self):
        for created, rating, tag in (("", 3, ""), ("x", 6, ""), ("x", True, ""), ("x", 3, "t" * 41), ("x", 3, 5)):
            with self.assertRaises(ValueError):
                takes.mark(self.folder, created, rating, tag)

    def test_a_tag_alone_is_kept(self):
        takes.mark(self.folder, "c", 0, "wide")
        self.assertEqual(takes.marks(self.folder), {"c": {"rating": 0, "tag": "wide"}})

    def test_missing_or_broken_file_reads_as_no_marks(self):
        self.assertEqual(takes.marks(self.folder), {})
        with open(os.path.join(self.folder, takes.MARKS), "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.assertEqual(takes.marks(self.folder), {})

    def test_listed_rows_carry_their_marks(self):
        marks = {"c1": {"rating": 5, "tag": "best"}}
        self.assertEqual(takes._in_use({"created": "c1", "timeline": {"seed": 7}}, marks),
                         {"created": "c1", "seed": 7, "carried_from": None, "rating": 5, "tag": "best"})
        self.assertEqual(takes._in_use({"created": "c2", "timeline": {"seed": 8}}, marks),
                         {"created": "c2", "seed": 8, "carried_from": None, "rating": 0, "tag": ""})
        self.assertEqual(takes._in_use({"created": "c3", "carried_from": "p", "timeline": {}}, {})["carried_from"], "p")


if __name__ == "__main__":
    unittest.main()
