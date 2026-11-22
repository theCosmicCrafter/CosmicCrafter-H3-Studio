import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import side_by_side  # noqa: E402


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
class SideBySideTest(unittest.TestCase):
    def test_two_labeled_clips_with_own_audio(self):
        folder = tempfile.mkdtemp()
        clips = []
        for name, tone in (("a", 440), ("b", 660)):
            path = os.path.join(folder, name + ".mp4")
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=1",
                            "-f", "lavfi", "-i", f"sine=frequency={tone}:duration=1", "-shortest", path],
                           check=True, capture_output=True)
            clips.append(path)
        out = os.path.join(folder, "out.mp4")
        subprocess.run(side_by_side.command(clips, ["OFF", "ON"], out, height=180), check=True, capture_output=True)
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", out],
                                          check=True, capture_output=True).stdout)
        video = [s for s in probe["streams"] if s["codec_type"] == "video"]
        audio = [s for s in probe["streams"] if s["codec_type"] == "audio"]
        self.assertEqual((video[0]["width"], video[0]["height"]), (640, 180))
        self.assertEqual([s["tags"]["handler_name"] for s in audio], ["OFF", "ON"])


if __name__ == "__main__":
    unittest.main()
