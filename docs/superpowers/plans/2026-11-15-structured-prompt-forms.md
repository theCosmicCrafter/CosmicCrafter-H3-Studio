# Cast Assignment and Structured Prompt Forms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an existing Cast entity to a clip as a linked Subject and make Sections a predictable, optional Basic/Advanced form over the native prompt.

**Architecture:** Native box.prompt remains authoritative. Extend the existing source-range parser, introduce small typed field codecs and a dedicated form panel, and keep Cast insertion on the existing bible transaction path. Form-authored shot cues are readable prompt text; no second content document or model-assisted conversion exists.

**Tech Stack:** Existing plain JavaScript ES modules/DOM, Python, node:test, unittest and Playwright; no new product dependencies.

**Spec:** docs/superpowers/specs/2026-11-15-structured-prompt-forms-design.md (approved by the user on 2026-11-15).

## Global Constraints

- "box.prompt remains the only saved creative content for this feature." No new timeline version, requires flag or content sidecar.
- "Blank optional fields emit no content, defaults, placeholder descriptions or N/A."
- "Sections is a derived view." Opening it or switching modes must not mutate prompts, create history entries or invalidate renders.
- "Raw edits immediately replace the authority." Preserve unrecognized text, whitespace and dialogue; no guessing identities or decomposing arbitrary prose.
- "No edit requires a writing model." Singularity is optional writing inspiration, never a required format or model parameter set.
- "Never silently move/delete an accepted guide or alter a guide's accepted frame."
- "Read-only Timelines remain byte-identical under every new control."
- "No deployment, restart or release is part of this planning request." No GPU generation during implementation verification.
- Preserve current dimensions, frames/exact, joins, seeds, reference/voice/cue ownership and Story source provenance except the explicitly edited content/link/schedule. A render becoming outdated follows existing behavior.
- Use an isolated workspace at execution time through using-git-worktrees/native tools; required unpublished design/plan commits are the local base, not origin/main alone. Preserve all pre-existing dirty files in the parent checkout. No workers or worktrees are created by this plan-writing turn.
- Before product edits, run the existing baseline once with the chosen Python/COMFY_ROOT and record it. Diagnose failures attributable to this feature; preserve and report unrelated baseline failures rather than widening the work.
- Run `node tools/module_versions.mjs --write` before each commit containing web changes, then `node --test tests/js/module_versions.test.mjs`. Stage explicit task paths plus generated import stamps; never stage unrelated parent edits.

## Review Focus

- CRLF, astral Unicode and literal headings/shot markers inside <d>: byte offsets must stay correct; test in Task 1.
- A late Cast reply after a schedule/reference change or Undo/Redo: never overwrite the newer state; test in Task 2.
- Changing reference numbering or an unresolved imported native tag: never bind to a guessed asset; test in Task 3.
- Continuing clips, subframe decimal times and targeted/legacy guides: no silent timing or frame drift; test in Task 4.
- Rerender/navigation/history while a structural draft is invalid: do not save it, lose it quietly or queue stale content as though it were applied; test in Tasks 5 and 8.

## Files and responsibilities

| File | Role |
| --- | --- |
| web/h3c_prompt_sections.mjs (modify) | Lossless ranges and existing promptSections/writePromptSections/promptShots compatibility |
| web/h3c_prompt_fields.mjs (new) | Small field descriptors, native row/cue/dialogue codecs and range-local edits |
| web/h3c_prompt_shots.mjs (new) | Playback/native timing and atomic shot edits with guide/reference guards |
| web/h3c_prompt_form.mjs (new) | Accessible form DOM, ephemeral drafts and Basic/Advanced visibility |
| web/h3c_timeline_editor.mjs (modify) | Mount panel, current video/clip adapters, history/navigation/queue integration |
| h3_continuity/story_bible.py; web/h3c_cast.mjs (modify) | Deterministic Cast assignment transaction and its UI/stale-result guards |
| web/h3c_timeline.js; web/h3c_track_editor.mjs (modify only integration points) | Host queue and alternate navigation entry points respect invalid drafts |
| web/h3c_shot_preview.mjs; web/h3c_shot_split.mjs; web/h3c_still_scene.mjs; web/h3c_frame_images.mjs | Audit/adapt partial-section callers; preserve existing clocks and payload contracts |
| tests/fixtures/prompt_forms.json (new) | Exact base/ref/partial/raw/Unicode/dialogue fixtures shared where useful |
| tests/js/prompt_sections.test.mjs; prompt_fields.test.mjs; prompt_shots.test.mjs (new) | Pure parsing, field serialization, timing and guide protection |
| tests/python/test_cast_assignment.py (new) | Bible transaction validation, looks, numbering and failure atomicity |
| tests/web/cast_assignment.test.mjs; prompt_form.test.mjs (new) | Real panel handlers with mocked host; history and stale replies |
| tests/web/prompt_form_fixture.mjs (new, folded into Task 3) | Minimal host/editor form harness using existing fake_dom and TimelineHistory |
| tests/browser/prompt_forms.py (new) | Real isolated Studio workflow on desktop/mobile with mocked services |
| guide/build/prompts.md; guide/story/cast.md; CHANGELOG.md | User-facing behavior and limitations, documented in owning tasks |

## Shared interface and serialization decisions

Keep existing `promptSections(source: string): Section[] | null` and `writePromptSections(source, sections): string` callers working. Return partial recognized sections; return null for wholly raw content. `promptShots` always returns `{sections, shots: [], style: ''}` safely when no visual section exists. Existing fields retain body `start/end/label/value`; add `entryStart/entryEnd` for full row spans without changing old offsets.

New pure contracts (declared in their owning tasks):

- `replacePromptRanges(source, patches): string` in prompt_sections; patch = `{start,end,before,text}`, offsets are JS UTF-16 source indices. Reject overlap, out-of-range or before-text mismatches. Apply validated edits from end to start. Unchanged empty patch set returns source exactly.
- `readPromptFields(source, {tags=[]}={}): PromptFields` and `writePromptField(source, edit, {tags=[]}={}): string` in prompt_fields. PromptFields = `{source, sections, problems}`; each section has `{key, entries}`. An entry is `{kind, shot:null|number, range:{start,end,before}, value, problem?}`; kinds include definition, summary, retention, narrative, cue, dialogue and existing. Visual entries are flattened within their section and identify their shot explicitly. Each typed value is defined in its task. Edit = `{expectedSource, section, kind, shot?:number, entry:null|entry, value:null|value}`; null entry adds, null value deletes. Shot is required for visual edits; adding a shot itself belongs to editPromptShot. Reject a source mismatch. Unknown/duplicate content is an existing entry, never discarded.
- `PromptFormPanel(editor)` exposes `root`, `render()`, `hasDrafts()`, `canLeave(): boolean`, `discardDrafts()`, `destroy()` and `focusSubject(label): void`. Task 3 also adds `TimelineEditor.applyPrompt(source:string,next:string,{structural:boolean}): boolean`: reject read-only/stale source, skip identical text, otherwise update only current video().prompt with existing typed/commit/history behavior and return true. Read the current video each time. All persistent content remains in prompt text. Drafts are keyed by stable clip/video id and source snapshot, not array index.
- Existing prompt text is narrative by default. Newly authored optional fields use the cue table below. Exact known forms can populate fields; ambiguous forms remain Existing text. Never silently normalize imported custom marker values or native tags.

Canonical cue prefixes, rank and visibility (prefixes include a colon and a space; values are free prose):

| Rank | Prefix(es) | Visibility |
| --- | --- | --- |
| 0 | Style: | Basic, opening shot; existing reference-mode style preamble remains directly editable |
| 10 | Composition: | Basic |
| 20, 30 | Initial state:, Trigger: | Advanced |
| 40 | Action:, or Action N: for repeatable actions | Basic |
| 50, 60 | Contact:, Reaction: | Advanced |
| 70, 80 | Shot size:, Camera position: | Advanced; shot-size suggestions also available in composition |
| 90 | Camera movement: | Basic |
| 100, 130, 140 | Camera direction:, Camera subject:, Focus: | Advanced |
| 110, 120 | Camera speed:, Camera amplitude: | Basic, as in the official camera guide |
| 150, 160, 170 | Effect N trigger:, Effect N:, Effect N motion: | Advanced, indexed positive N |
| 180 | Physical response:, or Effect N response: | Advanced |
| 190, 200, 210, 220, 230 | Lighting:, Light direction:, Colour and contrast:, Reflections:, Atmosphere: | Advanced |
| 240, 250 | Materials:, Depth of field: | Advanced |
| 260, 270, 280, 290, 300 | Gaze:, Expression:, Breathing:, Posture:, Hands: | Advanced |
| 310, 320, 330 | Continuity:, Recovery:, End state: | Advanced |
| 340 | Dialogue:, or Dialogue N: | Basic, value uses native speaker/<d> syntax |
| 350 | Scene sound: | Basic, diegetic sounds only |

Recognize cues only at a line's start within its shot, outside <d>. Continuation lines belong to that cue until the next recognized cue. Duplicate identical keys/indices remain Existing text. Singleton Action/Dialogue remains unchanged; adding a second explicitly indexes only that owned singleton and the new row. Other arbitrary duplicate lines are never merged. Removing the last repeated row removes its text and does not renumber other indices. New fields use the table rank; existing order stays intact. Empty/removal edits remove only owned line/value ranges.

## Task 1 / PF1: Partial, lossless prompt parsing

**Files:** Modify web/h3c_prompt_sections.mjs and its caller guards in h3c_shot_preview.mjs, h3c_shot_split.mjs, h3c_still_scene.mjs, h3c_frame_images.mjs and h3c_timeline_editor.mjs. Create tests/fixtures/prompt_forms.json and tests/js/prompt_sections.test.mjs.

**Interfaces:** Consume current Section/Field shapes. Produce partial-section support, full entry spans and replacePromptRanges as defined above. Preserve existing promptShots output and no-timestamp fallback for ordinary raw shots.

- [ ] **1. Write failing tests** `partial_sections_are_lossless`, `subject_only_has_no_shots`, `literal_markers_in_dialogue_are_not_structure`, `ranges_use_utf16_and_preserve_crlf`, `stale_or_overlapping_patch_is_rejected`. Include these exact assertions:
  ```js
  const source='subject_definitions:\r\n<Subject 1> is Zoë 😀.\r\n';
  assert.equal(writePromptSections(source,promptSections(source)),source);
  assert.deepEqual(promptShots(source).shots,[]);
  assert.equal(replacePromptRanges(source,[]),source);
  assert.throws(()=>replacePromptRanges(source,[{start:0,end:1,before:'X',text:'Y'}]));
  ```
  Fixtures also contain duplicate headers, unknown headers, same-line definitions, empty sections, plain prose, six-section prompts and <d>[English] summary:\n[Shot 9] stay literal</d>. Preserve unknown regions without letting them become typed spans.
- [ ] **2. Run red:** `node --test tests/js/prompt_sections.test.mjs`; expect new contract tests to fail for missing partial support/helper, not fixture import errors.
- [ ] **3. Implement** promptSections/promptShots guards and replacePromptRanges. Do not convert whole raw prompts at parse time. Audit every importer (`rg -n 'promptSections|promptShots|writePromptSections' web`) and handle missing visual sections; keep renderer/still extraction behavior unchanged for old complete prompts.
- [ ] **4. Run green:** `node --test tests/js/prompt_sections.test.mjs tests/js/shot_split.test.mjs tests/js/ph3_still_prompt.test.mjs tests/web/endpoint_references.test.mjs`; expect zero failures and unchanged old fixtures.
- [ ] **5. Stamp, commit and checkpoint PF1:** commit `refactor: support lossless partial prompt sections`; record exact commands/results before marking PF1 passing.

## Task 2 / PF2: Atomic Add from Cast

**Files:** Modify h3_continuity/story_bible.py, web/h3c_cast.mjs, web/h3c_timeline_editor.mjs and guide/story/cast.md; create tests/python/test_cast_assignment.py and tests/web/cast_assignment.test.mjs. Existing routes.py forwards the action unchanged; do not add a second HTTP endpoint.

**Interfaces:** `story_bible.assign(timeline: dict, box_id: str, entity_id: str) -> dict` returns `{prompts:{id:text},casts:{id:map},schedules:{id:schedule},subject:str,changed:bool}`; errors are ValueError surfaced by existing handle as `{ok:false,error}`. `handle({action:'assign',timeline,box,entity})` adds `{ok:true,...}`. `CastPage.addToClip(boxId,entityId): Promise<boolean>` consumes it; extend change's application path to include schedules and return/focus subject without changing other callers. Add `TimelineEditor.editRevision:number`, initialized at zero and incremented on successful saved state changes and load/history restoration; capture it with the state snapshot for asynchronous Cast writes, so an Undo/Redo ABA sequence is detectable.

- [ ] **1. Write failing tests** `next_subject_uses_active_look_and_shared_max`, `scheduled_only_entity_gets_definition`, `duplicate_focus_is_noop`, `empty_description_with_picture_is_grounded`, `base_prompt_keeps_body_and_audio`, `invalid_assignment_is_atomic`. Python factory `cast_timeline()` has clip a then b, a shared <Subject 7>, existing Subject 2 in b, entity e1 description Mara in a blue coat, and look from b Mara in a red coat, pictures image17. Assert next subject is <Subject 8>, new cast maps it to e1, schedule includes e1 once, description uses red coat and @image17, input is unchanged, and a second call returns changed false. Existing linked/scheduled entities, props and place stay intact. Empty description/picture emits an error without partial state. Frontend tests assert one Undo/Redo restores all three fields, and a late reply after prompt/schedule/bible/reference changes, load, deletion or Undo/Redo is refused even if text later equals the original again.
  ```python
  doc = cast_timeline()  # The exact two-clip fixture described above; add this helper in this test file.
  before = copy.deepcopy(doc)
  result = story_bible.assign(doc, 'b', 'e1')
  self.assertEqual(result['subject'], '<Subject 8>')
  self.assertEqual(result['casts']['b']['<Subject 8>'], 'e1')
  self.assertEqual(doc, before)
  ```
- [ ] **2. Run red:** `python -m unittest discover -s tests/python -t . -p test_cast_assignment.py -v` and `node --test tests/web/cast_assignment.test.mjs`; new behavior fails before implementation. Use the verified ComfyUI Python setup below if system Python lacks dependencies.
- [ ] **3. Implement** assign using wording(), pictures_at(), line() and max Subject over shared/prompt/cast labels. Pure candidate construction; no mutation until all checks pass. Blank picture-only descriptions become a minimal identity grounded in those pictures. For base/plain prompts perform the spec's explicit local section conversion; ambiguous/duplicate structure blocks add with an explanation instead of overwriting text. Keep source, timing, seed and neighbours intact. Add schedules to change()'s transaction, capture a generation/token plus state revision/snapshot before await, and refuse stale/ABA replies. Validate active added pictures against live referenceOptions()/connectedSets()/referenceEnabled and trial describeBox reference problems before commit; repeat after await. Reject missing/disabled/conflicting/replacement-source issues and >9 images (>3 audio/video if newly implicated), using existing actual-mode rules rather than raw string counts. Server validates shape, disabled active slots and native slot-budget rules; physical graph connectivity is checked by the host, which the bible endpoint does not own. Rename control Add from Cast; include schedule-only entities needing repair. Place selection uses the same assignment for a place; clearing Place retains schedule-only removal semantics. UI must keep Cast's existing primary-clip scope explicit when an alternate video is picked: select/show the main video's Subjects before applying, never silently edit a different visible prompt or invent per-layer Cast storage.
- [ ] **4. Run green:** the two red commands plus `node --test tests/web/read_only_timeline.test.mjs tests/js/history.test.mjs`; expect zero failures, no writer/model call and no extra undo entries on duplicate/error. Update guide with the Subject insertion and Remove from schedule distinction.
- [ ] **5. Stamp, commit and checkpoint PF2:** commit `feat: add Cast entities as linked clip Subjects`.

## Task 3 / PF3: Typed Basic rows and field panel

**Files:** Create web/h3c_prompt_fields.mjs, web/h3c_prompt_form.mjs, tests/js/prompt_fields.test.mjs, tests/web/prompt_form.test.mjs, tests/web/prompt_form_fixture.mjs; modify web/h3c_timeline_editor.mjs. Reuse existing SwitchSection, MentionLayer, tabs and CSS conventions.

**Interfaces:** Implement readPromptFields/writePromptField and PromptFormPanel from the shared contract. DefinitionValue = `{target,description,sources:[{slot,role}]}`; RetentionValue = `{target,shots:number[],scope,relationship,detail}`; SummaryValue = `{taskTypes:string[],text}`. Targets are Subject labels or stable @image/@video/@audio/@video_audio slots; unresolved literal native tags remain literal. `tags` is describeBox.tags' current `{name,tag}[]`, used only when a unique binding exists. Expose `RETENTION_VISUAL`, `RETENTION_AUDIO`, `SUMMARY_TASKS` exactly as in the approved spec. The helper `formHarness({prompt})` builds real panel + model state + TimelineHistory and returns `{panel,editor,history,input,stored,queued}`; input(label,value) dispatches an actual input/change event, stored():State parses the latest host text, queued():number counts host queue calls. Add this helper in tests/web/prompt_form_fixture.mjs as part of this deliverable.

- [ ] **1. Write failing tests** `retention_form_builds_exact_native_line`, `audio_marker_options_differ`, `custom_marker_survives_reload`, `raw_unresolved_tags_are_not_guessed`, `empty_and_mode_switch_are_noops`, `subject_delete_refuses_dangling_uses`. Assert formatting equals `<Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved - Keeps the coat.`; a Picture scope becomes `([Shot 1] first frame)`, audio has no forced shot clause. Custom `my_custom_relation` survives parse/write. Changing tags from image17=<Picture 1> to image20=<Picture 1> does not retarget an existing @image17 row. Raw unresolved <Picture 9> remains an Existing text entry until explicitly bound. Opening blank form or switching Raw/Sections preserves exact prompt and history count. Deleting a referenced/linked Subject must change nothing; offer an explicit Unlink from Cast action using existing links:null before deletion becomes available.
  ```js
  const source='retention_analysis:\n';
  const next=writePromptField(source,{expectedSource:source,section:'retention_analysis',kind:'retention',entry:null,
    value:{target:'<Subject 1>',shots:[1,3],scope:'',relationship:'fully_preserved',detail:'Keeps the coat.'}});
  assert.equal(next,source+'<Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved - Keeps the coat.');
  ```
- [ ] **2. Run red:** `node --test tests/js/prompt_fields.test.mjs tests/web/prompt_form.test.mjs`; fail on the new imports/contracts first, then on behavioral assertions.
- [ ] **3. Implement** schema/row codecs and field panel; update only entry spans. Add/remove definition, retention and summary rows, optional custom input and scoped source/role controls. When the first deliberate field is added to raw prose, wrap its untouched visual content in the correct visual section; never do that on render. Preserve existing unknown regions in editable Existing text. Never auto-fill summary/task/retention/default values. Mount panel instead of the current textarea-only renderPrompt loop; preserve promptSection, focusClipPrompt, mention interactions and native raw editor. Both Cast entry points call addToClip and focusSubject. Show route to Cast without a bible. Protect referenced definition deletion and stable target identity; distinguish text-role descriptions from native settings, so a Picture role is not a silently installed frame guide.
- [ ] **4. Run green:** the red command plus `node --test tests/web/switch_sections.test.mjs tests/web/mention_layer.test.mjs tests/web/typing_commit.test.mjs`; all pass. Keyboard labels/tab navigation remain usable; existing unknown prose is visible.
- [ ] **5. Stamp, commit and checkpoint PF3:** commit `feat: edit prompt references and retention through forms`.

## Task 4 / PF4: Shot timing and protected structural edits

**Files:** Create web/h3c_prompt_shots.mjs and tests/js/prompt_shots.test.mjs; modify existing shot helpers only to share parsing/conversion logic where necessary; extend tests/js/shot_split.test.mjs.

**Interfaces:** `shotTiming(state,index,context,videoId=null): {duration,carry,shots}` returns playback seconds, carry frames and `{number,nativeMs,seconds,cut:boolean|null,editable,problem}` rows. `editPromptShot(state,index,change,context,videoId=null): State` returns a cloned trial or throws; change = `{kind:'set-start',shot,seconds}` | `{kind:'set-cut',shot,cut:boolean}` | `{kind:'append',seconds,text,cut?:boolean}` | `{kind:'remove',shot}`. Use layerView for alternate-video timing without modifying primary text. No UI/persistent metadata in this module. Recognize native cut/continue introductions only when their exact prefix is known; null denotes custom Existing wording. set-cut replaces only that known introduction and leaves timestamp/body intact; ambiguous introductions remain editable as text, not a guessed transition toggle.

- [ ] **1. Write failing tests** `first_shot_has_no_start_field`, `seconds_validate_both_neighbours`, `continuation_uses_native_replay_offset`, `imported_replay_stages_stay_literal`, `guide_frame_is_protected`, `delete_remaps_only_known_survivors`. For 39 carry frames, assert playback 2 yields native At 00:03.625, and playback 0 can be the first new continuation boundary. Reject NaN, Infinity, empty-as-zero, equal/decreasing, negative and end-of-clip starts. Round native ms once; reject form starts mapping to the same rendered boundary as the previous/next shot. Accepted targeted guide at a moved boundary blocks the change; unrelated/free legacy guides remain exactly unchanged. After a safe Shot 2 deletion, original Shot 3 becomes Shot 2 and its known retention references/preview targets follow it. Unknown uses of affected Shot numbers or a removed guide block the whole operation; dialogue text is untouched.
  ```js
  // Add continuationFixture() locally: two exact clips a/b, b has 192 played frames, cut:false,
  // Shot 2 starts "At 00:03.000, the camera cuts to a doorway."; a is fresh with 96 frames. Context is 39.
  const state=continuationFixture();
  const next=editPromptShot(state,1,{kind:'set-start',shot:2,seconds:2},39);
  assert.match(next.boxes[1].prompt,/\[Shot 2\] At 00:03\.625,/);
  assert.throws(()=>editPromptShot(state,1,{kind:'set-start',shot:2,seconds:8},39));
  const continued=editPromptShot(next,1,{kind:'set-cut',shot:2,cut:false},39);
  assert.match(continued.boxes[1].prompt,/At 00:03\.625, the view continues without a cut\./);
  ```
- [ ] **2. Run red:** `node --test tests/js/prompt_shots.test.mjs`; expect missing helper/new behavior failures.
- [ ] **3. Implement** timing from playedFrames/isFresh/layerView, using generated-time offset only at the native-text boundary. Keep existing shotFrames/splitTiming conventions, including their continuation guide-frame offset, intact. Compare actual acceptedGuideFrames before/after on a cloned candidate before any writeState/syncTargets can move a guide. Remap surviving known numeric references; handle duplicate shot numbers as unresolved structure. Guard deleted Subject/Shot references outside <d>, not dialogue words. Do not resize/reseed/snap clip lengths or automatically shift neighbouring starts. Appending adds the next Shot number, later starts bounded by the next row, no drag reorder.
- [ ] **4. Run green:** `node --test tests/js/prompt_shots.test.mjs tests/js/shot_split.test.mjs tests/web/endpoint_references.test.mjs`; expect no failures and guide bytes unchanged on rejected edits. Verify cross-language split/guide compatibility with `python -m unittest discover -s tests -t . -p test_shot_split_server.py -v` and `python -m unittest discover -s tests -t . -p test_preview_targets.py -v`.
- [ ] **5. Stamp, commit and checkpoint PF4:** commit `feat: validate prompt shot timing and protect accepted guides`.

## Task 5 / PF5: Shot cards and unsaved structural drafts

**Files:** Modify web/h3c_prompt_form.mjs, web/h3c_timeline_editor.mjs, web/h3c_timeline.js and only necessary selection entry points in web/h3c_track_editor.mjs/web/h3c_studio.mjs; extend tests/web/prompt_form.test.mjs and tests/web/read_only_timeline.test.mjs.

**Interfaces:** Consume shotTiming/editPromptShot and existing panel contracts. Add `TimelineEditor.promptDraftsReady(): boolean` which focuses the active draft/error and returns false while structural drafts remain. All Studio navigation/queue entry points use this guard. Host queue throws a specific unsaved-draft error before posting any job if direct callers bypass the UI. Unbound global ComfyUI runs still use the saved native prompt; do not patch unrelated app internals. Per-shot Cut/Continue/Existing wording controls consume the cut value above; Shot 1 has no transition control.

- [ ] **1. Write failing tests** `later_shots_use_seconds_input`, `invalid_start_stays_local`, `navigation_and_queue_cannot_drop_draft`, `discard_preserves_last_saved_text`, `rerender_keeps_draft_and_focus`, `external_undo_discards_stale_draft_visibly`. On input Start Shot 2 = -1, assert stored prompt is unchanged, canLeave false, error visible and zero host.queue calls from Generate/Render next/Render remaining or a direct host queue. Clicking a different clip/video cannot change selection until correction/discard. Correct to 2.5 and assert At 00:02.500,; no Shot 1 timestamp input exists. Undo/Redo restores saved text and explicitly drops incompatible local drafts with a notice, never reapplies them to new state.
  ```js
  const h=formHarness({prompt:'integrated_multimodal_description:\n[Shot 1] A room.\n[Shot 2] At 00:02.000, a doorway.'});
  const before=h.stored(); h.input('Shot 2 start (seconds)','-1');
  assert.deepEqual(h.stored(),before); assert.equal(h.panel.canLeave(),false);
  await h.editor.queueBox(1); assert.equal(h.queued(),0);
  ```
- [ ] **2. Run red:** `node --test tests/web/prompt_form.test.mjs tests/web/read_only_timeline.test.mjs`; expect missing controls/guard failures.
- [ ] **3. Implement** ordered shot cards with add/delete/start/transition controls and local draft map. Add/imported invalid rows remain editable but clearly uncommitted; valid prose uses existing typing grouping, structural actions create one history step. A new row has no automatic timestamp/content until the user supplies valid structure. Inline error + Discard draft restores saved state; entering Raw/another clip is blocked only while a structural draft would be lost. Guard select/pick/add/duplicate/remove/split and track/studio equivalents, queue/preflight/submit before seed changes, and direct TimelineHost.queue. Before history load, drop local drafts with an explicit notice and let Undo proceed; never trap history or serialize drafts. Underlying source changes invalidate ranges and require a new draft rather than applying old offsets.
- [ ] **4. Run green:** red command plus `node --test tests/web/typing_commit.test.mjs tests/js/history.test.mjs tests/web/track_editor.test.mjs tests/web/studio_navigation.test.mjs`; all pass with unchanged read-only text and no accidental queue/seed edit.
- [ ] **5. Stamp, commit and checkpoint PF5:** commit `feat: edit prompt shots with safe local timing drafts`.

## Task 6 / PF6: Optional camera and advanced detail cues

**Files:** Modify web/h3c_prompt_fields.mjs and web/h3c_prompt_form.mjs; extend tests/js/prompt_fields.test.mjs and tests/web/prompt_form.test.mjs; update guide/build/prompts.md.

**Interfaces:** Add cue entries `{key,index:null|positiveInt,text}` to readPromptFields/writePromptField using the canonical table. Export `SHOT_FIELDS` descriptors `{key,prefix,rank,advanced,repeatable,suggestions}`. Existing narrative is an independent source range; cues add detail without replacing it. Group controls are ordinary optional form fields with editable suggestions, not nested opaque camera data.

- [ ] **1. Write failing tests** `lighting_is_one_optional_line`, `camera_presets_accept_custom_text`, `repeated_actions_and_effects_survive_reload`, `duplicates_and_dialogue_cues_are_not_guessed`, `basic_advanced_toggles_preserve_all_bytes`. Given `[Shot 1] A quiet room.`, adding Lighting = Warm window light yields exactly `[Shot 1] A quiet room.\nLighting: Warm window light`; Raw reload recovers it. A custom camera value `A slow spiral around her left shoulder` survives unchanged. Empty presets never inject Static Shot or N/A. A second owned action serializes Action 1:/Action 2:; duplicate Action 2: lines remain Existing text. Toggling Advanced off retains populated detail and shows Details present, with no write/history entry.
  ```js
  const source='integrated_multimodal_description:\n[Shot 1] A quiet room.';
  const next=writePromptField(source,{expectedSource:source,section:'integrated_multimodal_description',kind:'cue',shot:1,
    entry:null,value:{key:'lighting',index:null,text:'Warm window light'}});
  assert.equal(next,source+'\nLighting: Warm window light');
  assert.equal(readPromptFields(next).sections[0].entries.find(e=>e.kind==='cue').value.text,'Warm window light');
  ```
- [ ] **2. Run red:** `node --test tests/js/prompt_fields.test.mjs tests/web/prompt_form.test.mjs`; fail on missing cue codec/groups.
- [ ] **3. Implement** cue ranges/insertion ranks, optional Basic composition/action/camera/scene-sound controls, Advanced groups and local visibility preference. Use native editable suggestion controls. Camera suggestions include all current h3_prompt_schema.CAMERAS plus Orbit, Swoop, Whip-pan, Dive, Barrel roll, Handheld; shot sizes Wide/Medium/Close-up/Extreme close-up; effects Sparks/Smoke/Dust/Debris/Water/Energy/Explosion/Lightning; lighting Warm/Cool/Side light/Backlight/Haze/Shallow focus. No defaults. Values containing recognized cue-looking lines must round-trip: while writing, indent all continuation lines by two spaces and, on reading form-authored cues, remove exactly that indentation. Unindented imported cue-looking content remains structural/Existing text, not guessed. Do not add a generic preset manager. Document readable cue output and custom/optional behavior.
- [ ] **4. Run green:** red command plus `node --test tests/js/shot_split.test.mjs tests/js/ph3_still_prompt.test.mjs`; verify shot extraction and untouched dialogue still pass after cue additions.
- [ ] **5. Stamp, commit and checkpoint PF6:** commit `feat: add optional prompt camera and advanced detail fields`.

## Task 7 / PF7: Structured dialogue without changing cue ownership

**Files:** Modify web/h3c_prompt_fields.mjs and web/h3c_prompt_form.mjs; extend tests/js/prompt_fields.test.mjs, tests/web/prompt_form.test.mjs and tests/web/dialogue.test.mjs. Reuse current recording/manual controls; do not redesign web/h3c_dialogue.mjs.

**Interfaces:** DialogueValue = `{speakers:string[],identity,language,text,delivery?,voiceover?,singing?,fromPrevious?,toNext?,cutoff?}`. Blank modifiers are omitted, not defaults written into text. Speakers/language are structurally required only when a populated dialogue row is committed. Speaker IDs are literal S1/S2 etc.; allocate max used + 1 only when adding a new speaker, scanning all sections/audio definitions/shot dialogue. Encode owned Dialogue N: values using the existing compiler's native speaker and <d> conventions, including voiceover closed-lips and continuity/cutoff phrases. Existing unknown delivery phrasing remains narrative/Existing text rather than approximated flags.

- [ ] **1. Write failing tests** `verbatim_multilingual_dialogue_roundtrips`, `speaker_ids_do_not_shift`, `voiceover_and_cut_continuity_use_native_tokens`, `recording_owned_dialogue_is_not_duplicated`. Assert dialogue `营业中! “Wait.”\nsummary: stay` is preserved inside <d> verbatim, group IDs (S1,S2) stay stable across shots/audio definitions, offscreen voiceover includes the native closed-lips clause, and <scenetrans>/<cutoff> are not duplicated. When current mode is From the cues, show the source/route to the current control and refuse new manual dialogue until explicitly switched to Typed in the prompt; zero automatic cue or text removal.
  ```js
  const source='integrated_multimodal_description:\n[Shot 1] She waits.';
  const words='营业中! “Wait.”\nsummary: stay';
  const next=writePromptField(source,{expectedSource:source,section:'integrated_multimodal_description',kind:'dialogue',shot:1,
    entry:null,value:{speakers:['S1'],identity:'<Subject 1>',language:'Chinese',text:words}});
  assert.ok(next.includes('<d>[Chinese] '+words+'</d>'));
  assert.equal(readPromptFields(next).sections[0].entries.find(e=>e.kind==='dialogue').value.text,words);
  ```
- [ ] **2. Run red:** `node --test tests/js/prompt_fields.test.mjs tests/web/prompt_form.test.mjs tests/web/dialogue.test.mjs`.
- [ ] **3. Implement** Basic optional dialogue rows and known native parsing using strict recognizable patterns; retain unrecognized surrounding prose. Reuse selected clip/video dialogue mode and language/voice semantics, no translation or normalization of spoken text. Protect literal cue/header/shot-looking lines inside <d> from form structure and multiline indentation processing. Removing a dialogue row never renumbers other speakers; changing an ID with existing cross-references is rejected until those are explicitly updated.
- [ ] **4. Run green:** red command and `python -m unittest discover -s tests/python -t . -p test_dialogue_compile.py -v`; all pass with exact spoken text and native marker placement.
- [ ] **5. Stamp, commit and checkpoint PF7:** commit `feat: edit optional native dialogue through prompt forms`.

## Task 8 / PF8: Real Studio integration, documentation and branch verification

**Files:** Create tests/browser/prompt_forms.py using tests/browser/studio_fixture.py conventions; extend tests/browser/read_only_timeline.py; update guide/build/prompts.md, guide/story/cast.md, tests/README.md and CHANGELOG.md. Fix only integration issues demonstrated by these checks; no extra feature work.

**Interfaces:** Expose no production test API. The isolated browser fixture imports real TimelineEditor/Studio/TimelineHistory, serves this checkout's modules through Playwright routes and mocks bible/queue/storage. It never contacts ComfyUI, renders, starts a web server or edits a live project. Mock bible results follow Task 2's exact response. Browser actions use accessible labels.

- [ ] **1. Add regression assertions before fixes:** at 1440x1000 and 390x844, start from raw, partial and Story-source fixtures; add Cast, retention and Shot 2, edit custom Camera movement/Lighting/dialogue, switch Basic/Advanced/Raw, save/reload/import/export and Undo/Redo. Assert correct selected video prompt changes, no unexpected main/layer changes, source provenance retained with Edited by hand, ordinary bible wording updates respect manual differences, and stale results/read-only/draft guards work. Assert every recognized field is keyboard reachable, labels/errors are associated, text stays in the viewport and insertion/deletion keeps caret/focus. Also load the live-sized 88-clip fixture: editing one field never writes/reformats other prompts or reparses all clips per keystroke beyond existing cached shot extraction. Fixture failure output names each failed assertion; screenshots are local QA evidence only.
  ```python
  before = page.evaluate('stored()')  # Fixture helper returns the serialized Timeline string.
  page.get_by_role('checkbox', name='Advanced mode', exact=True).check()
  page.get_by_role('checkbox', name='Advanced mode', exact=True).uncheck()
  assert page.evaluate('stored()') == before
  assert page.evaluate('queued.length') == 0
  ```
- [ ] **2. Run the new browser test red where integration defects exist:** `uv run --with playwright python tests/browser/prompt_forms.py`; a clean first run is acceptable because component regression tests already went red in owning tasks. Fix demonstrated issues and re-run only affected cases until green. Perform visual QA per the UI skill at implementation time; do not use T3 preview tools unless browser work is requested then.
- [ ] **3. Finish documentation:** explain Add from Cast and schedule-only removal, optional/custom fields, seconds and continuation offset, Existing text preservation, cue text, Advanced visibility versus generation mode, unsaved drafts and accepted-guide restrictions. Add the isolated browser command/scope to tests/README.md. No unsupported render-quality promises. Add one concise CHANGELOG Unreleased entry for the complete behavior.
- [ ] **4. Run final verification once after fixes:** stamp modules; `node tests/run.mjs`; `uv run --with playwright python tests/browser/prompt_forms.py`; `uv run --with playwright python tests/browser/read_only_timeline.py`; `uv run --with-requirements requirements-docs.txt python -m mkdocs build --strict --site-dir .tmp/prompt-forms-docs`; `git diff --check`. Expect all suites exit 0, no product tests skipped for missing dependencies, no page errors, strict docs success and no changed live files. No GPU test, deployment or restart.
- [ ] **5. Review, commit and checkpoint PF8:** under the user-selected execution method, complete the branch review and fix findings, then commit `feat: complete structured prompt form workflow`. Mark passing only with fresh evidence. Hand back the branch/artifact and explicit remaining limits; do not merge/push/release without the task authorization in force at execution time.

## Verification environment and recovery

Both portable Python paths existed during planning: `D:/Projects/ComfyUI_windows_portable/python_embeded/python.exe` and `C:/Users/ricar/ComfyUI/ComfyUI_windows_portable/python_embeded/python.exe`. Follow tests/README.md. Prefer the configured H3_PYTHON/COMFY_ROOT; otherwise tests/run.mjs detects the latter portable installation. For focused Python commands in PowerShell, set `$env:H3_PYTHON` to the chosen embedded Python and invoke `& $env:H3_PYTHON -m unittest discover ...`; a direct `python` command above means that selected interpreter, not an instruction to install packages globally. Set COMFY_ROOT to the same installation's ComfyUI when CPU support fixtures need it.

Recover docs/roadmap-discipline/features.md and this phase's ledger before each task. PF0 covers the approved design and this plan; PF1-PF8 map one-to-one to Tasks 1-8. Only the current execution feature becomes active; tasks depend on previous interfaces and are sequential. Record partial edits, exact verification and the next executable action at each coherent checkpoint. Run the roadmap check before changing focus. The pending Phase 20 video watch-through is unrelated and remains preserved.

## Plan self-review and handoff

Self-review completed 2026-11-15: every approved spec section maps to Tasks 1-8; all five Review Focus conditions have explicit owning tests. Fixed missing shared edit kind/shot identity, explicit editor apply/revision contracts, cut/continue editing, and keeping official camera speed/amplitude in Basic. Verified the plan has eight PF-mapped tasks, forty checkable steps, file/interface blocks and the approved spec reference. This is plan/document verification; no product tests or browser/GPU work ran during planning.

Execution method was not selected when this plan was written. Recommended: Native execution, because the tasks share the same parser, field codec and editor state and must land sequentially; task-by-task fresh implementer contexts would add overhead. Offer Subagent-driven execution if the user prefers independent review at each task. Request plan review and execution choice before product edits, as required by writing-plans. Do not treat design approval alone as selection of a method or approval of unseen plan details.
