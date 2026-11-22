import json
import os
import subprocess
import sys
import tempfile
import unittest

from tests.support import FixtureStudio


class CLITest(unittest.TestCase):
    def test_diagnostic_launcher_works_outside_the_checkout(self):
        host = FixtureStudio()
        self.addCleanup(host.close)
        host.routes[('GET', '/h3c/agent/catalog')] = (200, {'agent_api_version': 1, 'skills': [{}]})
        host.routes[('GET', '/h3c/api/v1/capabilities')] = (200, {'profiles': [], 'readiness': {'render': False}})
        with tempfile.TemporaryDirectory(prefix='h3c path with spaces ') as directory:
            result = subprocess.run([sys.executable, '-m', 'h3c_mcp', '--studio-url', host.url, '--check'],
                                    cwd=directory, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['skills'], 1)
        self.assertEqual(result.stderr, '')

    def test_one_tool_call_runs_without_an_mcp_client(self):
        host = FixtureStudio()
        self.addCleanup(host.close)
        host.routes[('POST', '/h3c/agent/projects/read')] = (200, {'revision': {'state': 1}, 'unsupported_features': ['scène-map-1 😀']})
        target = {'kind': 'native', 'graph': 'g', 'timeline_node': '2'}
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'arguments.json')
            with open(path, 'w', encoding='utf-8') as stream:
                json.dump({'target': target}, stream)
            for source, stdin in ((json.dumps({'target': target}), None), ('@' + path, None), ('-', json.dumps({'target': target}))):
                with self.subTest(source=source[:1]):
                    result = subprocess.run([sys.executable, '-m', 'h3c_mcp', '--studio-url', host.url, '--state-dir', directory,
                                             '--call', 'h3_get_project', '--arguments', source], input=stdin, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), {'revision': {'state': 1}, 'unsupported_features': ['scène-map-1 😀']})
        self.assertEqual(json.loads(host.requests[-1]['body']), {'target': target})

    def test_one_tool_call_reports_errors_as_json(self):
        host = FixtureStudio()
        self.addCleanup(host.close)
        for arguments in (['--call', 'h3_missing'], ['--call', 'h3_get_project', '--arguments', '{"target":{"kind":"native"}}'],
                          ['--call', 'h3_get_project', '--arguments', '[1]'], ['--arguments', '{}']):
            with self.subTest(arguments=arguments):
                result = subprocess.run([sys.executable, '-m', 'h3c_mcp', '--studio-url', host.url, *arguments], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1 if '--call' in arguments else 2, result.stderr)
                if '--call' in arguments:
                    self.assertFalse(json.loads(result.stderr)['ok'])
        self.assertEqual(host.requests, [])

    def test_import_and_help_require_no_host_dependencies(self):
        result = subprocess.run([sys.executable, '-c', "import sys,h3c_mcp; assert 'torch' not in sys.modules; assert 'folder_paths' not in sys.modules"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, '-m', 'h3c_mcp', '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--studio-url', result.stdout)
