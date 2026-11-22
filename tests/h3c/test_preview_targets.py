import copy
import json
import unittest

from h3_continuity import timeline


def parse(previews):
    return timeline.parse(json.dumps({'version': 1, 'boxes': [
        {'id': 'a', 'frames': 22, 'prompt': 'Keep this prompt', 'previews': previews}]})).boxes[0].previews


class PreviewTargetsTest(unittest.TestCase):
    def test_identical_endpoint_records_are_one_preview_without_losing_metadata(self):
        for target in ({'kind': 'first'}, {'kind': 'last'}, {'kind': 'shot', 'shot': 2}):
            item = {'target': target, 'frame': 0, 'still_source': None, 'still_prompt': 'Exact still wording',
                    'images': [{'file': {'filename': 'candidate.png', 'subfolder': 'h3_previews', 'type': 'output'}}]}
            self.assertEqual(parse([item, copy.deepcopy(item)]), [item])

    def test_shot_one_alias_is_canonicalized_before_comparing_identical_records(self):
        self.assertEqual(parse([{'target': {'kind': 'shot', 'shot': 1}, 'frame': 0},
                                {'target': {'kind': 'first'}, 'frame': 0}]),
                         [{'target': {'kind': 'first'}, 'frame': 0}])

    def test_different_records_for_one_target_are_still_rejected(self):
        first = {'target': {'kind': 'first'}, 'frame': 0, 'still_source': None}
        for difference in ({'frame': 1}, {'still_prompt': 'Different'}, {'still_source': {'box': 'other'}},
                           {'images': []}):
            with self.subTest(difference=difference), self.assertRaisesRegex(ValueError, 'unique targets'):
                parse([first, {**first, **difference}])

    def test_duplicate_records_cannot_skip_frame_validation(self):
        with self.assertRaisesRegex(ValueError, 'preview frame must be a whole number'):
            parse([{'target': {'kind': 'first'}, 'frame': 0}, {'target': {'kind': 'first'}, 'frame': False}])

    def test_nested_candidate_types_are_not_treated_as_identical_payloads(self):
        for left, right in ((0, False), (1, True), (1, 1.0)):
            image = {'file': {'filename': 'candidate.png', 'subfolder': 'h3_previews', 'type': 'output'}}
            a = {'target': {'kind': 'first'}, 'frame': 0, 'images': [{**image, 'seed': left}]}
            b = {**a, 'images': [{**image, 'seed': right}]}
            with self.subTest(left=left, right=right), self.assertRaisesRegex(ValueError, 'unique targets'):
                parse([a, b])

    def test_legacy_shot_duplicates_are_still_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unique positive shot numbers'):
            parse([{'shot': 1, 'frame': 0}, {'shot': 1, 'frame': 0}])
