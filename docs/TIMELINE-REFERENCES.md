# MiniMax H3 references in Timeline and Story

H3 Timeline accepts the same reference media groups as the native **MiniMax H3 Reference to Video** node:

| Timeline input | Native reference input | Prompt mention | Meaning |
| --- | --- | --- | --- |
| `images.imageN` | `ref_images` | `@imageN` | Image reference; up to 9 selected per box |
| `videos.video1–3` | `ref_videos` | `@video1` | Video frame batch at 24 fps |
| `video_audios.video_audio1–3` | `ref_video_audios` | `@video_audio1` | Optional soundtrack paired with the same-numbered video |
| `audios.audio1–3` | `ref_audios` | `@audio1` | Standalone audio reference |

Connect a video loader's frame batch to `video1` and its audio output to `video_audio1`. A loader returning a ComfyUI `VIDEO` object needs **Get Video Components** to obtain the `IMAGE` frame batch and `AUDIO` waveform. Supply frames at 24 fps, as required by the native node. Existing image and audio wiring stays compatible.

Timeline also exposes `IMAGE` outputs named `image_1`, `image_2`, and so on, matching the selected clip's final native `<Picture 1>`, `<Picture 2>` order. For example, if `@image17` is `<Picture 1>`, its pixels appear on `image_1`. This order includes uploaded pictures, replacements, image RefMods and accepted endpoint guides. Cached endpoint presentations occupy their repeated Picture positions; a Last image used only by AddGuide has no Picture output. New sockets append without moving existing connections. Missing Picture positions block their consumers. Image exports run independently of video preparation. Appearance plates follow the selected clip's reference rules; endpoint images retain their native source. Outputs return source pixels; explicit RefMods decode their stored visual reference through the connected H3 VAE, so reconstructed pixels may differ from the original image. Restart ComfyUI and refresh the browser after installing this update.

Video and audio labels are assigned separately for each box. Only selected references are sent. In the selected video slot order, every selected soundtrack gets an `<Audio N>` label before standalone audio. For example, `@video3 @video_audio3 @audio2` becomes `<Video 1> <Audio 1> <Audio 2>`. There is no separate `<Video Audio N>` prompt tag.

Mentioning a video selects its visual track only. Mentioning `@video_audio3` also selects its required `video3`; a missing video produces a validation error. Disabling a video excludes its paired soundtrack while retaining the saved prompt and connections, and enabling it restores them. Audio VAE behavior is the same as the native node: without an audio VAE, audio supplies labels rather than audio latents.

Studio has an independent References pane on the left, with enabled references above disabled references. Use **Disable all** beside Enabled or **Enable all** beside Disabled. Each group preserves source order. Clicking a thumbnail previews the reference; its separate controls enable, disable or replace it. The pane can be hidden while working in the center Viewer, Story, Cast, Pictures or RefMods tabs. The selected Clip inspector stays on the right, with a drawer on narrow screens. Empty Audio and Text timeline rows have inline add actions; Text uses the existing Whisper timing importer.

Choose **Replace** to select any available reference of the same type, including disabled references. Replacing `image23` with `image12` switches prompt mentions, frame assignments and Cast picture selections to `image12`, enables it and disables `image23`. Selecting a zero-strength RefMod restores its strength to 1. The original source media remains available, and the entire switch supports Undo/Redo and save/reload. Uploading a replacement file keeps the original slot name; **Restore original source** removes that file override. Existing saved source aliases remain supported. A video RefMod held in an `imageN` slot requires another video RefMod; it cannot use a raw image upload.

Replacing `videoN` follows its paired `video_audioN` soundtrack automatically. A soundtrack source alias must remain paired with the effective video source; an explicitly uploaded audio file can override the soundtrack independently. Native connected video inputs remain numbered 1–3, while replacement aliases can use any positive slot number. H3's per-box selected-media limits still apply.

H3 Story can select video/audio references and accepts `descriptions.video1` and `descriptions.video_audio1` text inputs. Provide descriptions of motion/camera/structure and audible content there. The writer uses those descriptions; this update does not add a video or audio transcription provider. Whole-video relationships use `<Video N>`; visible subjects taken from video can still have `<Subject N>` definitions, and soundtracks use `<Audio N>`.

Automatically generated image identity descriptions now request just three or four prominent visible traits in one phrase or sentence, at most 30 words. Old generated descriptions refresh on the next description pass, while manually supplied descriptions are preserved. Whole-scene idea-image descriptions keep their separate story-inspiration instructions.

Native preprocessing handles video resizing, frame alignment and trimming. Full selected frame batches and soundtracks participate in the reference cache identity, so changing a later frame or soundtrack invalidates affected saved results. Existing RefMods and visual memories follow native reference ordinals without collisions.

Sources: [MiniMax full-reference guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md), [native ComfyUI implementation](https://github.com/comfyanonymous/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py).
