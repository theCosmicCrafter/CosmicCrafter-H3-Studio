"""Fixture-only launcher/client smoke. No model turns, live Studio, or global config writes.

uv run --project mcp_adapter python tools/mcp_client_smoke.py [--clients]
"""
import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mcp_adapter'))
from tests.support import FixtureStudio


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{command[0]} failed: {result.stderr[-2000:]}')
    return result.stdout


def codex_check(launcher, arguments, cwd):
    config = '{command=' + json.dumps(str(launcher)) + ',args=' + json.dumps(arguments) + ',startup_timeout_sec=30}'
    process = subprocess.Popen(['codex', 'app-server', '-c', 'mcp_servers={}', '-c', 'plugins={}',
        '-c', 'mcp_servers.h3c_fixture=' + config], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, cwd=cwd)
    messages = queue.Queue()
    def read():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
    threading.Thread(target=read, daemon=True).start()
    def send(value):
        process.stdin.write(json.dumps(value) + '\n')
        process.stdin.flush()
    def reply(identity):
        while True:
            message = messages.get(timeout=60)
            if message.get('id') == identity:
                if 'error' in message:
                    raise RuntimeError(str(message['error']))
                return message['result']
    try:
        send(dict(id=1, method='initialize', params=dict(clientInfo=dict(name='h3c_fixture_smoke', version='1'), capabilities=dict(experimentalApi=True))))
        reply(1)
        send(dict(method='initialized'))
        send(dict(id=2, method='mcpServerStatus/list', params=dict(serverName='h3c_fixture', detail='full')))
        result = reply(2)
        server = next(row for row in result['data'] if row['name'] == 'h3c_fixture')
        tools = server.get('tools', {})
        if 'h3_get_project' not in tools or server.get('toolsError'):
            raise RuntimeError('Codex did not discover the fixture tool catalog: ' + str(server.get('toolsError')))
        return dict(version=run(['codex', '--version']).strip(), tools=len(tools), resources=len(server.get('resources', [])),
                    server_capabilities=server.get('serverCapabilities'), automatic_skills_activation='not_verified')
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clients', action='store_true', help='Also exercise installed Codex and Claude Code without model turns')
    args = parser.parse_args()
    host = FixtureStudio()
    host.guidance()
    try:
        with tempfile.TemporaryDirectory(prefix='h3c installation with spaces ') as directory:
            root = Path(directory)
            project = root / 'Continuity Studio' / 'mcp_adapter'
            shutil.copytree(ROOT / 'mcp_adapter', project, ignore=shutil.ignore_patterns('.venv', '__pycache__', '*.egg-info', 'dist', 'build'))
            flags = ['--studio-url', host.url, '--workspace-root', str(root), '--state-dir', str(root / 'receipts')]
            uv_check = json.loads(run(['uv', 'run', '--project', str(project), 'h3c-mcp', *flags, '--check'], cwd=root))
            wheel_dir = root / 'wheel'
            run(['uv', 'build', '--wheel', '--out-dir', str(wheel_dir), str(project)], cwd=root)
            environment = root / 'isolated venv'
            run(['uv', 'venv', '--python', sys.executable, str(environment)], cwd=root)
            binaries = environment / ('Scripts' if os.name == 'nt' else 'bin')
            python = binaries / ('python.exe' if os.name == 'nt' else 'python')
            launcher = binaries / ('h3c-mcp.exe' if os.name == 'nt' else 'h3c-mcp')
            run(['uv', 'pip', 'install', '--python', str(python), str(next(wheel_dir.glob('*.whl')))], cwd=root)
            wheel_check = json.loads(run([str(launcher), *flags, '--check'], cwd=root))
            run([str(python), '-c', "import sys,h3c_mcp; assert 'torch' not in sys.modules and 'folder_paths' not in sys.modules"], cwd=root)
            evidence = dict(uv_launcher=uv_check, isolated_wheel_launcher=wheel_check, paths_contain_spaces=True, working_directory_outside_checkout=True)
            if args.clients:
                evidence['codex'] = codex_check(launcher, flags, root)
                env = {**os.environ, 'CLAUDE_CONFIG_DIR': str(root / 'claude config')}
                run(['claude', 'mcp', 'add', '--transport', 'stdio', '--scope', 'user', 'h3c_fixture', '--', str(launcher), *flags], cwd=root, env=env)
                status = run(['claude', 'mcp', 'list'], cwd=root, env=env)
                run(['claude', 'mcp', 'get', 'h3c_fixture'], cwd=root, env=env)
                if 'Connected' not in status:
                    raise RuntimeError('Claude fixture health check failed: ' + status[-1000:])
                evidence['claude'] = dict(version=run(['claude', '--version']).strip(), health='connected', automatic_skills_activation='not_verified')
            print(json.dumps(evidence, indent=2))
    finally:
        host.close()


if __name__ == '__main__':
    main()
