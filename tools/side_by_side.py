"""Side-by-side comparison MP4: clips in a row on one clock, each labeled, each clip's audio as its own track."""

import subprocess
import sys

FONT = "C\\:/Windows/Fonts/arial.ttf"


def _has_audio(clip, ffprobe="ffprobe"):
    result = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                             "-of", "csv=p=0", clip], capture_output=True, text=True, check=True)
    return bool(result.stdout.strip())


def command(clips, labels, output, height=544, ffmpeg="ffmpeg"):
    inputs = [arg for clip in clips for arg in ("-i", clip)]
    filters = [f"[{i}:v]scale=-2:{height},setsar=1,drawtext=fontfile='{FONT}':text='{label}':x=16:y=16:"
               f"fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=6[v{i}]"
               for i, label in enumerate(labels)]
    names = "".join(f"[v{i}]" for i in range(len(clips)))
    filters.append(f"{names}hstack=inputs={len(clips)}[v]" if len(clips) > 1 else "[v0]null[v]")
    maps, metadata, track = ["-map", "[v]"], [], 0
    for i, (clip, label) in enumerate(zip(clips, labels)):
        if _has_audio(clip):
            maps += ["-map", f"{i}:a"]
            metadata += [f"-metadata:s:a:{track}", f"title={label}", f"-metadata:s:a:{track}", f"handler_name={label}"]
            track += 1
    return [ffmpeg, "-y", *inputs, "-filter_complex", ";".join(filters), *maps,
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            *metadata, output]


if __name__ == "__main__":
    output, pairs = sys.argv[1], [arg.split("=", 1) for arg in sys.argv[2:]]
    subprocess.run(command([path for _, path in pairs], [label for label, _ in pairs], output), check=True)
    print(output)
