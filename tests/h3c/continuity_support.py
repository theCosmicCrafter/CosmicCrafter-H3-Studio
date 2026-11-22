"""Opt-in CPU bootstrap for later product tests; pure E1 tests never call it."""


def enable_comfy_cpu():
    import os
    import sys
    from pathlib import Path

    root = Path(os.environ['COMFY_ROOT']).resolve()
    if not (root / 'main.py').is_file():
        raise ValueError('COMFY_ROOT must identify the selected ComfyUI checkout')
    sys.path.insert(0, str(root))
    import comfy.cli_args
    comfy.cli_args.args.cpu = True
