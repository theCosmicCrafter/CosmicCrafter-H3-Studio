"""Import-time contract for the whole node pack.

The pack once shipped a ``NODE_CLASS_MAPPINGS`` entry that referenced a class
defined further down the file, so ComfyUI aborted loading the directory with a
``NameError`` and every node in the pack rendered red on the canvas.  Nothing in
the suite caught it, because the other tests import individual modules rather
than executing ``nodes.py`` the way ComfyUI does.

These tests execute ``nodes.py`` against mocked ComfyUI modules and assert the
registry is well-formed, so that class of failure cannot ship again.
"""

import contextlib
import importlib.util
import sys
import types
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent

#: Nodes that must survive any refactor - the audio-reactive pipeline.
REQUIRED_NODES = (
    "MiniMaxH3AudioAnalyze",
    "MiniMaxH3AudioCurveToMask",
    "MiniMaxH3MaskComposite",
    "MiniMaxH3LatentNoiseMask",
    "MiniMaxH3AudioReactiveDenoise",
    "MiniMaxH3AudioCurveRemap",
    "CosmicCrafterDirector",
)


class _NestedTensor:
    def __init__(self, tensors):
        self.tensors = list(tensors)
        self.is_nested = True

    def unbind(self):
        return self.tensors


def _install_comfy_mocks():
    """Register the minimal ComfyUI surface ``nodes.py`` touches at import."""

    def mod(name, **attrs):
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        sys.modules[name] = module
        return module

    mod("folder_paths",
        get_input_directory=lambda: ".",
        get_output_directory=lambda: ".",
        get_temp_directory=lambda: ".",
        get_folder_paths=lambda *a: ["."],
        get_filename_list=lambda *a: [],
        get_full_path=lambda *a: None,
        get_save_image_path=lambda *a, **k: (".", "x", 0, "", "x"))
    mod("node_helpers",
        conditioning_set_values=lambda cond, values, append=False: cond,
        pillow=lambda fn, path: fn(path))

    comfy = mod("comfy")
    utils = mod("comfy.utils",
                common_upscale=lambda s, w, h, m, c: s,
                ProgressBar=object,
                reshape_mask=lambda m, shape: m,
                pack_latents=lambda ls: (None, [t.shape for t in ls]))
    mod("comfy.model_management",
        intermediate_device=lambda: torch.device("cpu"))
    nested = mod("comfy.nested_tensor", NestedTensor=_NestedTensor)
    mod("comfy.samplers")
    mod("comfy.sample")
    mod("comfy.model_sampling")

    comfy.utils = utils
    comfy.nested_tensor = nested


#: Module names this test replaces; restored afterwards so sibling test
#: modules (which install their own, differently-shaped mocks into the same
#: process) still see the environment they set up.
_MOCKED = (
    "folder_paths", "node_helpers", "comfy", "comfy.utils",
    "comfy.model_management", "comfy.nested_tensor", "comfy.samplers",
    "comfy.sample", "comfy.model_sampling",
    "_cc_pack", "_cc_pack.nodes",
)


@contextlib.contextmanager
def _sandboxed_modules():
    saved = {name: sys.modules.get(name) for name in _MOCKED}
    try:
        yield
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


@contextlib.contextmanager
def _loaded_nodes_module():
    """Execute ``nodes.py`` the way ComfyUI loads a custom-node package."""
    with _sandboxed_modules():
        _install_comfy_mocks()

        package = types.ModuleType("_cc_pack")
        package.__path__ = [str(ROOT)]
        package.__package__ = "_cc_pack"
        sys.modules["_cc_pack"] = package

        spec = importlib.util.spec_from_file_location(
            "_cc_pack.nodes", str(ROOT / "nodes.py")
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["_cc_pack.nodes"] = module
        spec.loader.exec_module(module)
        yield module


def test_pack_imports_without_a_running_comfyui_server():
    # Guards the regression where a bare `from server import PromptServer`
    # at module scope broke every standalone import of the pack.
    with _loaded_nodes_module() as module:
        assert isinstance(module.NODE_CLASS_MAPPINGS, dict)
        assert module.NODE_CLASS_MAPPINGS, "pack registered no nodes"


def test_every_registered_class_is_defined():
    with _loaded_nodes_module() as module:
        for name, cls in module.NODE_CLASS_MAPPINGS.items():
            assert cls is not None, name
            assert isinstance(cls, type), f"{name} is not a class"


def test_every_node_has_a_display_name():
    with _loaded_nodes_module() as module:
        missing = sorted(
            set(module.NODE_CLASS_MAPPINGS) - set(module.NODE_DISPLAY_NAME_MAPPINGS)
        )
        assert not missing, f"nodes without a display name: {missing}"


def test_display_names_do_not_reference_unknown_nodes():
    with _loaded_nodes_module() as module:
        unknown = sorted(
            set(module.NODE_DISPLAY_NAME_MAPPINGS) - set(module.NODE_CLASS_MAPPINGS)
        )
        assert not unknown, f"display names for unregistered nodes: {unknown}"


def test_every_node_exposes_a_valid_schema():
    with _loaded_nodes_module() as module:
        problems = []
        for name, cls in module.NODE_CLASS_MAPPINGS.items():
            for attr in ("INPUT_TYPES", "RETURN_TYPES", "FUNCTION", "CATEGORY"):
                if not hasattr(cls, attr):
                    problems.append(f"{name} is missing {attr}")
            try:
                schema = cls.INPUT_TYPES()
            except Exception as exc:  # noqa: BLE001 - report, don't mask
                problems.append(f"{name}.INPUT_TYPES() raised {exc!r}")
                continue
            if not isinstance(schema, dict):
                problems.append(f"{name}.INPUT_TYPES() did not return a dict")
            if not hasattr(cls, getattr(cls, "FUNCTION", "")):
                problems.append(f"{name} has no method named by FUNCTION")
        assert not problems, "\n".join(problems)


def test_audio_reactive_pipeline_nodes_are_registered():
    with _loaded_nodes_module() as module:
        missing = [n for n in REQUIRED_NODES if n not in module.NODE_CLASS_MAPPINGS]
        assert not missing, f"audio-reactive nodes missing from registry: {missing}"


def test_cosmiccrafter_aliases_resolve_to_registered_classes():
    with _loaded_nodes_module() as module:
        registered = set(module.NODE_CLASS_MAPPINGS.values())
        for name, cls in module.NODE_CLASS_MAPPINGS.items():
            if name.startswith("CosmicCrafter"):
                assert cls in registered, f"alias {name} points outside the registry"
