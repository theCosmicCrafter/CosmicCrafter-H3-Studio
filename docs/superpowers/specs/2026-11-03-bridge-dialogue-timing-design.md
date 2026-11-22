# Dialogue timing and bridges within existing duration

Status: **chat design approved; written specification awaiting review**. The user accepted Q1–Q7 and confirmed the coherent design with “LGTM” on 2026-11-03. Approval authorizes this specification; product implementation, model runs and implementation-plan execution have not begun.

Repository: `KadoBOT/ComfyUI-H3-Continuity-Studio`, isolated branch `design/bridge-dialogue-timing`, starting source HEAD `558b838fc4b9fe5e6bba54a9a5b19faec40f0fc3`. The [decision and evidence record](../../research/2026-11-03-bridge-dialogue-timing.md) contains the source findings and individual approvals. The [worktree roadmap](../../roadmap-discipline/features.md) owns recovery state. The separate continuity-evidence planning effort remains untouched in the main checkout.

## 1. Problem and chosen approach

A current bridge inserts generated footage between two complete rendered boxes. Authoring time excludes that insertion. A long original audio clip is shifted only by bridges before its start, then plays continuously; later inserted bridges move the picture away from the recording's dialogue. Changing prompt text cannot move speech in an unchanged waveform or mouth movements in existing rendered frames.

The chosen approach combines recording-anchored dialogue cues with reversible picture replacement. In a sequence with a fixed recording, a bridge replaces an explicitly reviewed region around a cut, delivering exactly the duration it replaces. The recording and downstream times stay fixed. Original clips and takes remain available.

First-class dialogue is the shared synchronization model, rather than an instruction to push every line after a bridge. Blind edge trimming was rejected because silence does not establish that a gesture or reaction is expendable. Cutting and moving the recording was rejected as the default because it changes speech, music and ambience together. An explicit bridge mode that adds time remains available when no recording is locked to the sequence clock.

Replacement endpoint construction has a mandatory feasibility gate. The current renderer cannot simply be reused with arbitrary trimmed neighbors. This specification defines required behavior without claiming that all desired boundaries or durations are technically supported.

## 2. Scope and invariants

The first version covers original recorded dialogue, editable source-bound cues, bridge-region review, exact-duration picture replacement, reversible take selection and compatibility with existing insertion bridges.

It must preserve these invariants:

- A picture-only replacement never cuts, moves, stretches, loops or inserts silence into a locked recording.
- Delivered replacement frames equal the frames removed from the existing sequence. Total duration and every later box start remain unchanged, regardless of the number of replacements.
- Original source media and takes are not destructively trimmed or overwritten.
- Automatic replacement never touches protected visible speech. Explicit off-screen voiceover may continue over replacement pictures.
- The user reviews the exact region before generation and reviews the candidate before selecting it.
- Failure, missing evidence or unsupported geometry never silently removes protection, expands coverage, moves audio or falls back to inserting time.

Automatic transcription, forced alignment, diarization, stem separation, a new audio mixer and automatic repair of existing lip synchronization are outside the initial scope. Replacing visible speech through a future override requires its own explicit behavior and AV review; it is not part of the initial automatic path. This work does not resume the separate continuity-improvement program.

## 3. Dialogue cues and clocks

### Recording identity and cue meaning

Each dialogue cue has a stable identity, a bound recording, a source interval, exact words, speaker information and on-screen/voiceover portrayal. It references the placed recording instance as well as the source asset; an audio slot alone is insufficient identity when its file changes. Portrayal may vary across a line, so annotations must be able to identify the relevant subintervals without duplicating the logical spoken event.

Cue source times belong to the recording. Recording placement and source-in map those times onto the sequence. Box splits or picture replacements must not rewrite source intervals or duplicate the words. A deliberate recording move, trim or replacement is a separate edit that invalidates dependent verification and bridge approvals.

All locked recordings constrain the same sequence clock. There is no hidden priority that permits moving one locked track to satisfy another. The setup must expose conflicts with the existing full-video soundtrack selection before claiming synchronization to the original recording; it must not silently enable unrelated audio clips or change the existing mix policy. Generated bridge audio must not unexpectedly layer speech or music over the original soundtrack.

### Explicit time mappings

Reuse the existing audio placement convention:

`sequence_time = recording_placement_start + source_time - recording_source_in`.

Compile sequence events onto a box's generation clock, including its carried/replayed context. Source time, sequence time, generation time and delivered frame/sample positions must remain distinguishable. Rounding must not accumulate from box to box. Replacement coverage uses integer native frames; audio placement retains its sample clock. For protection, round speech coverage outward to frames rather than rounding away a spoken edge.

A line crossing a box boundary remains one logical event. Local compilation needs continuation information and must not schedule the complete utterance as a new event in both boxes. A cue cut by a recording's placed source window is an explicit review case; do not silently shorten or accelerate the utterance to make it fit.

For cue-managed dialogue, compile `<d>` instructions from the shared model. A hand-edited prompt that conflicts with those cues produces a reconciliation case instead of silently overwriting the user's prose or inventing source timing. Unmanaged prompts remain supported, but their tags alone do not establish verified recording intervals.

### Intake and verification

Initial cues can start from a supplied timed transcript, existing Story data or manual entry. Supply individual cue editing and recording audition. Existing transcript JSON parsing and source-clock projection may be reused; current visible-lettering attachments retain their distinct purpose and must not silently become speech.

Story schedules are planned timing. Transcript timestamps are supplied timing. Neither proves alignment to a particular recording or rendered mouth movement. Keep source-alignment verification distinct from verification of visible speech in a particular take. Bind verification to the relevant recording/take identities so it becomes stale when those inputs change.

Before approving a replacement region, the user checks its recording alignment and actual footage. Known visible-speech spans are protected, and observed protection can be extended beyond a planned cue. Unknown portrayal or unverified timing cannot be treated as silence. Missing structured data requires explicit manual review of that region rather than inferred permission to replace it. No automated lip-motion detector is promised.

## 4. Replacement geometry and generation

Represent replacement as an interval over the original sequence, associated with its join and endpoint source takes. The underlying boxes retain their complete media and authoring positions.

For a cut at frame `J`, choose left coverage `L` and right coverage `R`. The replacement covers `[J-L, J+R)` and delivers exactly `L+R` frames. Allocation can be asymmetric, subject to validated endpoint and duration support. Generation context is additional conditioning and is excluded from delivered coverage.

The outgoing guidance must come from the surviving footage before the interval; incoming guidance must come from the surviving footage after it. Using the original untrimmed tail/head would guide the bridge toward frames no longer adjacent in the assembled video. A visual endpoint construction must also respect temporal latent origin; matching tensor dimensions is insufficient.

The range solver may propose supported alternatives, but it must show the exact resulting interval and any snapping before confirmation. Confirmation binds to that exact range. No later grid adjustment may enlarge or move it without another review. Reject overlapping replacement intervals; adjacent bridges cannot consume the same source footage.

Video continuity and audio context are separate responsibilities. Native audio latent ticks and output audio samples have different clocks. Preserve the locked soundtrack independently of whatever audio conditioning is used during bridge generation, and validate any changed audio-context extraction rather than copying the old whole-run assumptions.

### Required feasibility gate

Current source uses repeating nominal video token widths `(1,4,4,4,4)` and canonical run lengths `17k+5`. Existing endpoint helpers copy complete saved-run tails/prefixes without an arbitrary internal frame boundary or cropped-origin contract. With both canonical contexts congruent to 5 modulo 17, the existing bridge interior is congruent to 12 modulo 17; the parser currently offers 12, 29 or 46 new frames.

Source arithmetic also shows that simply trimming whole 17-frame groups from both ordinary on-grid neighbors removes a multiple of 17 frames. That does not equal today's two-ended bridge interior. This is evidence against direct trim-and-reuse, not proof that replacement is impossible. Cropping output can enforce a frame count, but does not establish continuity at the surviving right endpoint.

Before committing to a replacement construction or unrestricted UI handles, establish and validate:

1. The source frame/token origins and valid internal endpoint extraction for the actual VAE path.
2. Permissible endpoint pairs, context geometry and delivered replacement durations.
3. Exact interval assembly, with generation context excluded and no omitted/duplicated source coverage.
4. Real generated endpoint continuity, motion and protected-speech behavior at both joins.

If that gate fails, keep replacement unavailable and preserve existing cuts; report the failing construction and evidence. Do not weaken the audio/protection invariants to obtain a nominally working bridge. Model runs belong to a separately authorized implementation/verification phase. No such proof or run exists yet.

## 5. Editor workflow and reversible state

The user selects a join and the mode. With a locked recording, replacement within existing time is the default.

1. Propose a bounded supported region, showing original footage, original audio, protected speech, existing actions where known, and the exact coverage from each side.
2. Let the user adjust the supported boundaries or retain the cut. Require confirmation of the final region before generation. The review concerns actual footage, including important silent actions, rather than a claim that Story metadata knows what is disposable.
3. Generate a separate candidate using the reviewed endpoints and region identity. With no valid replacement selected, keep the original coverage active during a pending or failed run. An existing valid selection can remain while an alternative renders.
4. Play the candidate against the original recording and allow comparison with the original join. Activate it only when the user selects that result.
5. Retain the original takes and candidate provenance. Removing a replacement or undoing its creation restores original coverage, with no timing change or audio hole. Undoing its removal can restore a still-valid selection.

If no protected-content-safe and technically supported region fits, keep the cut and state the reason. Where possible, offer a shorter or differently allocated supported region for a new review. Do not widen the region, regenerate visible speech, move the cut's surrounding content in time or add duration automatically.

Any endpoint take, range, relevant cue/protection, bound recording, prompt or generation-setting change must invalidate the dependent candidate/selection as appropriate. A valid existing selection can remain while a separate alternative renders if its inputs remain unchanged. A stale selection cannot silently enter an export; restore original coverage with an explicit stale status until a valid candidate is selected.

Moving/deleting boxes, resizing them or switching takes must revalidate join identity, source positions and replacement overlap. Undo restores the corresponding selection and dependencies, then revalidates them against actual available files. Cue edits that change a box's compiled generation inputs mark that box out of date; cue metadata cannot retime its existing render. Candidate reuse requires matching actual endpoint sources and reviewed range, not just matching a seed.

## 6. Components and integration boundaries

Keep responsibilities small and explicit:

- **Dialogue model and clock projection:** source-bound cue identity, intake, editing, verification state and projection into sequence/generation clocks. Current related surfaces: `timed_text.py`, `story_stages.py`, `story_fast.py`, `timeline.py` and browser timeline/audio models.
- **Replacement planning and validation:** mode, exact range, protections, endpoint identities and feasible native geometry. Current related surfaces: `bridges.py`, `timing.py`, `latents.py`, `timeline_node.py` and the durable API planner.
- **Assembly and persistence:** non-destructive source windows, exact delivered coverage, unchanged locked audio placement, stale/reusable take identity and reversible selection. Current related surfaces: `nodes.py`, `audio_tracks.py`, `store.py`, `takes.py` and API artifacts.
- **Review UI:** cue/recording audition, proposed-region confirmation and candidate comparison/selection. It consumes the same plans and protection results as generation/export; it must not maintain a separate approximate timing model.

Implement these contracts in the existing repository structure. Exact schemas, migrations and test paths belong in implementation planning after this document is approved. No replacement continuation engine or general editor rewrite is part of this design.

## 7. Existing projects and insertion mode

Existing projects retain their current time-inserting bridge semantics and saved takes. Missing new fields must not reinterpret an old bridge as replacement. New replacement records need explicit versioned mode/coverage data; files requiring new semantics must identify their minimum supported reader. Do not assume an older installation can save those fields safely.

Insertion remains an explicit option when no recording is locked. Introducing a locked recording into a project with insertion bridges exposes the timing conflict. Require an explicit mode/edit decision; do not silently convert old bridges, move the recording or claim the sequence is synchronized. A failed replacement never falls back to insertion.

Authoring and full-video timing must remain visibly distinguishable for insertion projects. Recording locks and replacement mode must use the same exact clock in authoring, generation planning, candidate review and full-video assembly.

## 8. Acceptance and evidence

Deterministic verification must establish source-to-sequence-to-generation mappings, stable cue identity, exact frame coverage, conservative speech protection, dependency invalidation and compatible project round trips. Verify decoded/pre-encode waveform placement and sample selection; lossy exported audio is not expected to be byte-identical to the source file.

Required cases include:

- A long recording crossing several replacements, with no cumulative dialogue drift or duration change.
- Audio starting inside a box, nonzero source-in, differing sample rates and more than one locked recording.
- Cues crossing box boundaries or recording-window edges; no duplicate words or invented timestamps.
- Visible speech at the join, off-screen voiceover over replacement footage, unknown timing and an important silent action.
- Asymmetric supported ranges, unsupported geometry, insufficient room and overlapping replacements.
- Pending/failed generation, stale endpoints/cues/recordings, take switching and add/remove/resize/reorder/undo.
- Existing insertion projects and old saved takes retaining their meaning; explicit conflicts when fixed recording timing is introduced.
- A candidate failing review leaves original footage and audio intact.

Actual media review must check both surviving endpoints, motion and scene continuity, protected footage, dialogue synchronization and uninterrupted original audio. Record the source/take identities, exact range, generation recipe, delivered frame count and selected result so a failure is reproducible. Arithmetic and unit tests cannot certify visual quality or lip synchronization.

## 9. Review boundary and next step

Q1–Q7 and the coherent chat design are approved. This written specification still requires the user's review under Superpowers brainstorming. After that review, use writing-plans to produce a focused plan whose first technical gate establishes valid replacement endpoint construction. Do not present that gate as already passed, and do not start product implementation or model runs from this document's existence alone.

Source-inspection anchors: `timeline.py:348-357,397-431`; `audio_tracks.py:66-90,156-194`; `nodes.py:364-457`; `timed_text.py:79-245`; `story_fast.py:125-138,421-452`; `story_stages.py:67-123,181-196`; `timing.py:3-48`; `latents.py:22-101`. These observations concern the starting source HEAD and are documented in the linked evidence record; they are not runtime verification of a new implementation.
