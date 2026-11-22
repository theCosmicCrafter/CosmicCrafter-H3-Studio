# Box-bound audio: real browser and GPU smoke

Date: 2026-11-06. Product revision: `7805d11` (documentation HEAD `4f84972`). User explicitly requested browser testing and offered the free GPU after the implementation handoff. This authorizes the bounded smoke below; it does not authorize integration or replacing the installed checkout.

## Environment

- Actual ComfyUI 0.44.0 / frontend1.58.5, Python3.13.14, PyTorch2.14.1+cu130, RTX5090 Laptop24GB.
- The normal8188 backend was offline; its Tailscale proxy returned502. Started a dedicated hidden ComfyUI process on loopback8189 with `--base-directory .tmp/box-audio-live`, existing model directory, and only this branch's custom node enabled through an isolated junction. Existing input/output/user state and installed main were untouched.
- Real browser preview tools drove actual ComfyUI, TimelineHost, Studio, upload endpoint, saved-state endpoint, render queue and media viewer. No mocked services in this run.
- Native profile's UI graph adapted only in the test fixture to installed filenames: Qwen3VL32B NVFP4 encoder, native REF2VA INT8 ConvRot model, REF2V Turbo4-step LoRA, native video/audio VAEs. Euler,4steps,320x192,24fps. Host instructions and audio/text guides inspected before authoring.

## Browser checks

1. Loaded two independent22-frame boxes, memory off, and uploaded a48kHz mono source:330Hz for22frames then880Hz for22frames.
2. Selected **In the full video**, then **Lock audio to boxes** using real checkboxes. Two segments appeared; captured intervals were source0..22/24 and22/24..44/24.
3. Used real length controls to extend the first box22→39frames. Frozen assignments stayed byte-equivalent; a silence gap appeared in its tail.
4. Duplicated through Clip actions: duplicate had no assignment. Undid duplication. Added a new clip with **+ Clip**, configured the test clip to22frames/cut/memory-off, and moved it between the originals with the real Move earlier button. Only original IDs remained assigned; two silence gaps and two audio segments appeared.
5. Flushed the real saved-state service, reloaded the serialized graph and awaited real saved-state recovery: revision13 retained all bindings.
6. Queued all three through the real **Render remaining** control. All completed. The unassigned middle box ran T2VA; bound boxes used REF2VA.
7. Selected the later audio segment: audition source-in22/24, duration22/24, timeline start61/24; browser playback sought to its source interval and stopped. Source-in controls stayed disabled while locked.
8. Actual ComfyUI confirmation displayed the playback-change warning. Confirm removed binding and restored continuous placement; Undo restored the complete original map. A separate Cancel closed the dialog and preserved the map.
9. At1440x1000 and390x844 there was no page overflow. Mobile Timeline→audio segment opened accessible checked locking and disabled source controls. Inspected desktop/mobile screenshots.
10. The full-video viewer decoded320x192 media, duration3.458333seconds; playback reached `ended` without a media error. Inspected decoded frames10,48,71: ceramic birds on a table, valid picture in each clip. Memory-off independent cuts vary appearance; this smoke does not assess production visual continuity or lip sync.

## Encoded media verification

Decoded the actual assembled MP4 with PyAV/NumPy using `.tmp/box-audio-live/verify_media.py`; assertions passed, including a second run after unlock/Undo.

-83video frames,24fps,320x192;48kHz audio;133719bytes.
-SHA256: `e68cdfffc037542f1cf7e5cbca315eb43d6d3343956f2da9b6b982fd5b7bed66`.
-Expected soundtrack:330Hz at0..22/24; silence at22/24..61/24 (extended tail plus inserted box);880Hz at61/24..83/24. Playback speed unchanged.

| Interior region (seconds) | Measured dominant frequency | RMS |
| --- | --- | --- |
|0.10–0.80, first assignment|330Hz|0.1413684|
|1.00–1.50, extended tail|silence|0|
|1.75–2.40, inserted box|silence|0|
|2.65–3.35, later assignment|880Hz|0.1413820|

Checks sample interior windows to avoid AAC boundary effects. This confirms original-source soundtrack assembly; it does not claim the model itself generates silence or reproduces a recording exactly.

Local artifacts retained under `.tmp/box-audio-live/`: `browser-tested-workflow.json`, `two-notes.wav`, `media-verification.json`, `verify_media.py`, startup/render logs, decoded frame PNGs, and `output/h3_sequences/box-audio-browser-smoke-20261106/` containing full video, segment videos, manifest and latents. They are ignored test artifacts, not product changes.

## Cleanup

Queue empty and all3boxes done before cleanup. GPU owner `box-audio-range-lock-20261106-browser`, ticket `3b0ce6b5-281b-4821-94dd-e6f71424c945`: finish→cleanup, then owned server PID34644 stopped after verifying its exact base-directory/port arguments. Process and8189listener absent. GPU memory1031MiB versus1102MiB pre-run baseline; ticket released with no holder or cleanup reminder. Closed the owned browser tab. No merge, push, deployment or product-code edit.
