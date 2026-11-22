import argparse
import json
import os
import sys
from pathlib import Path

from .transport import StudioClient, StudioError


def _call(client, state_dir, name, source):
    from pydantic import validate_call
    from .guidance import Guidance
    from .tools import StudioTools
    if not name.startswith('h3_') or not callable(getattr(StudioTools, name, None)):
        raise StudioError(f'Unknown tool {name}.', code='unknown_tool')
    text = sys.stdin.read() if source == '-' else Path(source[1:]).read_text(encoding='utf-8') if source.startswith('@') else source
    arguments = json.loads(text)
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be a JSON object.')
    # The same argument validation MCP clients get, so Target and revision objects arrive as models.
    return validate_call(getattr(StudioTools(client, Guidance(client), state_dir), name))(**arguments)


def main():
    parser = argparse.ArgumentParser(description='Connect an MCP agent to a local or remote H3 Continuity Studio.')
    parser.add_argument('--studio-url', default=os.environ.get('H3C_STUDIO_URL', 'http://127.0.0.1:8188'))
    parser.add_argument('--token-env', default='H3C_STUDIO_TOKEN', help='Environment variable containing the optional proxy bearer token')
    parser.add_argument('--workspace-root', action='append', type=Path, help='Allowed local file root (repeatable; default current directory)')
    default_state = Path(os.environ.get('LOCALAPPDATA', os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state')))) / 'h3c-mcp'
    parser.add_argument('--state-dir', type=Path, default=default_state)
    parser.add_argument('--check', action='store_true', help='Check the host without starting MCP or changing project data')
    parser.add_argument('--call', metavar='TOOL', help='Run one tool (e.g. h3_get_project) without an MCP client and print its JSON result')
    parser.add_argument('--arguments', metavar='JSON', help='Tool arguments for --call: a JSON object (default {}), @file or - for stdin')
    args = parser.parse_args()
    if args.arguments is not None and not args.call:
        parser.error('--arguments needs --call')
    client = None
    try:
        client = StudioClient(args.studio_url, token=os.environ.get(args.token_env), roots=args.workspace_root)
        if args.call:
            print(json.dumps(_call(client, args.state_dir, args.call, args.arguments or '{}')))
        elif args.check:
            catalog = client.json('/h3c/agent/catalog')
            if catalog.get('agent_api_version') != 1:
                raise StudioError('Update the Studio host to a version with agent API v1.', code='host_upgrade_required')
            capabilities = client.json('/h3c/api/v1/capabilities')
            print(json.dumps(dict(ok=True, agent_api_version=1, skills=len(catalog['skills']),
                                  profiles=len(capabilities.get('profiles', [])), render_ready=capabilities.get('readiness', {}).get('render', False))))
        else:
            from .server import create_server
            create_server(client, state_dir=args.state_dir).run(transport='stdio')
    except (StudioError, OSError, ValueError) as error:
        detail = error.result() if isinstance(error, StudioError) else {'code': 'local_io' if isinstance(error, OSError) else 'invalid_arguments', 'message': str(error)}
        print(json.dumps({'ok': False, 'error': detail}), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
