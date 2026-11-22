// Runs the browser-module tests (node --test) and the package tests (unittest) with ComfyUI's Python.
// Vendored into CosmicCrafter-H3-Studio at tests/h3c/ — paths adjusted for the
// new location and this machine's Comfy-Desktop install.
// Python: $H3_PYTHON, else the Comfy-Desktop venv, else the Windows portable
// ComfyUI Python if present, else `python`.
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { delimiter, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../..', import.meta.url));
const desktopVenv = 'F:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\ComfyUI\\.venv\\Scripts\\python.exe';
const desktopComfy = 'F:\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI\\ComfyUI';
const portable = join(homedir(), 'ComfyUI', 'ComfyUI_windows_portable', 'python_embeded', 'python.exe');
const python = process.env.H3_PYTHON
  || (existsSync(desktopVenv) ? desktopVenv : '')
  || (existsSync(portable) ? portable : 'python');
// Product tests that load ComfyUI on the CPU read COMFY_ROOT.
const comfy = process.env.COMFY_ROOT
  || (existsSync(join(desktopComfy, 'main.py')) ? desktopComfy : '')
  || join(homedir(), 'ComfyUI', 'ComfyUI_windows_portable', 'ComfyUI');
// PYTHONPATH puts ComfyUI's root on sys.path so `folder_paths` resolves for the
// product tests that import h3_continuity modules without enable_comfy_cpu().
const env = existsSync(join(comfy, 'main.py'))
  ? { ...process.env, COMFY_ROOT: comfy, PYTHONPATH: [comfy, process.env.PYTHONPATH].filter(Boolean).join(delimiter) }
  : process.env;
const run = (command, args) => spawnSync(command, args, { cwd: root, stdio: 'inherit', env }).status;

const js = run(process.execPath, ['--test', 'tests/h3c/js/*.test.mjs', 'tests/h3c/web/*.test.mjs']);
// `-t .` puts the pack root on sys.path so `h3_continuity` and `tests.h3c.*` resolve.
const py = run(python, ['-m', 'unittest', 'discover', '-s', 'tests/h3c', '-t', '.', '-p', 'test_*.py']);
if (py == null) console.error(`Could not start ${python}; set H3_PYTHON to ComfyUI's Python.`);
process.exit(js === 0 && py === 0 ? 0 : 1);
