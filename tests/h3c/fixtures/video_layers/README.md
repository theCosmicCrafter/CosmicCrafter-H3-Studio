# Video layers fixtures

`02a.mp4` and `02b.mp4` are shot 02 of the test production "The Unguarded Lamplighter": the two angles that the
video-layers acceptance test (`tests/python/test_video_layers_acceptance.py`) stacks into one clip. No test reads the
production folder.

They were made once from the production's composites (HEVC, 1152 × 640, 24 fps, 90 frames, AAC 32 kHz stereo):

```powershell
$src = 'D:/development/rambrogi/work/orrery-productions/unguarded-lamplighter-20261112/composite/v3/02-first-lamp'
foreach ($n in '02a','02b') {
  ffmpeg -y -i "$src/$n.mp4" -vf "scale=288:160:flags=area" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p `
    -bf 0 -g 24 -c:a aac -b:a 64k -ar 32000 -ac 2 -map_metadata -1 -fflags +bitexact "tests/fixtures/video_layers/$n.mp4"
}
```

Each file is H.264 yuv420p at 288 × 160 without B-frames, 24 fps and 90 frames, with 3.75 s of AAC at 32 kHz stereo.
