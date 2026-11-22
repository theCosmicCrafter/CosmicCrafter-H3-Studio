"""The agent skill pack: the instruction bundle serves every skill exactly, and the installer links them all."""
import hashlib
import importlib.util
import os
import re
import tempfile
import unittest
from pathlib import Path

from h3_continuity import timeline_prepare

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "skills"
ENTRY = "h3-continuity-video"


def installer():
    spec = importlib.util.spec_from_file_location("install_skills", PACK / "install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SkillPackTest(unittest.TestCase):
    def setUp(self):
        self.names = sorted(path.parent.name for path in PACK.glob("*/SKILL.md"))

    def test_bundle_serves_every_skill_with_the_entry_first(self):
        bundle = timeline_prepare.instructions()
        self.assertEqual([skill["name"] for skill in bundle["skills"]],
                         [ENTRY] + [name for name in self.names if name != ENTRY])
        for skill in bundle["skills"]:
            self.assertEqual(skill["body"], (PACK / skill["name"] / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(bundle["skill"], bundle["skills"][0]["body"])
        content = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
        self.assertEqual(bundle["bundle_sha256"],
                         hashlib.sha256(timeline_prepare.compact(content).encode("utf-8")).hexdigest())

    def test_each_skill_names_itself_and_only_skills_of_the_pack(self):
        for name in self.names:
            text = (PACK / name / "SKILL.md").read_text(encoding="utf-8")
            front = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
            self.assertIsNotNone(front, name)
            self.assertEqual(front.group(1), name)
            for mentioned in set(re.findall(r"`(h3-continuity-[a-z-]+)`", text)):
                self.assertIn(mentioned, self.names, f"{name} names {mentioned}")

    def test_the_entry_lists_every_skill(self):
        entry = (PACK / ENTRY / "SKILL.md").read_text(encoding="utf-8")
        for name in self.names:
            if name != ENTRY:
                self.assertIn(f"| `{name}` |", entry)

    def test_installer_links_the_whole_pack_and_leaves_folders_alone(self):
        module = installer()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            (target / "h3-continuity-api").mkdir()
            first = module.install(target)
            self.assertIn(f"{target / 'h3-continuity-api'}: left alone, it is a folder and not a link", first)
            for name in self.names:
                if name != "h3-continuity-api":
                    self.assertTrue(module.is_link(target / name), name)
                    self.assertEqual((target / name / "SKILL.md").read_text(encoding="utf-8"),
                                     (PACK / name / "SKILL.md").read_text(encoding="utf-8"))
            again = module.install(target)
            self.assertEqual(len([line for line in again if line.endswith("already linked")]), len(self.names) - 1)
            for name in self.names:
                if module.is_link(target / name):
                    (os.rmdir if os.name == "nt" else os.unlink)(target / name)


if __name__ == "__main__":
    unittest.main()
