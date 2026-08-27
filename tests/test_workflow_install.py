"""The generator must put workflows where ComfyUI can actually see them.

ComfyUI lists only what is under ``<install>/user/default/workflows``. A graph
sitting in this repo is invisible to its sidebar, which is how a stale workflow
stayed loaded across several runs while the regenerated file changed on disk.
"""

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "_cc_builder", ROOT / "tools" / "build_audio_reactive_workflow.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_cc_builder"] = module
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


def _make_install(tmp):
    target = tmp / builder.USER_WORKFLOWS
    target.mkdir(parents=True)
    return target


def test_user_workflows_path_matches_comfyui_layout():
    assert builder.USER_WORKFLOWS == Path("user") / "default" / "workflows"


def test_install_root_resolves_to_the_workflows_dir(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = _make_install(root)
        assert builder.find_comfyui_workflows(str(root)) == target


def test_workflows_dir_is_accepted_directly():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        target = _make_install(Path(tmp))
        assert builder.find_comfyui_workflows(str(target)) == target


def test_environment_variable_wins_over_argument():
    import tempfile
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        env_target = _make_install(Path(a))
        arg_root = Path(b)
        _make_install(arg_root)

        previous = os.environ.get("COMFYUI_USER_WORKFLOWS")
        os.environ["COMFYUI_USER_WORKFLOWS"] = str(env_target)
        try:
            assert builder.find_comfyui_workflows(str(arg_root)) == env_target
        finally:
            if previous is None:
                os.environ.pop("COMFYUI_USER_WORKFLOWS", None)
            else:
                os.environ["COMFYUI_USER_WORKFLOWS"] = previous


def test_missing_install_is_reported_not_guessed():
    import tempfile
    previous = os.environ.pop("COMFYUI_USER_WORKFLOWS", None)
    saved_roots = builder.CANDIDATE_ROOTS
    try:
        with tempfile.TemporaryDirectory() as tmp:
            # No user/default/workflows underneath: must not invent a location.
            builder.CANDIDATE_ROOTS = (Path(tmp),)
            assert builder.find_comfyui_workflows() is None
    finally:
        builder.CANDIDATE_ROOTS = saved_roots
        if previous is not None:
            os.environ["COMFYUI_USER_WORKFLOWS"] = previous


def test_install_writes_every_variant_into_a_named_subdir():
    import tempfile
    previous = os.environ.pop("COMFYUI_USER_WORKFLOWS", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            target = _make_install(Path(tmp))
            builder.main(["--install-to", tmp])

            dest = target / builder.INSTALL_SUBDIR
            assert dest.is_dir(), "workflows were not grouped in a sub-directory"
            installed = {p.name for p in dest.glob("*.json")}
            expected = {builder.variant_filename(n) for n in builder.VARIANTS}
            assert installed == expected
    finally:
        if previous is not None:
            os.environ["COMFYUI_USER_WORKFLOWS"] = previous


def test_no_install_flag_leaves_comfyui_untouched():
    import tempfile
    previous = os.environ.pop("COMFYUI_USER_WORKFLOWS", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            target = _make_install(Path(tmp))
            builder.main(["--install-to", tmp, "--no-install"])
            assert not (target / builder.INSTALL_SUBDIR).exists()
    finally:
        if previous is not None:
            os.environ["COMFYUI_USER_WORKFLOWS"] = previous
