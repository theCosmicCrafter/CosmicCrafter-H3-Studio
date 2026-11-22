# MCP for Codex and Claude Code

The standalone **h3c-mcp** adapter lets an agent use saved Studio projects, render tools and the seven existing H3 skills. Your agent launches it over stdio. The adapter calls the configured ComfyUI HTTP URL, on this computer or another host. Studio does not need an open browser.

## Install and check

Update the H3 Continuity node on the **Studio host**, install its `requirements.txt` with ComfyUI's Python and restart it when convenient. The host must provide `/h3c/agent/catalog` (agent API v1). Updating only the adapter cannot add routes to an older host.

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) or use Python **3.11 or newer** in a separate virtual environment. MCP dependencies belong in the adapter environment, separate from ComfyUI. Models and writer providers still need their usual Studio configuration.

With a checkout at `C:\AI Tools\Continuity Studio`, run in PowerShell:

```powershell
uv run --project "C:\AI Tools\Continuity Studio\mcp_adapter" h3c-mcp --studio-url http://127.0.0.1:8188 --workspace-root "C:\My Projects" --check
```

On macOS/Linux, use your checkout's absolute path:

```sh
uv run --project "/opt/Continuity Studio/mcp_adapter" h3c-mcp --studio-url http://127.0.0.1:8188 --workspace-root "$PWD" --check
```

`--check` prints one JSON diagnostic with the host version, skill/profile counts and render readiness. It queues no work. Ordinary server mode reserves stdout for MCP and sends diagnostics to stderr. The first uv launch installs dependencies; run the check before registering the server.

To run a single tool without registering the server, for scripts or to try a request, pass `--call` with the tool name and `--arguments` with its arguments. Arguments can be a JSON object, `@file` or `-` for standard input:

```powershell
'{"kind":"native"}' | uv run --project "C:\AI Tools\Continuity Studio\mcp_adapter" h3c-mcp --studio-url http://127.0.0.1:8188 --call h3_list_projects --arguments -
uv run --project "C:\AI Tools\Continuity Studio\mcp_adapter" h3c-mcp --call h3_get_project --arguments "@C:\My Projects\target.json"
```

Piping or a file avoids shell quoting differences; Windows PowerShell 5.1 strips the inner quotes from inline JSON.

The tool's result is printed as one JSON line. Arguments are validated as an MCP client's would be. On failure, an `{"ok":false,"error":...}` diagnostic goes to stderr with exit code 1. Each call is independent: keep revisions, request keys and job handles yourself, and use the same `--state-dir` for job tools.

An isolated venv is an alternative, including for machines without uv:

```powershell
py -3.13 -m venv "C:\AI Tools\h3c-mcp-env"
& "C:\AI Tools\h3c-mcp-env\Scripts\python.exe" -m pip install "C:\AI Tools\Continuity Studio\mcp_adapter"
& "C:\AI Tools\h3c-mcp-env\Scripts\h3c-mcp.exe" --studio-url http://127.0.0.1:8188 --check
```

Use `python3 -m venv /path/to/h3c-mcp-env`, then its `bin/python -m pip install /path/to/checkout/mcp_adapter` and `bin/h3c-mcp` on macOS/Linux. An installed wheel contains the adapter; skill bodies always come from the configured Studio host. Reinstall after adapter changes.

## Register the launcher

These commands change your selected agent's MCP configuration. Keep each quoted path as one argument. Replace the example paths with real ones; do not add `--check` to a server launcher.

### Codex

```powershell
codex mcp add h3-continuity -- uv run --project "C:\AI Tools\Continuity Studio\mcp_adapter" h3c-mcp --studio-url http://127.0.0.1:8188 --workspace-root "C:\My Projects"
codex mcp list
codex mcp get h3-continuity
```

For the venv install, replace `uv run ... h3c-mcp` with the absolute `h3c-mcp.exe` (or `bin/h3c-mcp`) path. In Codex, `/mcp` shows the active server and tools. See the [official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

### Claude Code

```powershell
claude mcp add --transport stdio h3-continuity -- uv run --project "C:\AI Tools\Continuity Studio\mcp_adapter" h3c-mcp --studio-url http://127.0.0.1:8188 --workspace-root "C:\My Projects"
claude mcp list
claude mcp get h3-continuity
```

The default Claude scope is local to the project. Add `--scope user` before the server name if you want the launcher available across projects. Use `/mcp` inside Claude Code for connection status. A direct executable or uv needs no `cmd /c` wrapper. See [Claude Code's MCP documentation](https://code.claude.com/docs/en/mcp).

## Remote Studio and authentication

The client-to-adapter connection stays stdio. Point **the adapter** at the remote Studio, including a reverse-proxy prefix:

```powershell
uv run --project "C:\AI Tools\Continuity Studio\mcp_adapter" h3c-mcp --studio-url https://studio.example.com/comfy --workspace-root "C:\My Projects" --token-env H3C_STUDIO_TOKEN --check
```

`H3C_STUDIO_URL` supplies the default URL when no flag is given. A token in `H3C_STUDIO_TOKEN` becomes the HTTP `Authorization: Bearer` header; `--token-env` selects another variable. An unset variable means no authentication header. Keep credentials out of URL arguments and shared config. Use your existing authenticated Studio proxy; this adapter does not add an HTTP listener or authentication to ComfyUI. Redirects are refused: configure the final URL.

Start the agent with the token available in its environment. Codex stdio configuration can explicitly forward it:

```toml
[mcp_servers.h3-continuity]
command = "uv"
args = ["run", "--project", "C:\\AI Tools\\Continuity Studio\\mcp_adapter", "h3c-mcp", "--studio-url", "https://studio.example.com/comfy", "--workspace-root", "C:\\My Projects"]
env_vars = ["H3C_STUDIO_TOKEN"]
startup_timeout_sec = 30
```

Claude project `.mcp.json` can use environment expansion, without storing a token value:

```json
{"mcpServers":{"h3-continuity":{"type":"stdio","command":"uv","args":["run","--project","C:\\AI Tools\\Continuity Studio\\mcp_adapter","h3c-mcp","--studio-url","https://studio.example.com/comfy","--workspace-root","C:\\My Projects"],"env":{"H3C_STUDIO_TOKEN":"${H3C_STUDIO_TOKEN}"}}}}
```

Local upload/download paths refer to the **adapter computer**. Repeat `--workspace-root` to allow more directories; the default is the launcher's working directory. Original bytes are uploaded; managed artifact downloads verify size and SHA-256 before replacing a local file. Native media descriptors refer to files on the Studio host and have the native route's weaker integrity contract.

## First requests and skills

Ask your agent:

> Call h3_capabilities, read skill://h3-continuity-video/SKILL.md with h3_read_guidance, then list saved native projects. Report readiness and missing snapshots before changing anything.

The adapter exposes `io.modelcontextprotocol/skills` with real `skills/list` and `skills/get` manifests plus ordinary MCP resource reads. Every manifest includes complete frontmatter and exact file-byte hashes/sizes from the host. Guidance is not copied into a second skill tree.

Extension discovery, reading a resource, and activating a client skill are different things. SDK conformance is tested separately from installed-client compatibility. A client that discovers tools can use `h3_read_guidance` even if it does not activate extension skills. For filesystem skills, use the existing installer from a checkout matching the host:

Fixture checks on 2026-11-08: Codex CLI 0.166.0 discovered 21 tools and a resource through its app-server status API; Claude Code 2.1.316 reported a connected stdio server. Automatic Skills activation was not verified in either client. Modern Skills list/get/resource behavior passes with the extension-aware Python SDK client, and legacy ordinary guidance reads pass separately.

```powershell
python "C:\AI Tools\Continuity Studio\skills\install.py" --target "$env:USERPROFILE\.agents\skills" --target "$env:USERPROFILE\.claude\skills"
```

It links all seven skills (Windows junctions), preserving ordinary existing folders. Remote host guidance takes precedence over an older local copy. Client verification results and the complete action reference are in [docs/MCP.md](https://github.com/KadoBOT/ComfyUI-H3-Continuity-Studio/blob/main/docs/MCP.md).

## Saved editing and recovery

Choose an explicit managed project ID or native saved graph/Timeline/Story identity. Read the whole `document_json`, edit it with an exact-integer JSON parser, and save with the returned revision. Keep unknown metadata, uint64 seeds, source audio clocks, manual prompts and acceptance records intact.

Native projects saved before execution snapshots existed remain editable. To run them, save a configured workflow in Studio (including its captured API prompt), or call `h3_register_workflow` with matching editor and executable API exports. The adapter cannot compile an arbitrary editor graph or read unsaved browser edits. Changed wiring/computed bindings can require a fresh snapshot. Managed projects stay on their configured profile; use explicit workflow export/fork when needed.

There is no browser synchronization or automatic merge. An older browser save may overwrite newer work where existing guards allow it. A revision conflict requires rereading and a deliberate edit. Busy sequences, managed leases and immutable checkpoints retain their guards. Named checkpoint restoration makes an editable copy; browser Undo is session history, not a remote revision rollback.

Plan before rendering. A native submit queues **one eligible box or insertion bridge**; status never queues the next unit. Managed jobs continue on the server. Retain each request key, job handle, plan and adapter state directory. Default receipts live under `%LOCALAPPDATA%\h3c-mcp` on Windows, `$XDG_STATE_HOME/h3c-mcp` or `~/.local/state/h3c-mcp` elsewhere; `--state-dir` overrides it. Reuse the same directory across restarts.

A lost acknowledgement stays `needs_reconciliation` until queue/history or Story request attribution proves ownership. Poll/resume the retained handle; do not create another key to hide uncertainty. No receipt expiry or automatic retry submits duplicate native work. Native global cancellation is unavailable through MCP; use Studio to stop the identified prompt. Scoped Story and managed cancellation are available.

| Symptom | Action |
| --- | --- |
| Connection refused / host offline | Start Studio and rerun the same launcher with `--check`. |
| Missing catalog / version mismatch | Update the node on the serving host as well as the adapter. |
| No ready profile/model | Configure the existing graph/models in Studio; the adapter does not install weights. |
| Execution snapshot required | Save/capture matching UI + API workflow data; old projects can still be edited. |
| `revision_conflict` / `plan_conflict` | Reread and inspect changes, then deliberately save/replan. |
| Held/unknown job | Retain receipts and poll existing evidence; do not resubmit or clear the global queue. |
| Resource changed | Refresh the manifest and reread the host file. |
| No client skill activation | Read guidance as ordinary context or install the filesystem pack. |

Generated Story/still results remain retrievable proposals. Explicitly save/accept them after checking the current revision; late results never replace newer authored data. Watch resulting media before creative acceptance. Replacement bridge generation, retired guide splitting/recheck, browser playback/layout/Undo and browser beat/waveform analysis are not MCP generation tools.
