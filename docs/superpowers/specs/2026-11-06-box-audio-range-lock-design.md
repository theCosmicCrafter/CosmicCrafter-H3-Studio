# Lock audio to boxes

Status: approved by the user on 2026-11-06 ("Approved"); Native implementation subsequently authorized. Work is isolated on `design/box-audio-range-lock`, created from local `main` at `b7eaedc` before any file edits. No push, merge, release, deployment or model render is authorized.

Builder review found one product conflict: enabling on a lane whose selected continuous soundtrack already crosses an inserted bridge. Preserving its current box reference windows and introducing silence at that bridge cannot also preserve its assembled soundtrack. The user delegated this choice to the author. Resolution: block enabling only when it would change existing selected soundtrack playback, identify the conflicting bridge(s), and leave the Timeline untouched. This preserves the already-approved enabling invariant. There are no unresolved behavior questions from that review.

## Intent and scope

Keep each box synchronized with its assigned part of a recording while the author changes the surrounding Timeline. A duration edit or inserted box must not make every later box hear a different part of the recording.

This is a coordinated feature across Timeline editing, native audio conditioning, source-time annotations and soundtrack assembly. It is not an independent audio-clip editor. Use one recording and shared lane settings, with non-destructive source windows attached to stable box IDs. Never write sliced audio files or change playback speed to achieve the binding.

## Approaches considered

1. **Box-bound source windows, selected by the user.** Preserve one recording and its lane settings; bind source ranges to boxes and display the resulting segments. This solves downstream drift without separate controls for moving, trimming or replacing every segment.
2. **Independently editable clips within a lane.** More editing freedom, but adds a broader multi-clip audio editor. The user chose the first approach.

For unlocking, the user chose restoration of the original continuous placement, with confirmation of playback changes and Undo. Keeping detached segments fixed to movie time was considered and not selected because it introduces another audio mode.

## Approved behavior

### Default and enabling

- Add **Lock audio to boxes** per audio lane, off by default for both new lanes and existing saved projects. No project-wide preference is added.
- On enabling, capture exactly the source interval each existing box currently receives, including its local offset if coverage starts partway through that box. Use actual played box lengths, after the existing frame-grid/exact-length rules, rather than requested seconds.
- Preserve any leading/trailing gap within a box. Enabling alone must not change the delivered source audio, speed or soundtrack selection.
- Check enabling eligibility before mutating state. If existing inserted bridges make the candidate bound soundtrack differ from what this lane currently contributes to the selected original soundtrack, block locking and identify the conflicting bridge(s). The author must resolve those bridges explicitly before locking; never remove/convert a bridge automatically. A bridge alone is not grounds for blocking: a reference-only lane, or a bridge outside the effective audio coverage, is eligible when the enabling invariant holds.
- Remember the original continuous placement (`start`, `source_start`, `duration`) for unlocking. Keep shared recording identity, description, layer and soundtrack selection on the lane.
- Display the assigned ranges as separate non-destructive segments at their owning boxes. These segments reuse the source's audio slot; they do not allocate one of the three reference slots per box.

### Editing boxes

- **Extend:** play the original assignment, then contribute silence from this lane beyond that assignment. Never consume audio assigned to a later box.
- **Shorten:** hide the clipped tail without discarding its assignment. Extending again restores that audio before adding silence. Resizing does not recapture ranges from the movie clock.
- **Insert or append:** a genuinely new box starts without an assignment on every already-locked lane. Existing boxes retain their assignments. Adding audio later while unlocked follows existing placement behavior.
- **Duplicate:** copy the picture/prompt behavior of the existing duplicate operation, but do not copy its audio assignments. The original and other boxes remain unchanged.
- **Move:** carry the assignment with the box's stable ID. Source order may therefore differ from recording order after a reorder.
- **Delete:** remove the deleted box's placement. Other boxes retain their source intervals; the source file is unchanged. Undo restores the removed assignment.
- **Split:** partition the original assignment at the logical split, transferring the remaining range and any hidden tail to the second half. No sample belongs to both halves. Later extension of the first half cannot consume the second half's audio.
- Existing normalization, joining and grid constraints still apply. Audio locking must not silently alter box lengths, force exact mode, change cut/continue, or regenerate media.

### Silence and soundtrack selection

Silence is lane-specific: unassigned boxes and padding contribute nothing from that recording. Other lanes remain unaffected. Do not automatically enable **In the full video**, mute whole boxes, or change the existing generated-versus-original soundtrack policy.

When selected for the full-video soundtrack, this lane's gaps are silent in that soundtrack. When used only as a native reference, an empty reference region does not guarantee that H3 generates silent media. Keep that distinction clear in the guide.

### Audio edits and unlocking

- While locked, require unlocking before moving, trimming, fitting, slipping the source window or replacing the lane's recording. Do not turn an attempted source edit into an implicit rebind.
- Shared descriptions, layer, reference enablement and **In the full video** remain editable using existing semantics.
- Unlocking restores the remembered continuous placement, without undoing any box edits.
- If that changes playback, confirm before applying it: **Return to continuous audio? Box-specific gaps and audio ordering will be removed.** Cancel leaves the entire locked state intact.
- Undo restores the full prior bindings, including hidden tails. Redo reapplies the unlock. These are one editor-history action, not one action per box.
- Re-enabling captures fresh overlaps from the continuous lane on the current Timeline; it does not silently revive an older binding snapshot.

### Linked timing and continuity

- Dialogue cues, audio-synced timed text and detected beats follow the same resolved source windows. Do not rewrite original source timestamps, cue words or transcript text. Independently clocked text retains its existing independent timing behavior.
- Preserve existing review/error behavior when an edit cuts through a dialogue cue. No automatic rewriting of speech to make a shortened box fit. Preserve lettering-contract validation.
- An inserted bridge contributes silence from a box-locked lane; later box assignments still begin with their own boxes in the assembled video. Other continuous lanes keep their existing bridge behavior.
- Existing **Locked to the sequence clock** remains a distinct setting and its bridge restrictions still apply. Do not rename or repurpose its saved `locked` field, or relax its restrictions as a side effect of this feature.
- Replacement joins, if supported by the running version, read the underlying windows without adding time. This feature does not enable otherwise unavailable replacement rendering.
- A continuation's audio replay/context comes from the actual preceding Timeline tail, including gaps or reordered source windows. Never fill replay by reading the recording immediately before the current assignment unless that is what the Timeline actually played.
- Stable assignments prevent audio drift, not every dependency change. Continue links, visual memory, joins and changed carried audio can still make later takes outdated. Never promise that later rendered boxes remain current merely because their delivered audio range is unchanged.

## Model and invariants

The exact JSON field names and helper/module boundaries are left to the builder. The following semantics are required:

- Each locked lane has a versioned mapping from stable box IDs to source intervals and box-local offsets. No assignment is a valid state. Presence of an empty locked mapping must be distinguishable from an unlocked continuous lane.
- Preserve the full assigned interval even if part of it is beyond the current box end. The visible/audible interval is the intersection with that box's current played duration. Hidden tails never extend playback by themselves.
- Retain the original continuous placement separately from the current resolved placements. Serialize bindings, hidden tails and lock state; never reconstruct them from current cumulative movie time on reload.
- Resolve current placements from box order, actual played lengths and the assembly's bridge geometry. Source ownership stays stable when movie positions change.
- Allow only one recording per existing audio slot, with multiple placements referencing that same source. Preserve the three-reference limit and existing connected/uploaded source validation.
- All readers use the same placement semantics: conditioning, active references/mode selection, dialogue/text, beats, lane drawing/audition, soundtrack assembly and render/cache identity. Avoid a frontend-only lock or a soundtrack-only fix.
- Use half-open intervals and the existing frame/sample timing utilities. Resolve absolute sample endpoints consistently so adjacent windows do not drop or repeat samples at rates not divisible by 24. Preserve existing sample-rate conversion/mixing policy.
- Validate finite nonnegative times, positive nonempty ranges, unique binding ownership and referenced box IDs. Reject malformed or unsupported binding data explicitly instead of falling back to continuous playback.
- Feature-gate dependent saved Timelines through the existing `requires` contract so older readers fail clearly rather than ignore the binding. Ordinary unlocked files keep their existing behavior.
- Persist through editor history, workflow JSON, project revisions, checkpoints, saved Story state and import/export. Bindings survive all normal save/load paths. A save failure must not leave only part of a lock/unlock transition applied.
- Removing or disabling a lane follows existing source controls; disabling must preserve its bindings for re-enabling. Undo of lane removal restores its bindings with it.

## Author's implementation calls for review

These details follow from the selected behavior and existing project rules; they were not separate user choices:

1. Disable enabling when there are no boxes; explain that boxes are needed before their audio ranges can be captured. Do not create a hidden auto-binding policy for future boxes. For existing inserted bridges, use the playback-equivalence eligibility check above, as settled under the user's delegation of judgment; do not add a second confirmation path that changes audio on enable.
2. A split uses the existing operation's logical source cut, before any extra duration introduced by frame-grid rounding. Keep the existing split timing preview/constraints. Extra grid duration is padding owned by that resulting box, not permission to borrow the neighboring source range. A hidden tail belongs only to the second half. A zero-length omitted half receives no binding.
3. If a bulk edit or Story update retains box IDs, retain their assignments; if it creates new IDs, those boxes are unassigned. Deleted IDs lose their placements. Do not guess correspondence from box index or wording. Operations that merge boxes must explicitly preserve ordered windows/local gaps in the merged owner or reject the operation with an explanation; they must never flatten to one guessed source span.
4. Active reference selection must not leak the full recording into a box with no assigned window, including explicit mentions or another reference pathway. Conflicting audio RefMod/replacement paths must either honor the same windows or reject the unsupported combination clearly. Exact handling should reuse existing source-validation and reference-routing conventions.
5. For simultaneous sequence-clock lock and box lock, keep the sequence lock's existing conservative insertion restrictions and existing requirement for soundtrack selection. Use the coverage envelope from the first through last resolved active placement, including internal gaps; do not accidentally permit every join because windows meet exactly at box boundaries. Do not introduce mutual automatic toggles.
6. File bytes are never frozen or copied as part of this feature. Replacing source identity through editor/API controls requires unlocking. External edits to the same file use existing file-change detection and invalidate affected media; do not claim the old recording can be recovered from bindings.
7. Preserve selected soundtrack policy even if every selected bound lane is currently silent or unassigned. An empty set of resolved segments must not accidentally fall back to H3's generated soundtrack.
8. Playback-change confirmation compares effective audio placement, including assembled bridge positions, rather than assuming that any binding edit is audible. Do not require confirmation when unlocking leaves playback equivalent.

## Implementation surfaces to inspect during planning

- `web/h3c_timeline_model.mjs`: parse/serialize, active audio, box mutations, stable IDs and reference routing.
- `web/h3c_audio_lanes.mjs`: lock control, disabled placement edits, waveform segments, audition and beat projection.
- `web/h3c_shot_split.mjs`, `web/h3c_timeline_editor.mjs`, `web/h3c_timeline.js`: split mutation, duration/normalization, editor history, Story/workflow saves and host source views.
- `h3_continuity/timeline.py`, `timeline_prepare.py`, `audio_tracks.py`: validation, played/generated/carry windows, reference mode/slots, sliced conditioning and soundtrack placement.
- `h3_continuity/dialogue.py`, `timed_text.py`, `replacement.py`: source cue projection, lettering contracts, sequence-lock conflicts and splice coverage.
- `h3_continuity/nodes.py`, `partial_video.py`, plus the existing partial-preview/full-video/export builders and their keys: assemble with the same box-ID mapping. Audit every `audio_tracks` and soundtrack-placement caller before implementing.
- `h3_continuity/timeline_api/contracts.py` and project/workflow/checkpoint serializers: schema validation, feature negotiation and full fidelity round trips.
- Current guide sections for audio/dialogue/bridges and corresponding JS/Python tests. No new dependencies are expected.

Cache/render identity must be based on effective local audio inputs and carried context. Moving an independent box with unchanged delivered/carry inputs should not become outdated merely because its global start changed; actual changed inputs and visual dependencies still invalidate it. A full/partial soundtrack cache must include resolved windows, box ordering/durations and inserted bridge gaps. Hidden metadata alone must not force an unnecessary render if effective inputs did not change.

## Acceptance evidence required from implementation

Use focused JS/Python tests for timing and persistence, then the project's existing test runner and representative desktop/mobile UI checks. A design-only task does not run GPU generation or claim model-level silence/lip-sync acceptance.

- Enabling and immediate unlocking in eligible states are audibly equivalent for fractional placement, nonzero source-in, leading gaps and partial coverage. An existing inserted bridge that conflicts with selected soundtrack playback blocks enabling without state changes and identifies the join. Non-conflicting bridges and reference-only lanes remain eligible.
- Extending an earlier box adds only local padding and shifts later movie placement without changing later source intervals. Shorten/re-extend restores hidden audio; cycling resize does not accumulate drift.
- Insert, append and duplicate are unassigned; move/delete/split preserve the approved ownership rules. Cover splitting a shortened assignment, splitting inside a gap, grid-added duration and omitted empty halves.
- Multiple lanes can mix bound and continuous behavior; all-empty selected bound lanes remain silent under the existing soundtrack policy. Source shortfall remains padded rather than stretched or looped.
- Carry references include actual preceding gaps/reordered windows; linked dialogue/text/beats follow source assignments while independent text and existing cue/lettering checks retain their behavior.
- Bridges insert lane-specific silence, preserve following assignments and retain sequence-lock restrictions. Verify full/partial/preview/export paths against one resolved mapping.
- Save/load, history, checkpoint restore, project revisions and workflow import/export retain hidden tails and empty bindings. Test unlock cancel, unlock/undo/redo and re-lock capture after edits.
- Reject unsupported reader features, malformed mappings and source edits that bypass the lock. Check no unassigned box can accidentally receive the whole recording via reference routing.
- Independent unchanged audio inputs retain effective render identity; changed context or visual dependencies still invalidate. Soundtrack caches rebuild when resolved placements change.

## Non-goals and remaining builder discretion

No per-segment source editing, audio stretching/looping, automatic crossfades, whole-box mute system, separate sliced files, automatic dialogue rewriting, forced soundtrack selection or guarantee that visual dependencies remain current. Do not automatically add audio to future boxes or silently rebind after Story/JSON edits.

The builder chooses the smallest suitable schema and helper structure, reuses current controls/history/validation, and determines focused test placement. Changes to the approved behavior or scope return to design review. The subsequent implementation plan and Native execution choice govern implementation.
