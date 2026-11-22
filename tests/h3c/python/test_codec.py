import os
import shutil
import tempfile
import unittest

import av
import torch

from h3_continuity import media


def frames(count, channel):
    """Frame i is a flat colour in `channel` of level 10 * (i + 2), so the source and index survive encoding."""
    images = torch.zeros(count, 32, 32, 3)
    for index in range(count):
        images[index, :, :, channel] = (index + 2) * 10 / 255
    return images


def label(array):
    means = array.reshape(-1, 3).mean(axis=0)
    channel = int(means.argmax())
    return channel, round(means[channel] / 10) - 2


def describe(path):
    with av.open(path) as container:
        stream = container.streams.video[0]
        packets = [(p.pts, p.dts) for p in container.demux(stream) if p.size]
        return {"codec": stream.codec_context.name, "tag": stream.codec_tag, "pix_fmt": stream.codec_context.pix_fmt,
                "transfer": stream.codec_context.color_trc, "packets": packets}


class CodecTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="h3c-codec-")

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.folder, name)

    def test_default_stays_h264(self):
        media.write_segment_video(self.path("a.mp4"), frames(22, 0), 24, 16)
        self.assertEqual(describe(self.path("a.mp4"))["codec"], "h264")
        self.assertEqual(media.video_codec(self.path("a.mp4")), "H.264")

    def test_hevc_segment_is_tagged_and_has_no_b_frames(self):
        media.write_segment_video(self.path("a.mp4"), frames(22, 0), 24, 16, codec="HEVC")
        info = describe(self.path("a.mp4"))
        self.assertEqual(info["codec"], "hevc")
        self.assertEqual(info["tag"], "hvc1")
        self.assertEqual(info["pix_fmt"], "yuv420p")
        # packet copy joins need decode order == presentation order
        self.assertEqual([pts for pts, _ in info["packets"]], sorted(pts for pts, _ in info["packets"]))
        self.assertEqual([pts for pts, _ in info["packets"]], [dts for _, dts in info["packets"]])
        decoded = media.read_frames(self.path("a.mp4"), range(22))
        self.assertEqual([label(decoded[i]) for i in range(22)], [(0, i) for i in range(22)])

    def test_hevc_hdr_is_ten_bit_hlg(self):
        media.write_segment_video(self.path("a.mp4"), frames(22, 1), 24, 16, color_space="HDR", codec="HEVC")
        info = describe(self.path("a.mp4"))
        self.assertEqual((info["codec"], info["pix_fmt"]), ("hevc", "yuv420p10le"))
        self.assertEqual(info["transfer"], 18)  # ARIB STD-B67 (HLG)

    def test_hevc_segments_join_by_packet_copy_and_stay_hevc(self):
        for name, channel in (("a.mp4", 0), ("b.mp4", 2)):
            media.write_segment_video(self.path(name), frames(22, channel), 24, 16, codec="HEVC")
        written, note = media.build_full_video(self.path("full.mp4"), [self.path("a.mp4"), self.path("b.mp4")], None, 16)
        self.assertNotIn("re-encoded", note)
        info = describe(written)
        self.assertEqual((info["codec"], info["tag"]), ("hevc", "hvc1"))
        decoded = media.read_frames(written, range(44))
        self.assertEqual([label(decoded[i]) for i in range(44)],
                         [(0, i) for i in range(22)] + [(2, i) for i in range(22)])

    def test_re_encoded_full_video_keeps_hevc(self):
        for name, channel in (("a.mp4", 0), ("b.mp4", 2)):
            media.write_segment_video(self.path(name), frames(22, channel), 24, 16, codec="HEVC")
        written, note = media.build_full_video(
            self.path("full.mp4"), [self.path("a.mp4"), (self.path("b.mp4"), 6, 10)], None, 16)
        self.assertIn("re-encoded", note)
        self.assertEqual(describe(written)["codec"], "hevc")
        decoded = media.read_frames(written, range(32))
        self.assertEqual([label(decoded[i]) for i in range(32)],
                         [(0, i) for i in range(22)] + [(2, i) for i in range(6, 16)])

    def test_unknown_codec_is_refused(self):
        with self.assertRaises(ValueError):
            media.write_segment_video(self.path("a.mp4"), frames(22, 0), 24, 16, codec="AV1")


if __name__ == "__main__":
    unittest.main()
