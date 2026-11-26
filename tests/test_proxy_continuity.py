import json
from pathlib import Path

import numpy as np
from PIL import Image

from h3_proxy_continuity import (
    CosmicH3ProxyKeyframes,
    CosmicH3ProxyWorldState,
    bind_proxy_prompt,
    load_world_state,
    map_resonance_beats_to_shots,
    save_world_state,
)
from tests.test_pack_loads import _loaded_nodes_module


def test_world_state_persistence_across_revisit(tmp_path):
    ws_path = tmp_path / "world_state.json"
    state = {
        "schema_version": "1.0",
        "fps": 24,
        "entities": [
            {
                "id": "cobalt_crate",
                "granularity": "medium",
                "color_name": "cobalt blue",
                "hex": "#1E61E6",
                "role": "relocated_prop",
                "transforms_by_shot": {
                    "shot_01": {"location": [-0.15, -0.52, 1.22]},
                    "shot_02": {"location": [3.60, 0.20, 1.52]},
                    "shot_03": {"location": [3.60, 0.20, 1.52]},
                },
            },
            {
                "id": "artisan_hands",
                "granularity": "video_model_only",
            },
        ],
        "shots": [
            {"shot_id": "shot_01", "camera": {"location": [0.0, -4.35, 2.55]}},
            {"shot_id": "shot_02", "camera": {"location": [3.45, -2.55, 2.15]}},
            {"shot_id": "shot_03", "camera": {"location": [0.0, -4.35, 2.55]}},
        ],
    }

    save_world_state(ws_path, state)
    loaded = load_world_state(ws_path)
    assert loaded["entities"][0]["transforms_by_shot"]["shot_03"]["location"] == [3.60, 0.20, 1.52]
    assert loaded["shots"][0]["camera"] == loaded["shots"][2]["camera"]


def test_bind_proxy_prompt_grounds_entities_and_beats():
    entities = [
        {
            "id": "workbench_desk",
            "granularity": "medium",
            "color_name": "brown",
            "hex": "#8C6B47",
            "role": "static_env",
            "transforms_by_shot": {"shot_03": {"location": [0.0, 0.0, 0.5]}},
        },
        {
            "id": "crimson_sphere_orb",
            "granularity": "medium",
            "color_name": "crimson red",
            "hex": "#E02E33",
            "reference_image": "refs/orb.png",
            "transforms_by_shot": {"shot_03": {"location": [0.35, 0.0, 1.21]}},
        },
        {
            "id": "cobalt_crate",
            "granularity": "medium",
            "color_name": "cobalt blue",
            "hex": "#1E61E6",
            "transforms_by_shot": {"shot_03": {"location": [3.60, 0.20, 1.52]}},
        },
        {"id": "operator_hands", "granularity": "video_model_only"},
    ]
    grounded = bind_proxy_prompt(
        "Studio workbench shot.",
        entities=entities,
        shot_id="shot_03",
        beat_anchor={"start_frame": 48, "end_frame": 96, "beat_count": 4, "cue": "beat_cut@2.00s"},
        camera_x=0.0,
    )
    assert "brown workbench desk" in grounded
    assert "crimson red sphere orb in the center" in grounded
    assert "cobalt" not in grounded  # out of camera_x=0.0 range
    assert "operator hands" in grounded
    assert "#E02E33" not in grounded
    assert "frames=" not in grounded
    assert "beat cut" in grounded


def test_resonance_beat_mapping_to_shots():
    beat_grid = {
        "duration": 6.0,
        "beats": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5],
        "phrases": [
            {"start": 0.0, "end": 2.0, "label": "intro"},
            {"start": 2.0, "end": 6.0, "label": "drop"},
        ],
    }
    sched = map_resonance_beats_to_shots(json.dumps(beat_grid), num_shots=3, fps=24)
    assert len(sched) == 3
    assert sched[0]["start_frame"] == 0
    assert sched[0]["end_frame"] == sched[1]["start_frame"]
    assert sched[1]["end_frame"] == sched[2]["start_frame"]
    assert sched[2]["end_frame"] > sched[2]["start_frame"]
    assert "intro" in sched[0]["cue"]
    assert "drop" in sched[1]["cue"]


def test_proxy_world_state_and_keyframes_nodes(tmp_path):
    # Create unaligned 770x515 test images to confirm /32 cropping
    for name in ("shot_01_proxy.png", "shot_01_depth.png", "shot_03_proxy.png"):
        arr = np.full((515, 770, 3), 128, dtype=np.uint8)
        Image.fromarray(arr).save(tmp_path / name)

    ws_path = tmp_path / "world_state.json"
    save_world_state(
        ws_path,
        {
            "entities": [{"id": "amber_vessel", "granularity": "medium", "color_name": "amber", "hex": "#EB8519", "transforms_by_shot": {"shot_01": {"location": [1.25, 0.2, 1.32]}}}],
            "shots": [{"shot_id": "shot_01", "camera": {"location": [0.0, -4.35, 2.55], "lens_mm": 34.0}}],
        },
    )

    ws_node = CosmicH3ProxyWorldState()
    prompt, manifest_json, cam_json, sf, ef = ws_node.build_proxy_context(
        world_state_path=str(ws_path),
        shot_id="shot_01",
        base_prompt="Workbench establishing shot.",
        resonance_beats_json="",
        fps=24,
    )
    assert "amber vessel" in prompt
    assert "amber_vessel" in manifest_json
    assert "34.0" in cam_json
    assert sf == 0 and ef > sf

    kf_node = CosmicH3ProxyKeyframes()
    first, last, depth, w, h = kf_node.load_proxy_keyframes(
        shot_dir=str(tmp_path),
        shot_prefix="shot_01",
        align_to_32=True,
        last_shot_prefix="shot_03",
    )
    assert w % 32 == 0 and h % 32 == 0
    assert w == 768 and h == 512
    assert tuple(first.shape) == (1, 512, 768, 3)
    assert tuple(last.shape) == (1, 512, 768, 3)
    assert tuple(depth.shape) == (1, 512, 768, 3)


def test_poc_shot_dir_loads_if_present():
    poc_dir = Path(r"C:\Users\richk\CascadeProjects\_shots\code2video_poc")
    if not (poc_dir / "world_state.json").exists():
        return
    kf_node = CosmicH3ProxyKeyframes()
    first, last, depth, w, h = kf_node.load_proxy_keyframes(
        shot_dir=str(poc_dir),
        shot_prefix="shot_01",
        align_to_32=True,
        last_shot_prefix="shot_03",
    )
    assert w == 768 and h == 512
    assert tuple(first.shape) == (1, 512, 768, 3)


def test_proxy_continuity_nodes_registered():
    with _loaded_nodes_module() as module:
        assert "CosmicH3ProxyWorldState" in module.NODE_CLASS_MAPPINGS
        assert "CosmicH3ProxyKeyframes" in module.NODE_CLASS_MAPPINGS
        assert "CosmicH3ProxyWorldState" in module.NODE_DISPLAY_NAME_MAPPINGS
        assert "CosmicH3ProxyKeyframes" in module.NODE_DISPLAY_NAME_MAPPINGS
