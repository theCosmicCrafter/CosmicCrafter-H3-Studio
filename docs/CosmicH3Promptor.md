# Cosmic Video | MiniMax-H3 Promptor

**Category:** `Cosmic/Video/H3`

## Description

Writes a MiniMax-H3 prompt from a one-line idea with a local or cloud language model, then checks the result against H3's own grammar (field order, shot numbering, strictly increasing cut times, `<d>` dialogue tags, voiceover lips-closed rule, soundscape and music budgets) and repairs what has only one correct answer. Everything else is named in the `report` output so a bad prompt is caught before a render, not after it.

## Inputs

- **idea**: What you want to see. One sentence is enough; the model expands it into the full field structure.
- **task**: `Auto` reads what is wired: nothing = T2VA, first_frame = I2VA, last_frame alone = L2VA, both = FL2VA. Or force one.
- **seconds**: Target duration. Cut times are checked against it. A stated length renders on H3's 17k+5 frame grid, rounded up (5.0 s is 124 frames).
- **shots**: How many shots to write. FL2VA prefers 1 so the model can interpolate between the two frames.
- **provider** / **model**: Where the writing model runs (ollama and lmstudio are local; openai, anthropic, gemini need a key). Blank model picks the first the provider lists.
- **style**: Forces one of H3's named looks into Shot 1; the default lets the idea decide.
- **dialogue**: OFF forbids `<d>` spoken lines and the checker enforces it.
- **shot**: A named camera recipe folded into the camera guidance (see below). Default `none`.
- **vision_context**: Output of the Vision Analyzer, folded into the brief so the prompt matches the references.
- **endpoint**, **api_key**, **temperature**, **seed**: Provider plumbing. Prefer environment variables for keys.
- **first_frame**, **last_frame**: Reference images; they also drive `Auto` task detection.

## Outputs

- **prompt**: `STRING`. The H3 prompt, repaired where repair was unambiguous.
- **report**: `STRING`. What was fixed, every grammar issue left over, and a shot warning when the chosen recipe needs more frames than `seconds` renders as.
- **task**: `STRING`. The task type actually used.

## Camera shots

The `shot` combo steers Shot 1's camera move toward one of fourteen recipes. Each is built only from the motion types, amplitudes and speeds in MiniMax's own camera table (motion type + amplitude + speed), so nothing here is outside the documented vocabulary. The frame counts are the shortest clips the recipes are known to land in at 24 fps, from community test renders of one subject in one scene, with small stated sample sizes. Treat them as floors, not promises.

| shot | built from | frames | what the opening frame needs |
|-|-|-|-|
| crash zoom | Zoom In, large amplitude, fast speed | 124 | wide, so the snap has range; ends tight |
| yo-yo zoom | Zoom Out building from slow (no modifiers), then Zoom In, large amplitude, fast speed | 192 | tight close-up at both ends; the hold length is the model's; a zoom out at one steady fast speed has no snap-back shape |
| dolly zoom | Push In with Zoom Out at the matching rate | 124 | the medium framing it ends on; no amplitude or speed words |
| super dolly in | Push In, large amplitude, fast speed | 124 | extreme wide, subject tiny in the distance, one large foreground object each side |
| eyes in | Push In, large amplitude, slow speed | 124 | medium; the destination is one eye, named |
| aerial pullback | Pull Out with Pedestal Up, large amplitude, fast speed | 124 | tight; ends wide with the whole location in view |
| crane rise | Tracking Shot with Pedestal Up and Tilt Down, large amplitude, fast speed | 124 | low beside a moving subject; ends high overhead |
| orbit 360 | Arc Shot, large amplitude, fast speed | 124 | medium on a loose, stationary subject; both modifiers required |
| handheld | Shake Strongly with Tracking Shot, fast speed | 124 | medium on a subject moving fast enough to earn the shake |
| whip pan | Pan Right (Pan Left is in the guide, not rendered in the survey), no amplitude or speed words; the named landing point drives the move | 124 | medium; name the subject it leaves and the subject and place it lands on, and say it stays there |
| dutch angle | Roll Counterclockwise (Clockwise untested) | 124 | medium with visible verticals; the roll lands and holds |
| rack focus | Static Shot, focus change described | 124 | medium-wide with two depth planes and a reason to shift |
| snorricam | Tracking Shot fixed to the subject, described | 124 | tight head-and-shoulders on a straight, plain walk |
| split screen | Static Shot in three panels, described | 192 | three equal vertical panels, black gutters; only the order is yours |

Three recipes (rack focus, snorricam, split screen) have no motion primitive of their own in the guide; they are written as a static or tracking shot plus a description of the result, which is what the renders responded to. A dolly zoom in the other direction (Pull Out with Zoom In, background flattening instead of stretching) has been rendered but on weaker evidence, so it is not tabled.

Pick `seconds` to fit the recipe. The widget steps by 0.5 s and a stated length rounds up onto the grid, so 4.5 s already renders as 124 frames and fits the twelve 124-frame shots (the default 5.0 s does too); yo-yo zoom and split screen need 7.5 s, which renders as 192. The `shot` tooltip states the same two thresholds, computed from the table. Choosing one that does not fit still writes the prompt, and the report says so.

## Example

Idea "a runner crosses an empty car park at dawn", `shot` = `crane rise`, `seconds` = 5.0. The brief tells the model to open Shot 1 at ankle height beside the runner and write the camera as a tracking shot beside the runner with large amplitude at fast speed that pedestals up and tilts down as it travels, ending directly overhead with the runner centred and sharp. The framing note asks for the face as an arc, so the model writes something like a tight frown loosening into a grin by the time the camera is above, rather than one held expression.
