import json
import re
import unittest
from pathlib import Path
from h3c_mcp.tools import StudioTools

ROOT = Path(__file__).resolve().parents[2]


class DocumentationTest(unittest.TestCase):
    def test_published_installation_and_all_guidance_references_resolve(self):
        guide = ROOT / 'guide/automation/mcp.md'
        reference = ROOT / 'docs/MCP.md'
        self.assertTrue(guide.is_file(), 'Installation must be published in the guide')
        self.assertTrue(reference.is_file(), 'Host must serve a complete MCP operation reference')
        tools = {name for name in dir(StudioTools) if name.startswith('h3_')}
        coverage = json.loads((ROOT / 'h3_continuity/agent_api/coverage.json').read_text())
        for feature in coverage['features'].values():
            self.assertTrue(set(feature['tools']) <= tools)
        texts = [path.read_text(encoding='utf-8') for path in (ROOT / 'skills').glob('*/SKILL.md')]
        texts.extend(path.read_text(encoding='utf-8') for path in (guide, reference))
        for text in texts:
            for name in re.findall(r'`(h3_[a-z_]+)`', text):
                self.assertIn(name, tools)
            for directory, filename in re.findall(r'h3c://(docs|examples)/([A-Za-z0-9_][A-Za-z0-9_.-]*)', text):
                self.assertTrue((ROOT / directory / filename).is_file(), filename)
