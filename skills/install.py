"""Link every skill of the H3 Continuity pack into agent skill folders.

    python skills/install.py                  # every existing ~/.agents, ~/.claude and ~/.codex skill folder
    python skills/install.py --target DIR     # these folders instead (created when missing)

Each skill becomes a link (a junction on Windows) to its folder in this checkout, so it follows the checkout
when it updates. A folder of the same name that isn't a link is left alone and reported.
"""

import argparse
import os
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent
DEFAULTS = [Path.home() / folder / "skills" for folder in (".agents", ".claude", ".codex")]


def skills():
    return sorted(path.parent for path in PACK.glob("*/SKILL.md"))


def is_link(path):
    if path.is_symlink():
        return True
    try:
        return bool(os.lstat(path).st_file_attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT: a junction
    except (OSError, AttributeError):
        return False


def link(source, destination):
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(source), str(destination))
    else:
        destination.symlink_to(source, target_is_directory=True)


def install(target):
    lines = []
    for source in skills():
        destination = target.absolute() / source.name
        if is_link(destination):
            if Path(os.path.realpath(destination)) == Path(os.path.realpath(source)):
                lines.append(f"{destination}: already linked")
                continue
            (os.rmdir if os.name == "nt" else os.unlink)(destination)
        elif destination.exists():
            lines.append(f"{destination}: left alone, it is a folder and not a link")
            continue
        link(source, destination)
        lines.append(f"{destination} -> {source}")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", action="append", type=Path, help="an agent skill folder (repeatable)")
    args = parser.parse_args(argv)
    targets = args.target or [path for path in DEFAULTS if path.is_dir()]
    if not targets:
        sys.exit("No agent skill folder found; name one with --target.")
    for target in targets:
        target.mkdir(parents=True, exist_ok=True)
        print("\n".join(install(target)))


if __name__ == "__main__":
    main()
