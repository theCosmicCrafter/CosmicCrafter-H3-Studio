# External Timeline preparation (version 1)

For headless productions that need no caller-authored graph, start with
`GET /h3c/api/v1/capabilities` and [Timeline API v1](TIMELINE-API.md).
Server-configured profiles own its complete graph, revisions and durable jobs.
The instructions bundle supplies its guide as `timeline-api` and its stdlib
client under additive `clients`. The graph preparation/client contract below
remains available for existing productions and acknowledged attempts.

Start with `GET /h3c/timeline/instructions` before authoring. Its versioned JSON
includes the public agent skill pack (`skill` is its entry, `h3-continuity-video`, and
`skills` lists every skill of the pack as `name` and `body`, entry first), native base/reference guide bodies when installed (otherwise an explicit missing-guide message), shared
writing/transition direction, this contract, audio/text guides and a complete
Whisper/source-in-30 preparation example. Remote callers read `guides[].body`
and `examples[].body` directly; repository links are optional local conveniences.
The bundle's `client.body` contains the complete stdlib Python client; save it
using `client.filename` to run the same client without repository access.
`revisions` matches preparation, while `instructions_revision` and
`bundle_sha256` identify the instruction bundle and its exact content.

Use `GET /object_info` to inspect the host's installed node schemas and choose an
existing working H3 API graph. The standard HTTP calls below are relative to the
exact ComfyUI base URL (including a reverse-proxy path, if any). No Story, writer
provider, or consumer-specific integration is needed.

`POST /h3c/timeline/prepare` prepares any consumer's native H3 Timeline without a
Story node, Guide node, provider, canon, or particular creative brief. Python
callers can use `h3_continuity.timeline_prepare.prepare(body)` with the same
contract. Preparation reads explicitly supplied local asset bytes, checks their
SHA-256 hashes, and returns owned graph copies. It never uploads, fetches URLs,
decodes media, loads models, invokes writers, queues prompts, saves workflow
state, or creates a sequence directory. The HTTP handler offloads preparation
to a worker thread.

```json
{
  "version": 1,
  "name": "caller-sequence",
  "timeline": {"version": 1, "prompt": "", "boxes": [
    {"id": "opening", "frames": 192, "prompt": "A paper boat crosses a moonlit canal."}
  ]},
  "settings": {"width": 1344, "height": 768, "context_frames": 39,
    "carry_audio": true, "ref_image_size": "match"},
  "workflow": {
    "api": {"20": {"class_type": "H3C_Timeline", "inputs": {}}},
    "timeline_node": "20"
  },
  "assets": [],
  "semantic_boxes": {}
}
```

Supply your complete ComfyUI API graph for actual production. The small example
and [four preparation fixtures](../tests/fixtures/external_timeline/) demonstrate
planning only; they do not load an H3 model or contain a sampler/save pipeline.
Preparation retains the whole supplied graph, including model, sampler,
adapter, output ancestry, and flat `images.imageN` / `audios.audioN` links.
Connected references may come from arbitrary computations. Such connections
have no fabricated staged-file hash. Preparation certifies planning, not that
every node in the caller's graph will execute or that the generated lettering
will match its requested appearance.

## Settings and editable workflows

`workflow.ui` is optional. Version 1 accepts current root flat workflows only,
with matching Timeline API/UI node identity and exactly seven positional
widgets: `name,width,height,context_frames,carry_audio,ref_image_size,timeline`.
If `widgets_values_named` is present, its corresponding values must agree.
Preparation patches both representations and preserves canvas and unrelated
metadata. Custom/legacy layouts and subgraphs return an explicit error. API-only
requests remain usable.

Supplied UI connections must match API connections at the owned Timeline
widgets and flat reference sockets, linked setting producers, and bound loader
filename inputs. Validation checks each input's link pointer, root link record,
and source output; missing, extra, conflicting, bypassed or muted connections
fail precisely. Updating a dormant widget cannot override a conflicting link.

Width and height are integer multiples of 32 in 32..16384. Context is 22, 39, 90,
or 141 frames (API combo values are strings). Carry audio is boolean; reference
image size is `match` or `max`. Omitted settings retain effective template
values. Missing API settings use native defaults 1344, 768, 39, true, `match`.
Present graph-computed settings never fall back to defaults.

Linked settings are readable only from output 0 of `PrimitiveInt`,
`PrimitiveFloat`, `PrimitiveBoolean`, `PrimitiveString`,
`PrimitiveStringMultiline`, or `CustomCombo` (literal `choice`). Primitive
`value` must have the producer's exact type; float output cannot satisfy integer
geometry. Computed values, linked primitive values, wrong output indices and
unknown producers fail without execution. Omitted/equal settings preserve their
links. For an unequal override, explicitly name its exact writable primitive:

```json
{"workflow":{"settings_bindings":{"width":{"node":"41","input":"value"}}}}
```

The existing Timeline link must be `["41",0]`; only that producer's literal
`value` changes. CustomCombo writes are unsupported. A supplied primitive UI
uses `value` at index 0 and retains companion widgets. PrimitiveInt's
`control_after_generate` must be `fixed`. Conflicting setting values sharing one
producer fail, including omitted settings that would otherwise change. Linked
Timeline name/JSON and linked loader filenames cannot be silently detached.
CustomCombo setting producers are supported in API-only requests. Their dynamic
UI layout is unsupported in version 1 and returns a precise producer error even
when its displayed choice matches the API. Use API-only preparation or a
compatible primitive/literal control when supplying an editable UI graph.

## Assets and explicit destinations

An optional manifest entry is:

```json
{"file":{"type":"input","subfolder":"references","filename":"portrait.png"},
 "sha256":"64 hexadecimal digits",
 "bindings":[{"kind":"loader","node":"31","input":"image","slot":"image9"}]}
```

All files must exist inside their selected ComfyUI input/output/temp root after
real-path resolution. Absolute paths, traversal and symlink escapes fail. All
hashes are verified before destination patches; missing files and hash mismatches
are errors. Several explicit bindings may share one file. Multiple writes to
one destination fail, even for identical bytes. Destination selectors are:

| Kind | Selector | Existing target |
| --- | --- | --- |
| `loader` | `node`, `input`, `slot` | `LoadImage.image`, `LoadImageOutput.image`, or `LoadAudio.audio`; the exact flat Timeline slot must link directly to loader output 0 |
| `audio_clip` | `slot` | One `timeline.audio_clips[]` entry; writes `file` |
| `plate` | `id` | One `timeline.plates[]` revision; writes `image` |
| `guide` | `box`, positive integer `shot` | One box's `previews[]` item; writes `guide` |
| `picture` | `slot` from `image17` up, optional text `title` | The `timeline.pictures[]` entry in that slot, added when missing; writes `file` (see [Long edits](#long-edits-exact-boxes-and-saved-pictures)) |

Loader values use relative paths plus the ComfyUI type annotation, for example
`references/portrait.png [input]`. Shared loader consumers necessarily observe
the same filename. Lanes are never created or retimed: preserve `start`,
`source_start`, `duration`, `description`, `layer`, and `in_full_video`. An
enabled lane cannot have both a file and a connected audio socket. Reference
disablement follows native Timeline rules.

Plates and timed guides require safe PNG descriptors in **output/h3_previews**.
Stage external timed PNG guides first using the existing explicit ComfyUI image
upload endpoint, a content-addressed filename, and overwrite disabled. Preparation
does not perform that upload. `shot` is a saved preview number, not an array
index; its existing local `frame` is checked by native `frame_guides` including
shared-boundary conflicts. Accepted descriptors may contain the paired
`visible_text` and `text_contract` metadata. Pass both with the accepted image;
preparation preserves the pair on a same-file replacement, validates its shape,
and checks its text compatibility where native rendering uses it. It does not
certify the pixels' lettering.

## Native and optional semantic authoring

Native `boxes[].prompt` accepts arbitrary H3 prompts. Logical `@imageN` /
`@audioN` mentions remain in saved Timeline JSON. Rewritten native tags and
inserted visible-text windows are inspection outputs only. Shared Timeline
direction may augment either authoring mode.

`semantic_boxes` optionally maps an existing unique box ID to
`{version:1,references:[...],prompt:{...},analysis:{...}}`. The selected references
and native endpoints determine the pure `PromptContext`, snapped generation
budget, and compiler mode. `analysis` is required by Ref2VA and absent in other
modes, following the existing semantic schema. A nonempty native prompt and
semantic authoring for the same box fail. Other native boxes need no semantic
input. [Semantic text](../tests/fixtures/external_timeline/semantic-text.json) and
[semantic references](../tests/fixtures/external_timeline/semantic-reference.json)
show complete data-only compiler inputs.

H3 owns these box keys: `id`, `frames`, `seconds`, `exact`, `prompt`, `seed`,
`cut`, `new_scene`, `first`, `last`, `memory`, `memories`, `previews`,
`plate_changes`, `plate_edits`, `cast`, `schedule`, `join`, `source`, and
`layers` and `switch` for a clip with several videos (see
[Videos in one clip](TIMELINE-VIDEO-LAYERS.md)).
Prepare keeps any other key on a box as it is, so keep your own metadata, such
as where a cut comes from in your edit, under another key, for example `edit`.
`source` holds what H3's Story wrote for a box, so Prepare refuses one the Story
didn't write, at `timeline.boxes.N.source`. At the top level, H3 also owns
`bridges` and `render_bridge`; see [Bridges](#bridges), and `render_layer`.

With `cut: true`, `memory: "scene"`, `"cast"` or `"selected"` also supplies the
full preceding video's original latent as a reference. The target starts fresh,
so this context does not freeze opening frames or turn the cut into a continuation.
`new_scene: true` retains visual history while the incoming prompt defines the
new setting, time and appearance. Existing scene/Cast anchors and explicit
selected moments supplement the preceding video. Render that source first;
retaking it invalidates boxes that remember it. `memory: "off"`, including the
legacy omitted default, disables these references.

## Long edits: exact boxes and saved pictures

A box with `"exact": true` plays exactly its `frames`: 1 to 362 for a box that
starts fresh, and 1 to 362 minus `context_frames` for a box that continues the
one before it (`limits.exact_frames`). H3 generates the smallest length on its
frame grid that holds them, 17k+5 fresh (at least 22) or 17k continuing (at
least 17). The box keeps its first `frames` frames and the rest are dropped.
`exact` must be `true` or `false`; a box without it snaps to the grid as before.

| Played | Generated | Dropped |
| --- | --- | --- |
| 9 (fresh) | 22 | 13 |
| 30 (fresh) | 39 | 9 |
| 96 (fresh) | 107 | 11 |
| 22 (fresh) | 22 | 0 |
| 40 (continuing) | 51 | 11 |

A box that drops frames can't be continued: the next box must be a cut, or there
must be no next box. Otherwise preparation fails at the box with a message such
as "box 1 drops 13 generated frames, so box 2 can't continue it: make box 2 a
cut, or give box 1 a length on the grid (22 frames), which moves every later
box". Prefer the cut, which keeps every length. An exact length on the
grid drops nothing, so the next box may continue it. Box starts, timed text,
audio lanes, guides and memory use the played length, and the saved segment,
its audio and the full video keep only the played frames.

A box that continues another carries `context_frames` frames from it, so a box
that starts fresh must play at least that many to be continued. Preparation
accepts a Timeline that breaks this, but rendering stops at the continuing box
with a message such as "box 2 continues box 1, which plays 22 frames, fewer
than the 39 it carries: make box 2 a cut, or give box 1 at least 39 frames,
which moves every later box".

```json
{"boxes": [
  {"id": "cut1", "frames": 9, "exact": true, "first": "image140", "prompt": "..."},
  {"id": "cut2", "frames": 30, "exact": true, "cut": true, "first": "image141", "last": "image142", "prompt": "..."}
]}
```

Saved pictures are `timeline.pictures[]` entries `{slot, file, title}` in slots
from `image17` up, with no upper limit (`limits.saved_picture_slots`). The
Timeline node's wired inputs stay `image1` to `image16`, and each box still
sends H3 at most 9 pictures. Stage each picture first through ComfyUI's image
upload endpoint, for example into `input/h3_pictures`, then bind it:

```json
{"file":{"type":"input","subfolder":"h3_pictures","filename":"harbour.png"},
 "sha256":"64 hexadecimal digits",
 "bindings":[{"kind": "picture", "slot": "image140", "title": "Harbour"}]}
```

The binding adds the picture to `timeline.pictures`, or replaces the file of the
picture already in that slot; without a `title`, an existing picture keeps its
own. Box `first` and `last` fields, mentions, the bible and `disabled_refs` can
then name the slot. A slot below `image17` fails with "picture binding needs a
saved slot from image17 up".

## Continuity settings for long chains and repaints

Four optional Timeline fields, off by default. Each changes only continuing boxes (or, for `video_slices`, the boxes that mention the slot), and a set value marks those boxes for a new render.

| Field | Value | Effect |
| --- | --- | --- |
| `context_noise` | `true` | Paired context noise on the carried frames: less texture build-up ("burn") over long continuing chains, about 10% more time per continuing box. |
| `continuation_guide` | `false` | No guide from the previous box's last frame at the first new frame; removes a ~3-frame hold at joins in moving shots. |
| `audio_feather` | 0-16 | The last N carried audio ticks regenerate, rising by cosine from frozen to free. |
| `video_slices` | e.g. `["video1"]` | Each box receives only its own Timeline window of that reference video (its start minus the carried frames, through every generated frame) and of its same-numbered soundtrack. |

## Bridges

A top-level `bridges` list adds a few generated frames on the join before a box
that starts fresh, turning that hard cut into a generated move without
rendering either box again (see [Bridges](TIMELINE-BRIDGES.md)):

```json
"bridges": [{"before": "box4", "frames": 29, "seed": 4410, "prompt": "..."}]
```

`before` is the id of the box the bridge leads into. That box must come after
box 1 and have `cut` or `new_scene`, and one bridge at most leads into it.
`frames` is 12, 29 or 46 (`limits.bridge_frames`). `seed` is a whole number
from 0 to 18446744073709551615; without one, it is the CRC-32 of `bridge:`
followed by the box id, and Prepare writes it back. `prompt` is text, sent
after the shared prompt. A bridge sends H3 no pictures, references, guides,
timed text or memory, so each mention reads as the described subject or
sound. Prepare refuses a wrong entry at `timeline.bridges.N`, for example
"bridge 1 leads into box 2, which continues box 1: a bridge needs a box that
starts with Cut or New scene" or "bridge 1 has 30 frames; a bridge has 12, 29
or 46".

A bridge renders once both its boxes are rendered. It carries the end of the
box before from its saved latents and freezes the start of its own box, so a
29-frame bridge with 39 context frames is a 107-frame run. A run with no box
left to render renders the first bridge, in Timeline order, that needs a
render. To render one bridge, set `render_bridge` to its box's id in the
queued copy only, as `render_box` is set; a run with both fails with "a run
renders one box or one bridge: drop render_box or render_bridge". A bridge
that can't render fails the run with the reason, such as "render box 3
first", or with its problem, such as "box 3 drops 9 frames, so the bridge
before box 4 can't start from its last frame: give box 3 a length on the
grid" after an exact box that drops frames.

The status gets `bridges` only when the Timeline has any: one item per bridge,
in Timeline order, with `box`, `status`, and `note` and `video` when they
apply. `box` is the id of the bridge's box. `status` is `done`, `next` (the
first that needs a render, once every box is done), `pending`, `waiting` (a
box it joins isn't done) or `problem`. `note` says why the bridge isn't done,
and `video` (`file`, `frames`, `fps`) is its saved take. The top-level `next`
stays the next box or `null`, and the message adds, for example, "The bridge
before box 4 is next."

No box gets longer: box starts, `delivered_range`, timed text, audio lanes and
the saved segments stay as they are. Only the full video grows. It plays each
`done` bridge before its box, and the status's `seconds` includes those
bridges' frames. A bridge that isn't `done` is left out, so its join plays as
a hard cut.

The example client renders boxes only, with `render_box`, so a bridge in a
prepared Timeline renders on a plain run once every box is done, for example
with Render next in the Studio. The client's final check adds the frames of
the status's `done` bridges to the boxes' frames. Leave `render_bridge` out of
the Timeline you prepare.

## Response, identity, and errors

Success is HTTP 200 with `ok:true`, `version`, `name`, normalized `timeline` and
`settings`, copied `workflow` (including optional UI), verified `assets`,
`boxes`, `revisions`, and a SHA-256 `fingerprint`. Normalization retains requested
box frames and opaque consumer metadata; native defaults such as seeds and box
flags become explicit. Each inspection box contains:

- `id`, one-based `index`, native `mode`, and logical-slot-to-native `tags`;
- `frames` (snapped, or as requested for an exact box), `carried`, and
  `generated` frame counts;
- half-open absolute movie-frame `delivered_range`, `generated_range`, and
  `carry_range`, at 24 fps; generated origin is delivered start minus carried,
  and `generated_range` spans `generated` frames, so it shows dropped frames;
- `effective_prompt`, native `text_window`, actual timed `guides` with generated
  frame positions and file descriptors, and technical `notes`.

For example a 96-frame first box delivers 90 frames; a 96-frame continuation
delivers 102. With 39-frame context their movie ranges are `[0,90)` and
`[90,192)`, while the continuation generates `[51,192)` and carries `[51,90)`.
An exact 96-frame first box delivers 96 and generates 107: `[0,96)` and
`[0,107)`.

The fingerprint covers normalized name/Timeline/settings/API, canonically
ordered verified assets/bindings, and preparation/schema/guidance revisions.
UI canvas data is excluded. Timestamp bookkeeping keys (`timestamp`,
`timestamps`, `created_at`, `updated_at`) and absolute host provenance values
under `path`, `local_path`, or `absolute_path` are excluded recursively.
Creative prompt, direction, and cue strings stay verbatim, including strings
that happen to resemble paths. Other opaque metadata participates. Identical
preparation is deterministic; no wall-clock time or filesystem mtime is added.

Invalid requests return HTTP 400 and
`{ok:false,errors:[{path,message}]}`. Paths identify request/graph/asset/box
boundaries and native validation messages explain the technical problem.

## Complete Whisper attachment and sparse references

The bundle's `whisper-source30` example (local file
[`examples/whisper-source30.json`](../examples/whisper-source30.json)) is a complete
**preparation** body with three boxes, a normalized attachment, synchronized
audio1 and a computed IMAGE linked to the sparse logical slot `images.image9`.
The example uses a generated solid image as an executable reference computation;
replace that computation with the user's visual reference. `LoadAudio` names a
caller-staged `reference.wav`. Its exact original Whisper JSON bytes are included
as the string `timeline.consumer.whisper_source_json`, and their SHA-256 is the
attachment's `source_sha256`. That string has no trailing newline. This provides
a reproducible import example without guessing a transcript hash.

Like the other fixtures, it is planning-only. For rendering, copy its Timeline,
settings and reference links into a complete working H3 graph, preserving its
models, sampling and decoding. Link `audio_vae` when conditioning on audio. Stage
real assets through the host's existing upload workflow and bind their verified
descriptors/hashes via `assets` when applicable. A computed image is a real IMAGE
connection, with no invented file hash; preparation cannot certify its later
pixels. A loader binding must point directly to its Timeline socket. If an
image passes through a computation, preserve that ancestry and its loader input.
Version 1 cannot bind or verify that upstream file through the computation:
every manifest entry requires a supported explicit destination; `bindings: []`
is rejected. Verify upstream sources in the consumer's own staging process.

If `timed_text.audio_sha256` is supplied, preparation requires a verified asset
bound to the selected `audio_slot`'s lane file or directly connected `LoadAudio`
source and compares the digest without regard to hex casing. A mismatch or
unverifiable source fails at `timeline.timed_text.audio_sha256`. Omit this optional
claim for computed audio whose source bytes cannot be verified; preparation does
not invent a hash for computed media.

This is the full normalized `timeline.timed_text` shape used by the example:

```json
{
  "version": 1,
  "source_name": "whisper.json",
  "source_sha256": "f5db6a4de4eea1734cd6d8104416240a2af687868ade21824848d12412cc58f1",
  "enabled": true,
  "sync_audio": true,
  "audio_slot": "audio1",
  "start": 0,
  "source_start": 30,
  "duration": 12,
  "direction": "Large ivory lettering remains readable against charcoal, softly appears at each onset and clears at its end; preserve exact punctuation.",
  "cues": [
    {"id": "cue1", "start": 30, "end": 32, "text": "Hold the light."},
    {"id": "cue2", "start": 33.5, "end": 34.5, "text": "Keep walking."}
  ],
  "words": [
    {"id": "word1", "start": 30, "end": 30.5, "text": "Hold"},
    {"id": "word2", "start": 30.5, "end": 31, "text": " the"},
    {"id": "word3", "start": 31, "end": 32, "text": " light."},
    {"id": "word4", "start": 33.5, "end": 34, "text": "Keep"},
    {"id": "word5", "start": 34, "end": 34.5, "text": " walking."}
  ]
}
```

Attach it alongside these lane and box records, retaining each box's authored
native prompt (the bundled example supplies complete six-section Ref2VA prompts):

```json
{
  "audio_clips": [
    {"slot": "audio1", "start": 0, "source_start": 30, "duration": 12,
     "description": "Rhythm reference", "layer": "music"}
  ],
  "boxes": [
    {"id": "opening", "frames": 96, "prompt": "..."},
    {"id": "continue", "frames": 96, "prompt": "..."},
    {"id": "cut", "frames": 96, "cut": true, "new_scene": true, "prompt": "..."}
  ]
}
```

Supply `source_duration` when known: the full recording duration in seconds, not
the placed window length. It must be finite and positive. Older records without
it remain valid; the Studio reads the duration from the audio file before
enabling source trimming. See [Timeline audio](TIMELINE-AUDIO.md#imported-audio-metadata).

An audio lane needs either a `file` descriptor or the flat `audios.audio1`
connection, never both while enabled. Sparse inputs use ordinary API links:
`"images.image9":["32",0]`, `"audios.audio1":["40",0]`. Preserve these logical
names; preparation's `boxes[].tags` reports their native per-box numbering.
Reference selection follows prompt mentions, selected endpoints and native
limits. `first` / `last` box fields select an image slot as an endpoint; generic
appearance references remain mentions. Read the locally installed `base` guide, or the official MiniMax documentation, for
T2VA/I2VA/FL2VA/L2VA structure and `ref` for all six Ref2VA sections. These guides
are the maintained source of native syntax, shared with H3 Story.
Timeline inspection uses `t2va`, `flf2va` (first/last-frame variants), and
`ref2va` as its runtime mode names; the base guide names individual endpoint
patterns I2VA, FL2VA and L2VA.

All attachment/lane times above are **seconds on their named clocks**. Required
attachment fields are shown; `words` and an `audio_sha256` are optional. Both SHA
fields, when present, are 64 hexadecimal characters. Hash original transcript
bytes before decoding/normalizing. Keep cue/word text verbatim, including leading
spaces, punctuation and original language. IDs must be nonempty and unique
within each list; times finite and nonnegative, end strictly after start.
Intervals are half-open. `direction` controls native visual treatment separately
from transcript content. H3 control tokens such as `<d>`, `<|...|>`,
`<scenetrans>` and `<cutoff>` cannot be literal transcript text.

Whisper input dialects accepted by the local pure helper
`h3_continuity.timed_text.import_whisper(data, source_name, source_sha256)` are:
`segments` (including nested `words`), top-level `words`, `chunks` using
`timestamp:[start,end]`, or a raw timing array. Items use `text`, `word`, or
`value`; original times/text become normalized `cues`/`words`. No HTTP import
route is needed: external callers can create the normalized structure above.
Import never invents missing word times or speaker assignments. The helper
initially produces an independent clock; set `sync_audio`, `audio_slot`, and the
preserved independent clock deliberately afterward.

With sync enabled, the selected lane's `start`, `source_start`, and `duration`
are authoritative: `movie = lane.start + source - lane.source_start`. Thus
[30,32) becomes movie [0,2), and [33.5,34.5) becomes [3.5,4.5). The saved 96-frame
boxes snap to delivered ranges [0,90), [90,192), [192,282) at 24 fps. The actual
first continuation boundary is **3.75 seconds**, not the requested 4 seconds.
The second phrase crosses it. With 39 carried frames the continuation generates
[51,192), beginning at 2.125 seconds, and its phrase window is [1375,2375) local
milliseconds with `continuing:true`. In the outgoing box the phrase has
`continues_after:true`: its clipped local end is the box boundary, rather than a
request to clear the lettering. This flag uses the audio/text selection-bounded
source interval and participates in render identity. Exact boundary endings have
`continues_after:false`. The first phrase has already ended before
that generated window. A phrase ending within replay is marked `replay_only`;
keep the renderer's replay contract so it is not restarted in new delivered
frames. The third box is a hard cut at movie 8 seconds, carries zero frames, and
has no active phrase from this example. These are inspection semantics, not a
guarantee that pixels meet exact timing.

Independent text clocks use the attachment's own three clock fields. When
turning sync off, first copy the currently resolved lane clock into those fields
so the effective placement stays unchanged. A missing synced lane produces an
unresolved window; disabled audio conditioning does not disable text. Phrase
cues drive visible lettering; optional exact word timing is retained for
inspection and authoring. Visible text is inserted into native visual prompts,
separate from audible `<d>` dialogue/lyrics. No subtitle overlay is generated.

## Rendering and durable resume

Save the successful preparation response as `prepared.json` and run:

```sh
python examples/external_timeline.py prepared.json --base-url http://127.0.0.1:8188 --production my-film --receipt receipts/my-film.json --output-directory rendered
```

Remote callers who saved `client.body` as `external_timeline.py` use
`python external_timeline.py` with the same arguments.

Use a unique stable sequence name (for example a production label plus a
persisted UUID suffix) and retain it across resumes. Sequence names are 1–64
native-safe characters; different consumers share the server's sequence folders.
The client requires exactly one native `H3C_SaveSegment` directly receiving the
target Timeline's `segment` output 3, with sampled latent and decoded IMAGE
ancestry connected to that Timeline, 24 fps, and full-video writing enabled.
Timeline outputs are positive 0, negative 1, latent 2, segment 3, seed 4, prompt 5,
info 6. Preserve your working sampler/model/decode graph; this example does not
select models. Its connection check is structural, not a ComfyUI execution test.
Custom save pipelines can use preparation and adapt their own execution client.

The synchronous standard-library client copies the prepared graph per box,
sets only the target Timeline JSON's one-based `render_box`, and serializes:

1. Read normalized status via `POST /h3c/timeline/status` with `{name,timeline,settings}`
   (`timeline` is JSON text). A new receipt requires an empty sequence.
2. Atomically persist submit intent, then make **one** `POST /prompt` with
   `{"prompt": API_GRAPH}`. Persist the server's acknowledged `prompt_id` before
   polling. No caller-supplied ID or retry can provide exactly-once delivery.
3. Read `GET /history/{prompt_id}`. If absent, match the ID at queue tuple index 1
   from `GET /queue`, and compare its graph at index 2. If absent there, re-read
   history to close the completion race. Absence everywhere is ambiguous.
4. Error/interrupted history wins over partial outputs, even with
   `completed:false`. Successful history requires `status_str:"success"`,
   `completed:true`, the matching submitted graph, and no error event.
5. Read fresh Timeline status after success. Discover each `video.file` and
   `full_video` descriptor there, then retrieve URL-encoded `/view` bytes and
   SHA-256 them. SaveSegment's human output text and pre-save Timeline history
   status are not output-discovery contracts.

Repeat the **same command** after a timeout or client disconnect. The receipt
binds production, exact normalized host/port/base path, sequence, Timeline ID,
normalized Timeline/settings/API/assets, preparation fingerprint/revisions, and
each submitted graph. Only `render_box` is excluded from the stable input
selection. Changed input/identity or corrupt receipts fail before queueing.
Completed attempts retain attributed terminal evidence and recheck fresh status
and downloaded artifact hashes on resume. Immutable staged assets are also
rechecked through `/view`; graph-computed pixels remain an execution-time limit.

A `submitting` receipt without an acknowledged ID means the server may have
accepted the job. Stop and reconcile manually; the client never retries that
POST. Likewise an acknowledged ID lost through server restart, history retention
or deletion is ambiguous without already persisted terminal evidence. Preserve
the receipt and inspect server records/queue/outputs before deciding on a new
production or take. A failure remains a recorded failure on resume.
(The managed [Timeline API v1](TIMELINE-API.md) persists terminal native evidence
on its attempts and offers a human-attested POST `/jobs/{id}/abandon` for a held
job; see "Held jobs, cancel and abandon" there. This stdlib client has no such
route: it records the decision only in your receipt.)

The receipt uses same-directory temporary writes, flush/fsync and atomic replace.
A host+sequence `O_EXCL` lock in its directory serializes cooperating local
clients. A crash may leave that lock: inspect the recorded PID and reconcile the
receipt before manual removal. Locks never expire by age. Different directories
or machines do not share this lock, so unique sequence names and a single owner
remain necessary. Keep the receipt directory on a filesystem with reliable
exclusive create/atomic replace. The client refuses redirects and arbitrary
artifact hosts; use the exact ComfyUI base URL. HTTP and poll deadlines are
bounded. It never cancels, frees models, uploads or writes workflow state.

Final completion requires every expected box in order, fresh done status, each
box's prepared `frames` at 24 fps, `done == segments == box count`, `next:null`, zero
trailing segments, matching total duration (the boxes' frames plus each `done`
bridge's), and a retrievable full MP4. A partial
prefix may already have `full_video`; that alone is not completion. Receipt
frame counts come from verified segment metadata and total status duration;
this stdlib example retrieves/hashes bytes but does not decode or independently
count MP4 frames. Media is hashed in bounded chunks with optional atomic downloads. Omit
`--output-directory` to verify without saving a second local copy.

Native render validation and creative acceptance are separate: review actual
spelling, readable intervals, onset/clear timing, motion/transition state, and
decoded frame counts. Reference audio conditions H3. An uploaded clip with
`"in_full_video": true` makes the full video play the recording instead of H3's
audio (see `timeline-audio`); mixing it with H3's audio belongs to the consuming
workflow.
