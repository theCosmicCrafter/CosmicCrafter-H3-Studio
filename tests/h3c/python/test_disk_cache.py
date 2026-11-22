"""H3 Disk Cache: a first pass made from the same inputs loads from disk and the sampler does not run.

The scheduler tests run ComfyUI's real executor on the CPU with stand-ins shaped like rebuild_v2: a settings node feeds
the Timeline's size, the first pass's steps and the second pass's size; the Timeline's positive, latent and seed are the
keys. They load no models.
"""
import asyncio
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

import torch

from tests.h3c.continuity_support import enable_comfy_cpu

enable_comfy_cpu()

import execution  # noqa: E402
import nodes  # noqa: E402
from comfy.nested_tensor import NestedTensor  # noqa: E402
from comfy_execution.graph import DynamicPrompt  # noqa: E402

from h3_continuity import disk_cache, nodes as continuity, store  # noqa: E402

RAN = []
SEEN = {}


def stand_in(name, inputs, returns, function):
    def go(self, **values):
        RAN.append(name)
        SEEN[name] = values
        return function(**values)
    return type(name, (), {
        "INPUT_TYPES": classmethod(lambda cls: {"required": {key: (kind,) for key, kind in inputs.items()}}),
        "RETURN_TYPES": returns, "FUNCTION": "go", "CATEGORY": "test", "go": go,
        "OUTPUT_NODE": name == "TestSink"})


def latent_for(box):
    video = torch.full((1, 24, 2, 3, 4), float(box))
    return {"samples": NestedTensor((video, torch.zeros(1, 8, 2, 16))), "noise_mask": torch.ones(1, 1, 2, 3, 4)}


def sampled(positive, latent, seed, steps, note=None):
    out = dict(latent)
    out["samples"] = latent["samples"] + float(steps * 100 + seed)
    return (out,)


STAND_INS = {
    "TestSettings": stand_in("TestSettings", {"width": "INT", "steps": "INT", "second_pass": "INT"},
                             ("INT", "INT", "INT"), lambda width, steps, second_pass: (width, steps, second_pass)),
    "TestTimeline": stand_in("TestTimeline", {"width": "INT", "box": "INT", "manifest": "STRING"},
                             ("CONDITIONING", "LATENT", "INT", "STRING"),
                             lambda width, box, manifest: ([[torch.full((1, 3, 4), float(box)),
                                                             {"minimax_keyframes": [{"resolved_frame_index": 0,
                                                                                     "image": torch.zeros(1, 2, 2, 3)}]}]],
                                                           latent_for(box), 7, f"box {box}")),
    "TestSampler": stand_in("TestSampler", {"positive": "CONDITIONING", "latent": "LATENT", "seed": "INT", "steps": "INT"},
                            ("LATENT",), sampled),
    "TestSecondPass": stand_in("TestSecondPass", {"latent": "LATENT", "size": "INT"}, ("LATENT",),
                               lambda latent, size: (latent,)),
    "TestSink": stand_in("TestSink", {"latent": "LATENT"}, (), lambda latent: ()),
}


def prompt(box=1, manifest="a", steps=8, second_pass=768, mode="use", namespace="first_pass", sampler_reads_info=False):
    sampler = {"positive": ["tl", 0], "latent": ["tl", 1], "seed": ["tl", 2], "steps": ["cfg", 1]}
    if sampler_reads_info:
        STAND_INS["TestSampler"].INPUT_TYPES = classmethod(lambda cls: {"required": {
            "positive": ("CONDITIONING",), "latent": ("LATENT",), "seed": ("INT",), "steps": ("INT",)},
            "optional": {"note": ("STRING",)}})
        sampler["note"] = ["tl", 3]
    return {
        "cfg": {"class_type": "TestSettings", "inputs": {"width": 512, "steps": steps, "second_pass": second_pass}},
        "tl": {"class_type": "TestTimeline", "inputs": {"width": ["cfg", 0], "box": box, "manifest": manifest}},
        "s1": {"class_type": "TestSampler", "inputs": sampler},
        "cache": {"class_type": "H3C_DiskCache", "inputs": {"result": ["s1", 0], "keys.key0": ["tl", 0],
                                                            "keys.key1": ["tl", 1], "keys.key2": ["tl", 2],
                                                            "mode": mode, "namespace": namespace}},
        "s2": {"class_type": "TestSecondPass", "inputs": {"latent": ["cache", 0], "size": ["cfg", 2]}},
        "out": {"class_type": "TestSink", "inputs": {"latent": ["s2", 0]}},
    }


def run(graph, cache_type=execution.CacheType.RAM_PRESSURE):
    async def go():
        server = types.SimpleNamespace(client_id=None, last_node_id=None, last_prompt_id=None,
                                       send_sync=lambda *a, **k: None, prompt_queue=None)
        executor = execution.PromptExecutor(server, cache_type=cache_type,
                                            cache_args={"ram": 8, "ram_inactive": 8, "lru": 0})
        valid = await execution.validate_prompt("test", graph, None)
        assert valid[0], valid
        await executor.execute_async(graph, "test", {}, ["out"])
        assert executor.success, executor.status_messages
        return executor
    RAN.clear()
    SEEN.clear()
    return asyncio.run(go())


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="h3c-disk-cache-")
        self.addCleanup(shutil.rmtree, self.root, True)
        original = STAND_INS["TestSampler"].INPUT_TYPES
        self.addCleanup(setattr, STAND_INS["TestSampler"], "INPUT_TYPES", original)
        for patch in (mock.patch.dict(nodes.NODE_CLASS_MAPPINGS, {**STAND_INS, "H3C_DiskCache": disk_cache.H3C_DiskCache}),
                      mock.patch.object(disk_cache, "cache_root", lambda: self.root)):
            patch.start()
            self.addCleanup(patch.stop)

    def final(self):
        return SEEN["TestSink"]["latent"]

    def test_the_second_run_loads_the_first_pass_and_the_sampler_does_not_run(self):
        run(prompt())
        self.assertIn("TestSampler", RAN)
        first = self.final()
        run(prompt(manifest="saved one more box"))
        self.assertNotIn("TestSampler", RAN)
        self.assertIn("TestSecondPass", RAN)
        again = self.final()
        for a, b in zip(first["samples"].tensors, again["samples"].tensors):
            self.assertTrue(torch.equal(a, b))
        self.assertTrue(torch.equal(first["noise_mask"], again["noise_mask"]))

    def test_a_larger_second_pass_keeps_the_first_pass(self):
        run(prompt(second_pass=768))
        run(prompt(second_pass=1536))
        self.assertNotIn("TestSampler", RAN)
        self.assertEqual(SEEN["TestSecondPass"]["size"], 1536)

    def test_first_pass_settings_and_a_different_box_sample_again(self):
        run(prompt())
        run(prompt(steps=4))
        self.assertIn("TestSampler", RAN)
        run(prompt(box=2))
        self.assertIn("TestSampler", RAN)

    def test_refresh_samples_and_replaces_and_off_never_saves(self):
        run(prompt())
        run(prompt(mode="refresh"))
        self.assertIn("TestSampler", RAN)
        run(prompt(box=3, mode="off"))
        run(prompt(box=3))
        self.assertIn("TestSampler", RAN)

    def test_a_timeline_output_that_is_not_a_key_turns_the_cache_off(self):
        run(prompt(sampler_reads_info=True))
        run(prompt(sampler_reads_info=True))
        self.assertIn("TestSampler", RAN)
        self.assertEqual(os.listdir(self.root), [])

    def test_without_comfyui_caching_the_settings_are_still_read_by_value(self):
        run(prompt(second_pass=768), cache_type=execution.CacheType.NONE)
        run(prompt(second_pass=1536), cache_type=execution.CacheType.NONE)
        self.assertNotIn("TestSampler", RAN)


class KeyTest(unittest.TestCase):
    def test_contents_decide_the_digest_not_identity_or_dict_order(self):
        a = [[torch.ones(2, 3), {"x": 1, "y": [torch.zeros(1)]}]]
        b = [[torch.ones(2, 3).clone(), {"y": [torch.zeros(1)], "x": 1}]]
        self.assertEqual(disk_cache.content_digest(a), disk_cache.content_digest(b))
        self.assertNotEqual(disk_cache.content_digest(torch.ones(2, 3)), disk_cache.content_digest(torch.ones(3, 2)))
        self.assertNotEqual(disk_cache.content_digest(torch.ones(2)), disk_cache.content_digest(torch.ones(2).half()))
        self.assertNotEqual(disk_cache.content_digest(1), disk_cache.content_digest(1.0))
        self.assertNotEqual(disk_cache.content_digest(True), disk_cache.content_digest(1))

    def test_an_object_it_cannot_compare_is_refused(self):
        with self.assertRaises(disk_cache.Uncacheable):
            disk_cache.content_digest([{"model": object()}])

    def test_node_ids_do_not_matter_and_widget_values_do(self):
        def graph(ids, strength=1.0):
            lora, sampler, timeline, cache = ids
            return DynamicPrompt({
                lora: {"class_type": "Lora", "inputs": {"strength": strength}},
                timeline: {"class_type": "TestTimeline", "inputs": {"box": 1}},
                sampler: {"class_type": "Sampler", "inputs": {"model": [lora, 0], "latent": [timeline, 1]}},
                cache: {"class_type": "H3C_DiskCache", "inputs": {"result": [sampler, 0], "keys.key0": [timeline, 1]}}})

        def key(dynprompt, cache):
            with mock.patch.object(disk_cache, "node_class", lambda name: None):
                return disk_cache.describe_key(dynprompt, cache, "first_pass", {"key0": latent_for(1)})[0]

        self.assertEqual(key(graph(("1", "2", "3", "4")), "4"), key(graph(("10", "20", "30", "40")), "40"))
        self.assertNotEqual(key(graph(("1", "2", "3", "4")), "4"), key(graph(("1", "2", "3", "4"), 0.5), "4"))

    def test_a_node_that_changes_every_run_above_the_sampler_is_refused(self):
        changing = type("Changing", (), {"IS_CHANGED": classmethod(lambda cls, **kw: float("nan"))})
        dynprompt = DynamicPrompt({
            "1": {"class_type": "Changing", "inputs": {}, "is_changed": [float("nan")]},
            "2": {"class_type": "Sampler", "inputs": {"noise": ["1", 0], "latent": ["3", 0]}},
            "3": {"class_type": "TestTimeline", "inputs": {}},
            "4": {"class_type": "H3C_DiskCache", "inputs": {"result": ["2", 0], "keys.key0": ["3", 0]}}})
        with mock.patch.object(disk_cache, "node_class", lambda name: changing if name == "Changing" else None):
            with self.assertRaises(disk_cache.Uncacheable):
                disk_cache.describe_key(dynprompt, "4", "first_pass", {"key0": 1})
            dynprompt.get_node("1")["is_changed"] = ["file-hash"]
            disk_cache.describe_key(dynprompt, "4", "first_pass", {"key0": 1})

    def test_a_miss_names_the_key_part_that_changed(self):
        root = tempfile.mkdtemp(prefix="h3c-disk-cache-")
        self.addCleanup(shutil.rmtree, root, True)
        dynprompt = DynamicPrompt({
            "1": {"class_type": "TestTimeline", "inputs": {}},
            "2": {"class_type": "Sampler", "inputs": {"positive": ["1", 0], "latent": ["1", 1]}},
            "3": {"class_type": "H3C_DiskCache", "inputs": {"result": ["2", 0], "keys.key0": ["1", 0],
                                                            "keys.key1": ["1", 1]}}})
        positive = [[torch.zeros(1, 3), {"minimax_keyframes": [{"image": torch.zeros(1, 2, 2, 3)}]}]]
        changed = [[torch.zeros(1, 3), {"minimax_keyframes": [{"image": torch.ones(1, 2, 2, 3)}]}]]
        with mock.patch.object(disk_cache, "node_class", lambda name: None), \
                mock.patch.object(disk_cache, "cache_root", lambda: root):
            key, record = disk_cache.describe_key(dynprompt, "3", "ns", {"key0": positive, "key1": latent_for(1)})
            disk_cache.save("ns", key, latent_for(1), record)
            _, record = disk_cache.describe_key(dynprompt, "3", "ns", {"key0": changed, "key1": latent_for(1)})
            why = disk_cache.closest_difference("ns", record)
        self.assertIn("key0", why)
        self.assertIn("minimax_keyframes[0].image", why)
        self.assertNotIn("key1", why)


class GuideFrameTest(unittest.TestCase):
    def test_the_guide_is_the_last_played_frame_of_the_latent(self):
        frames = torch.arange(49, dtype=torch.float32).reshape(49, 1, 1, 1).expand(49, 2, 2, 3)
        self.assertEqual(continuity.guide_frame(frames, {"frames": 49, "context_frames": 22})[0, 0, 0].item(), 48)
        played = {"frames": 49, "context_frames": 22, "played": 17}
        self.assertEqual(continuity.guide_frame(frames, played)[0, 0, 0].item(), 38)
        with self.assertRaises(ValueError):
            continuity.guide_frame(frames[:48], {"frames": 49, "context_frames": 22})

    def test_a_continuing_box_prefers_the_guide_frame_to_the_finished_one(self):
        folder = tempfile.mkdtemp(prefix="h3c-guide-")
        self.addCleanup(shutil.rmtree, folder, True)
        entry = {"stem": "seg_0001"}
        store.save_last_frame(folder, entry, torch.ones(2, 2, 3))
        self.assertEqual(store.load_continuation_frame(folder, entry).max().item(), 1.0)
        store.save_guide_frame(folder, entry, torch.zeros(2, 2, 3))
        self.assertEqual(store.load_continuation_frame(folder, entry).max().item(), 0.0)
        self.assertEqual(store.load_last_frame(folder, entry).max().item(), 1.0)


if __name__ == "__main__":
    unittest.main()
