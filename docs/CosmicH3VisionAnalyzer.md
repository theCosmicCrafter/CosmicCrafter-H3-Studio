# Cosmic Video | MiniMax-H3 Vision Analyzer

**Category:** `Cosmic/Video/H3`

## Description

Describes reference images in the concrete physical terms an H3 prompt needs, using a vision model on a local or cloud provider, and hands the result to the Promptor's `vision_context` input. The model is told to report only what is visibly there: no mood words, no interpretation, no story. Five focus settings narrow the description to one aspect of a reference look. A sixth, `event chain (timestamped)`, turns the node into the reasoning half of reverse prompting: fed a contact sheet and the evidence from the Video Forensics node, it reconstructs what happened in an existing clip as trigger, action and reaction, each step with its time.

## Inputs

- **images**: Reference frames. Only the first `max_frames` are sent. For the event chain focus, wire the Video Forensics `contact_sheet` here; it is one image carrying up to 16 timestamped frames.
- **provider** / **model**: Must be a vision model (llava, qwen2-vl, gpt-4o, claude-*, gemini-*). ollama and lmstudio are local; openai, anthropic and gemini need a key. Blank model picks the first the provider lists, which for a text-only model will fail.
- **focus**: What to concentrate on.
  - `everything`: subject identity, wardrobe, setting, lighting, style and composition.
  - `subject identity`: who or what the subject is; age, build, hair, face, distinguishing marks.
  - `wardrobe and props`: clothing, colours, materials, and every object held or worn.
  - `lighting and style`: light direction, quality and colour, and the visual style or film stock.
  - `composition and camera`: shot size, angle, framing, depth of field, where the subject sits.
  - `event chain (timestamped)`: reconstruct the clip's timeline from the frames and the evidence, in time order, from visible evidence only. Every cut, freeze, flash and black frame in the evidence must appear at its time, and every listed audio peak must be explained by something seen at or just before it, or reported as unexplained.
- **endpoint**, **api_key**: Provider plumbing. Prefer environment variables for keys.
- **max_frames**: How many frames of a batch to send. Each one costs a round trip and tokens. With a contact sheet, 1 is enough.
- **evidence** (optional): The Video Forensics `evidence` string. It is appended to the user message under a "Measured evidence" heading. With the event chain focus it is the model's timeline; with any other focus it is offered as context, with the instruction to mention a cut, freeze, flash or black frame only if it changes what the frames show.

## Outputs

- **vision_context**: `STRING`. What the references show, written for an H3 prompt. Wire it to the Promptor's `vision_context`; the Promptor folds it into the brief as "What the reference images show".
- **images**: `IMAGE`. The input, passed through unchanged, so the same frames can go on to the Promptor's `first_frame` or a save node.

## Reverse prompting an existing clip

Video loader -> Video Forensics (`images`, `fps`, `audio`) -> this node (`contact_sheet` to `images`, `evidence` to `evidence`, focus `event chain (timestamped)`) -> Promptor (`vision_context`). The Promptor writes the event chain into `integrated_multimodal_description` with cut clauses at the measured times, the sound events into `overall_soundscape` and the music verdict into `non_diegetic_music`. Nothing about the prompt grammar changes: the result is the same official three-field (or Ref2VA six-field) structure the checker validates, not a separate template.

When no evidence is wired with the event chain focus, the model is told to take times from the frame labels only and to say so, which is a fair fallback for a clip with no audio.

## Example

Focus `event chain (timestamped)`, one contact sheet of a 4 s clip, evidence listing a hard cut at 00:02.000 and a sound peak at 00:02.000. The model writes, in prose, that a hand reaches for a light switch through 00:01.500, the picture cuts at 00:02.000 to a lit room with the click accounting for the peak, and the subject turns to camera by 00:03.500. The Promptor's report then shows the cut at 00:02.000 inside the 4 s budget and a clean grammar check.
