# Cast assignment and structured prompt forms

Status: approved by the user on 2026-11-15. Next: write and review the implementation plan before product implementation.

Builder check (2026-11-15): an independent software-engineer review reported "nothing important left" to resolve before planning. This checks planning completeness, not product behavior or user approval.

## Intent and decisions

Creators should be able to add an existing Cast character to a clip and edit an H3 prompt without remembering its punctuation, labels or time format. Sections becomes a predictable form while Raw text remains a first-class editor of the same prompt.

User requirements:

- Adding from Cast creates the next Subject using the bible description.
- Turn the official MiniMax prompting guide into a small field schema: repeatable definitions, retention entries, shots and other structured content; predefined values where the format calls for them.
- Shot 1 has no timestamp input. Later starts are entered conveniently and cannot precede or equal the previous start.
- All content fields are optional; advanced details can be added individually. Provide common options while allowing custom creative text.
- Keep native prompt text authoritative (explicitly selected on 2026-11-15). Incorporate useful Singularity details without strictly following its format or ordering (explicit clarification).

This is one editor project with sequential slices: Cast assignment, Basic forms, advanced additions, integration and documentation. It is larger than a button change, but does not need a new form library, a new prompt storage format, an LLM conversion service or a rendering-engine rewrite.

## Approaches

**Selected: text-backed forms.** Extend the existing lossless source-range parser. Recognize known syntax and write only the field or row being edited. Retain all other text. The same native prompt survives save/reload and continues to work through existing render, API and workflow paths. The tradeoff is that arbitrary existing prose cannot reliably be separated into every advanced field.

**Considered: canonical structured prompt document.** Save a versioned document and compile it to prompt text. This would make field ownership explicit but require persistence changes and an authority policy for raw edits. The user chose the smaller text-backed approach.

The existing strict Story schemas are a vocabulary and compatibility reference, not the human form contract. They require fields that this form must allow users to omit. The form does not fabricate or overwrite Story's box.source provenance.

## Authority, optionality and preservation

1. box.prompt remains the only saved creative content for this feature. There is no synchronized second prompt document or authoritative field cache.
2. Sections is a derived view. Opening it, changing tabs or Basic/Advanced, loading a project, or focusing an empty field produces no prompt mutation, undo step or render invalidation.
3. Blank optional fields emit no content, defaults, placeholder descriptions or N/A. A populated row needs its minimum syntax to be valid, such as a target and marker for a retention row. Incomplete structural drafts stay local to the editor and are visibly unsaved until corrected or discarded.
4. Changes operate on source ranges derived from the current prompt. Reparse after edits; do not apply old offsets to newer text. Unrelated bytes, whitespace, native labels, dialogue and alignment prose stay unchanged.
5. Sections supports recognized subsets of the native sections, not only today's exact three/six-header sequences. A blank prompt exposes an empty form. The first deliberate content edit creates only the applicable headings/content. Do not convert a whole prompt merely because a field is shown.
6. A plain prompt with no recognized headings remains visible as Existing text. Adding fields does not overwrite it: preserve its text and place it in the applicable shot-description section during the explicit edit that first adds native structure. Opening Sections alone does not wrap it. Duplicate/ambiguous section headers or malformed entries stay visible as Existing text at their source position; only unambiguous regions get typed controls.
7. Raw edits immediately replace the authority. Sections reparses them without semantic rewriting. Unknown prose, custom values and unsupported syntax remain visible in an Existing text field for that region; they do not disable the rest of the form.
8. No edit requires a writing model. The UI performs deterministic formatting, never invents actions, translates dialogue or claims visual continuity.

## Add from Cast

Use the existing In this clip area and rename its ambiguous Add… control to Add from Cast. Keep it near the prompt and also offer the same action from Subjects & references; both call one transformation. The picker lists characters and props, with the existing Place selector for locations. With no bible, show a concise route to Cast to create/build one; do not generate an entity automatically.

The action is atomic and undoable:

1. Resolve the selected entity's description, active look and pictures at this clip using the existing bible helpers. An empty description with usable pictures can still create a picture-grounded definition; without either, show an inline request to describe the entity in Cast and change nothing.
2. If this clip already maps a Subject to the entity, focus that Subject instead of duplicating it. If only its schedule contains the entity, create the missing Subject. Never guess that an unlinked manually written Subject is the entity based on similar prose; offer the existing Link action.
3. Allocate max(existing Subject numbers) + 1. Scan the clip prompt, shared prompt and its cast-map labels to avoid collisions, including references in shot prose; do not renumber or fill gaps. Subject numbering is local to the clip.
4. Add one <Subject N> is ... definition using the bible's wording and active pictures, expressed with stable @image slots. Establish box.cast and add the entity to box.schedule together. For Place, update schedule.place instead of entities. No shot appearances, retention choice, new first/last frame or character action is inferred.
5. Existing reference prompts get an appended definition. A blank prompt gets the subject_definitions content. A base/plain prompt gets subject_definitions plus its current visual text retained under detailed_description; rename an existing integrated_multimodal_description heading as part of this explicit action, preserve its body and the sound/music sections, and leave unfilled summary/retention absent. This makes the Subject definition visible to the existing bible tooling without requiring a complete six-section template.
6. Adding a picture can change actual reference conditioning and therefore the reported H3 mode. Use the existing reference resolution and limit checks; do not present Basic/Advanced as a mode switch. If the added references exceed a supported limit or are missing/disabled, fail the whole add with a specific inline explanation; preserve the prior prompt, cast and schedule.
7. Commit the prompt, cast and schedule as one history operation. Use the usual outdated-render behavior; never render, resize, reseed or rewrite another clip as a side effect.

Bible updates continue to use existing managed-line/differs behavior. A user-edited Subject description is not silently reset. After a form edit, preserve the Story source record as provenance and let existing Edited by hand/Recompile behavior identify divergence; do not forge a new writer reply.

Removal retains the current schedule-only meaning. Label it Remove from schedule and explain that it leaves prompt text in place. Deleting a Subject definition is a separate explicit form operation; reject it while known prompt references or cast links would dangle, and direct the user to unlink/remove those uses first. Do not broaden this project into a semantic prose-cleanup service.

## Small field schema and Basic form

A small module describes keys, labels, control types, suggestion lists, optionality, applicability and serializers/parsers. Reuse the existing DOM, mention picker, tabs, optional-section components and history. No generic schema-rendering framework or dependency is needed. Avoid duplicating the strict Python writer schemas wholesale; contract tests compare shared syntax vocabulary where appropriate.

| Area | Form fields | Native output |
| --- | --- | --- |
| Subjects & references | Repeatable Subject/Picture/Video/Audio definition rows; stable identity/target, description, sources and their roles; optional Cast link | subject_definitions |
| Summary | Optional known task-type multi-selection plus free paragraph; preserve custom existing prefix | summary |
| Reference retention | Target; zero or more applicable shot numbers; role/scope; visual or audio relationship; free details | retention_analysis |
| Shots | Ordered cards with number, start for Shot 2+, cut/continue intent, composition, actions, optional basic camera and dialogue | integrated_multimodal_description or detailed_description |
| Sound | Optional soundscape and audience-only music; preserve existing reference mentions | overall_soundscape and non_diegetic_music |

Definition roles distinguish content identity from a concrete frame anchor. An appearance picture belongs in the Subject definition; a standalone Picture row is appropriate for a frame, keyframe, composition or storyboard anchor. Video and Audio rows use their own scope and independent numbering. Source pickers store stable @slot identities and show the current human-readable title/native binding; never assume a rendered Picture number identifies the same file forever. Imported native tags that cannot be resolved remain literal and visibly unresolved, not silently bound to a guessed file.

Retention examples:

```text
<Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved - Her appearance remains unchanged.
<Picture 2> ([Shot 1] first frame): fully_preserved - The opening uses this composition.
<Video 1> (cut and pacing structure): weak_reference - Follow the broad editing rhythm.
<Audio 1>: reference - Follow the voice timbre without copying the recording.
```

Visual relationship suggestions: fully_preserved, partially_preserved, attribute_transfer, weak_reference. Audio: fully_copy, partially_copy, reference, weak_reference. These are the official expected markers. Allow an explicit Custom value option and preserve imported custom markers; identify them as outside the expected vocabulary, without dropping or rewriting them. Do not automatically promote Singularity's newly_generated into a required/default value.

Summary task suggestions: keyframe completion, reference generation, video editing, video continuation, audio reuse, audio reference. Select none by default. Creative controls, including camera, shot size, style, delivery, effect and lighting, accept custom text directly.

All structured fields support keyboard operation and labelled inputs. On narrow screens, row controls stack vertically. Keep the incumbent Studio visual style and section tabs; this is a usability refinement, not a new visual theme.

## Shots, timestamps and associated guides

- Shot 1 starts at native time zero and has no editable start. Shot 2+ shows Start (seconds), accepts decimal seconds to millisecond precision, and formats native At MM:SS.mmm, text. A later shot may continue without a cut; preserve that distinction.
- The entered number is clip playback time. For continuing clips, serialize using the existing generated-video clock: native time = playback time + carried frames / 24 for later shots. Show a small replay-offset note when relevant. Existing native times are displayed with that offset removed. Never shift the original shot merely by opening the form. Native stages wholly inside replay remain preserved as existing text, with timing controls unavailable for that row.
- Form-authored later starts must be finite, strictly greater than the previous displayed boundary, and less than played clip duration. A continuation can have its first new cut at playback 0 if its native start follows the replay opening; later boundaries must still increase. Respect representable frame boundaries used by previews/splitting; do not treat equal timestamps as valid or silently move neighbours.
- Keep invalid input as a local draft with an inline error and retain the last valid saved prompt. Raw text can still hold nonconforming imported timing; show the problem without silently correcting it. Resolve/discard a structural draft before changing clips or starting generation; do not generate under the pretense that unsaved timing was applied.
- Add shot is an explicit operation with a local start draft and empty optional content. It does not commit until its boundary is valid. Append by default. Editing an earlier start is bounded by both neighbours; no automatic cascading shifts.
- Deleting a shot or changing its boundary must account for retention shot selections, saved preview targets and accepted guides. Remap known surviving shot numbers atomically on deletion, and use existing target synchronization for supported targets. Never silently move/delete an accepted guide or alter a guide's accepted frame. If an operation would do that, explain which guide blocks it and require the user to remove/reassign that guide through existing controls first. Unknown references to affected shot numbers similarly block automatic renumbering rather than guessing.
- Reordering shots by drag-and-drop is outside this first design; append/delete and valid start edits are sufficient. Existing Split before Shot N must continue to work with the resulting prompt.

## Advanced details without a second document

Advanced mode reveals optional groups within each shot. Returning to Basic only hides empty extra controls; populated advanced groups remain discoverable through a Details present indicator and keep contributing text. To remove a detail, clear/remove that field explicitly. The preference is local UI state, not a render parameter or a different video model.

Use readable, recoverable cue lines inside the shot for newly authored subfields. This is a design choice to support text authority and reliable reload; it is not a Singularity syntax requirement. Examples:

```text
[Shot 2] At 00:03.500, the shot cuts to a close-up of her hand.
Initial state: Her fingers rest loosely around the cup.
Action: She tightens her grip and begins lifting it.
Camera movement: Slow push-in toward the cup.
Physical response: Steam curls around her fingers as the cup rises.
Lighting: Warm window light catches the wet ceramic.
End state: The cup pauses just below her mouth.
```

The complete line value is the field's text. A camera suggestion fills editable prose in Camera movement; it does not introduce a hidden camera object that must be recovered from arbitrary sentences. Values can span continuation lines; the next recognized cue at the shot's line start ends the value. Cue parsing is scoped to that shot and outside <d> blocks. Duplicate cues are treated as Existing text instead of guessed/merged. Existing unlabeled prose remains the composition/action narrative and is never automatically split into these fields.

Each cue descriptor defines its English prefix and insertion rank. New populated fields are inserted relative to recognized cues; existing text and existing cue order stay unchanged unless that field is edited. No inline metadata markers are sent to H3, no extra top-level sections are invented, and no hidden offsets are persisted. A raw edit to a recognized cue updates its form value; if the cue is removed/changed beyond recognition, its text stays in Existing text.

| Group | Optional fields and suggested content |
| --- | --- |
| Action progression | Initial state, trigger/preparation, action (repeatable), contact/reaction, recovery/end state |
| Camera | Shot size/position, movement, direction, speed/amplitude, subject followed, focus; presets populate editable wording |
| Physical response/effects | Trigger, effect description, direction/motion, impact/environment response; repeatable blocks only when individually addressable in text |
| Lighting/materials | Light/source/direction, colour/contrast, reflections, atmosphere, material response, depth/focus |
| Acting | Gaze, expression, breath, posture and hand actions as optional prose fields |
| Continuity | Screen direction, carried pose/object/damage/environment state as authored prose |

Initial suggestion catalogue: official camera vocabulary plus orbit, swoop, whip-pan, dive, barrel roll and handheld; common framing such as wide, medium, close-up and extreme close-up; effects such as sparks, smoke/dust, debris, water, energy, explosion and lightning; lighting such as warm/cool, side/backlight, haze and shallow focus. Suggestions are writing aids, not model switches or quality guarantees. No suggestion is selected automatically. Custom entries need not be saved in a new user preset system.

Basic already includes optional composition/actions, basic camera and dialogue. Advanced supplies the additional detail fields; it does not withhold official basic syntax behind an expert toggle. Dialogue keeps stable speaker identities and exact <d> content, preserving the current distinction between manual dialogue and recording cues. Never duplicate cue-owned dialogue through a new manual form.

## Integration and validation boundaries

Implementation must reach the Cast frontend/server transformation, prompt parser and editor, shared shot extraction, source-range writers, history, read-only guards, reference resolution, shot preview/guide and split helpers, relevant tests and guide pages. All callers of promptSections/promptShots must tolerate partial forms with no shot section, including subject-only prompts, frame candidates and still-scene extraction. Existing render/compiler code changes only where necessary for a demonstrated compatibility issue, not to impose strict Singularity behavior.

Reuse story_bible wording/picture/line rules. If a server action is used for Cast insertion, validate target and current input there and apply the returned prompt/cast/schedule only when the request's snapshot still matches; never land a stale async result over edits or an Undo. Existing apply/recompile behavior is preserved for unrelated callers.

No new authoritative per-clip metadata means no automatic timeline format migration. Verify real save/reload, import/export and Undo/Redo anyway. Do not serialize ephemeral drafts or UI preferences in box.source. Read-only Timelines remain byte-identical under every new control.

## Success criteria and verification

- Add from Cast inserts one correct next Subject with the applicable look/pictures and synchronized link/schedule; duplicates, schedule-only membership, sparse numbering, missing inputs, stale replies and one-step Undo/Redo are covered.
- A blank prompt, partial native prompt, normal base/reference prompt, Story-written prompt and unfamiliar pasted prompt can all be edited without losing unrelated content.
- Byte-identical round-trips for untouched input, Raw/Sections switches and Basic/Advanced switches; exact dialogue preservation, including text that resembles headings/cues.
- Optional fields add no content until populated; custom values survive reload and remain editable. Advanced cues survive raw edits, save/reload and existing prompt transformations; unknown text remains visible.
- Timestamp validation covers neighbours, non-numeric/equal/out-of-range values, playback/native conversion with carry, first-new-frame continuation cuts and imported replay stages. Guide/frame contracts and Split before Shot N remain valid.
- Preview target/retention renumbering, protected guides, subject/reference deletion, stale generated takes, history and unknown-feature read-only guards remain correct.
- Run focused JS/Python tests for each slice, then node tests/run.mjs and strict guide build as appropriate. After web edits run node tools/module_versions.mjs --write. Browser QA covers desktop/mobile, actual control labels, keyboard focus, empty/error states and no draft lost by clip navigation.
- No GPU generation is required to prove editor correctness. Prompt richness improving a particular rendered video is creative acceptance and is not claimed by passing structural tests.

## Scope exclusions and builder discretion

No generic form framework, new dependencies, automatic LLM prose decomposition, strict Singularity validator, preset-management system, automatic shot retiming, render scheduling or automatic cleanup of user prose. No deployment, restart or release is part of this planning request.

The builder may choose helper/module boundaries, exact accessible control components and a compact initial suggestion list within the specified groups. Canonical cue prefixes and parse/serialize fixtures must be written down in the implementation plan before product edits. Any need for persistent content metadata or a second prompt authority requires revisiting this design rather than quietly expanding it.

## Sources and implementation anchors

- [Official MiniMax base/reference guides](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/h3-prompt-writing/references), read 2026-11-15.
- [Singularity writing details](https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity/blob/main/MiniMax_H3_Singularity_Prompt_Writing_Specification_Enhanced_EN.md), read 2026-11-15; optional inspiration as clarified by user.
- web/h3c_cast.mjs; web/h3c_prompt_sections.mjs; renderPrompt/renderCastChips in web/h3c_timeline_editor.mjs.
- h3_continuity/story_bible.py; story_bible_write.py; story_fast.py; h3_prompt_schema.py; h3_prompt_compile.py.
- web/h3c_shot_split.mjs; h3c_shot_preview.mjs; h3c_timeline_model.mjs; tests/js/shot_split.test.mjs; tests/README.md.
- Planning ledger: docs/roadmap-discipline/phases/2026-11-15-structured-prompt-forms.md.
