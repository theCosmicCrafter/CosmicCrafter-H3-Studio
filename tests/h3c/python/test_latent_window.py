import unittest

import torch

from h3_continuity import latents
from h3_continuity.timing import FRAME_PER_TOKEN, ticks_for_frames


class ChunkVAE:
    """Each token holds the number of the first source frame it covers, so a decode/encode round trip of
    consecutive frame numbers is exact and every window shows which frames it came from."""

    def __init__(self):
        self.calls = []

    def encode(self, frames):
        self.calls.append(("encode", frames.shape[0]))
        values, cursor = [], 0
        while cursor < frames.shape[0]:
            values.append(frames[cursor, 0, 0, 0].item())
            cursor += FRAME_PER_TOKEN[(len(values) - 1) % 5]
        return torch.tensor(values).reshape(1, 1, -1, 1, 1).expand(1, 24, -1, 2, 2).clone()

    def decode(self, latent):
        self.calls.append(("decode", latent.shape[2]))
        frames = []
        for token in range(latent.shape[2]):
            value = latent[0, 0, token, 0, 0].item()
            frames += [value + step for step in range(FRAME_PER_TOKEN[token % 5])]
        return torch.tensor(frames).reshape(1, -1, 1, 1, 1).expand(1, -1, 32, 32, 3).clone()


def source(frames=107):
    vae = ChunkVAE()
    pixels = torch.arange(frames, dtype=torch.float32).reshape(-1, 1, 1, 1).expand(-1, 32, 32, 3)
    video = vae.encode(pixels)
    ticks = ticks_for_frames(frames)
    audio = torch.arange(ticks, dtype=torch.float32).reshape(1, 1, 1, -1).expand(1, 32, 2, -1).clone()
    return video, audio


def numbers(video):
    return [int(value) for value in video[0, 0, :, 0, 0].tolist()]


class WindowTest(unittest.TestCase):
    def test_fake_vae_matches_the_token_grid(self):
        video, _ = source()
        self.assertEqual(video.shape[2], 32)
        self.assertEqual(numbers(video)[:7], [0, 1, 5, 9, 13, 17, 18])

    def test_chunk_aligned_windows_are_exact_slices(self):
        video, audio = source()
        vae = ChunkVAE()
        window, ticks = latents.window(video, audio, 34, 39, vae)
        self.assertEqual(vae.calls, [])
        self.assertTrue(torch.equal(window, video[:, :, 10:22]))
        self.assertEqual(numbers(window)[:3], [34, 35, 39])
        self.assertEqual(ticks.shape[-1], ticks_for_frames(39))

    def test_unaligned_windows_are_encoded_from_their_own_first_frame(self):
        video, audio = source()
        vae = ChunkVAE()
        window, ticks = latents.window(video, audio, 54, 39, vae)
        self.assertEqual(vae.calls, [("decode", 17), ("encode", 39)])
        self.assertEqual(window.shape, (1, 24, 12, 2, 2))
        self.assertEqual(numbers(window), [54, 55, 59, 63, 67, 71, 72, 76, 80, 84, 88, 89])
        self.assertEqual((int(ticks[0, 0, 0, 0]), int(ticks[0, 0, 0, -1])), (90, 154))

    def test_audio_window_stays_inside_the_source(self):
        video, audio = source()
        # Frame 85 starts at tick 142, but 22 frames need 37 ticks and the source has 178.
        _, ticks = latents.window(video, audio, 85, 22, None)
        self.assertEqual(ticks.shape[-1], 37)
        self.assertEqual(int(ticks[0, 0, 0, -1]), audio.shape[-1] - 1)

    def test_bad_windows(self):
        video, audio = source()
        with self.assertRaises(ValueError):
            latents.window(video, audio, 80, 39, ChunkVAE())
        with self.assertRaises(ValueError):
            latents.window(video, audio, 54, 39, None)
        with self.assertRaises(ValueError):
            latents.window(video, audio, 0, 30, ChunkVAE())


if __name__ == "__main__":
    unittest.main()
