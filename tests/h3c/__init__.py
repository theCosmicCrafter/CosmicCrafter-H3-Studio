"""Vendored H3 Continuity test package.

This pack ships a root-level ``nodes.py`` (the V1 node registry). When the
pack root is on ``sys.path`` — as ``unittest discover -t .`` arranges — a bare
``import nodes`` inside ComfyUI's ``server.py`` would resolve to the pack's
module instead of ComfyUI's. Putting ``COMFY_ROOT`` first keeps ComfyUI's own
modules authoritative, matching what ``enable_comfy_cpu()`` does for the
opt-in tests.
"""

import os
import sys

_comfy = os.environ.get("COMFY_ROOT")
if _comfy and os.path.isfile(os.path.join(_comfy, "main.py")):
    sys.path.insert(0, os.path.realpath(_comfy))
