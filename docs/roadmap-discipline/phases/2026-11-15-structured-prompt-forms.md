### Phase 21: Cast assignment and structured prompt forms

User request (2026-11-15): brainstorm and plan with roadmap-discipline and ponytail. Explain how to add an existing Cast character to a clip; if missing, design an Add from Cast action that creates the next Subject from the bible. Replace broad Sections textareas with optional, predictable schema-based fields, repeatable retention rows, ordered shot times, and an optional advanced mode based on the Singularity writing guide. Built-in suggestions must allow custom prose. No implementation requested yet.

Prior work: Phase 20 VID3/VID5 remain blocked on the user's watch-through, with files/evidence in 2026-11-14-release-videos.md. Existing dirty product files and local documents predate this task and must be preserved. Development checkout is main at 8db79824075a; no AGENTS.md at repository root.

- [x] **PF0** (State: `passing` | Verification: `source-backed current-behavior findings; user chooses approach and approves written design; implementation plan follows design approval`)
  - *Behavior:* Research current Cast/Sections implementation, official MiniMax prompt references and the linked Singularity guide; brainstorm tradeoffs and record an approved design before implementation planning.
  - *Evidence:* 2026-11-15: source-backed findings below identify schedule-only Add behavior and current lossless textareas. User chose text authority, relaxed strict Singularity format, then explicitly approved the written design ("Approved"). Independent design builder check: "nothing important left". Implementation plan at docs/superpowers/plans/2026-11-15-structured-prompt-forms.md written after approval and self-reviewed against every spec section. Fresh planning structure check passed: 8 PF-mapped tasks, 40 explicit steps, file/interface blocks, all required sections and approved-spec reference. No product behavior completion is claimed.
  - *Partial:* User approved the implementation plan on 2026-11-15 (second "Approved"); proceed with recommended Native execution, implementing tasks in this session with one independent final branch review. Setting up isolated native worktree before baseline/PF1. No product edits, product tests, live workflow changes, deployments or GPU work performed for this task yet.
  - *Sources:* https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/h3-prompt-writing/references ; https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity/blob/main/MiniMax_H3_Singularity_Prompt_Writing_Specification_Enhanced_EN.md
  - *Next:* Native handoff of this thread to feat/structured-prompt-forms from the local commits containing this ledger and the approved spec/plan; initialize worktree-local roadmap from the parent checkpoint, activate PF1, run baseline, and execute all eight tasks continuously under executing-plans. Preserve original parent product edits. No further plan approval is required.

- [ ] **PF1** (State: `not_started` | Verification: `node --test tests/js/prompt_sections.test.mjs tests/js/shot_split.test.mjs tests/js/ph3_still_prompt.test.mjs tests/web/endpoint_references.test.mjs`)
  - *Behavior:* Plan Task 1: lossless partial sections and safe source-range edits, including subject-only prompts and all shot-parser callers.
  - *Evidence:* None; implementation has not started.

- [ ] **PF2** (State: `not_started` | Verification: `node --test tests/web/cast_assignment.test.mjs tests/web/read_only_timeline.test.mjs tests/js/history.test.mjs; python -m unittest discover -s tests/python -t . -p test_cast_assignment.py -v`)
  - *Behavior:* Plan Task 2: atomic Add from Cast with next Subject, correct look/pictures, synchronized schedule/link, live reference validation and stale-result/Undo protection.
  - *Evidence:* None; depends on PF1.

- [ ] **PF3** (State: `not_started` | Verification: `node --test tests/js/prompt_fields.test.mjs tests/web/prompt_form.test.mjs tests/web/switch_sections.test.mjs tests/web/mention_layer.test.mjs tests/web/typing_commit.test.mjs`)
  - *Behavior:* Plan Task 3: typed definition/retention/summary fields, stable reference identity, blank/raw compatibility, deletion guards and accessible form panel.
  - *Evidence:* None; depends on PF2.

- [ ] **PF4** (State: `not_started` | Verification: `node --test tests/js/prompt_shots.test.mjs tests/js/shot_split.test.mjs tests/web/endpoint_references.test.mjs; python -m unittest discover -s tests -t . -p test_shot_split_server.py -v; python -m unittest discover -s tests -t . -p test_preview_targets.py -v`)
  - *Behavior:* Plan Task 4: playback/native shot timing, increasing boundaries, explicit cut/continue editing and atomic structural edits protecting accepted guides and references.
  - *Evidence:* None; depends on PF3.

- [ ] **PF5** (State: `not_started` | Verification: `node --test tests/web/prompt_form.test.mjs tests/web/read_only_timeline.test.mjs tests/web/typing_commit.test.mjs tests/js/history.test.mjs tests/web/track_editor.test.mjs tests/web/studio_navigation.test.mjs`)
  - *Behavior:* Plan Task 5: shot cards and unsaved structural drafts, with navigation/generation/history guards and one-step valid edits.
  - *Evidence:* None; depends on PF4.

- [ ] **PF6** (State: `not_started` | Verification: `node --test tests/js/prompt_fields.test.mjs tests/web/prompt_form.test.mjs tests/js/shot_split.test.mjs tests/js/ph3_still_prompt.test.mjs`)
  - *Behavior:* Plan Task 6: recoverable readable cue fields, Basic camera controls and optional advanced action/effect/lighting/acting/continuity details; custom suggestions and lossless toggles.
  - *Evidence:* None; depends on PF5.

- [ ] **PF7** (State: `not_started` | Verification: `node --test tests/js/prompt_fields.test.mjs tests/web/prompt_form.test.mjs tests/web/dialogue.test.mjs; python -m unittest discover -s tests/python -t . -p test_dialogue_compile.py -v`)
  - *Behavior:* Plan Task 7: optional native dialogue fields with exact words, stable speakers, voiceover/continuity syntax and current manual/recording ownership.
  - *Evidence:* None; depends on PF6.

- [ ] **PF8** (State: `not_started` | Verification: `node tests/run.mjs; uv run --with playwright python tests/browser/prompt_forms.py; uv run --with playwright python tests/browser/read_only_timeline.py; uv run --with-requirements requirements-docs.txt python -m mkdocs build --strict --site-dir .tmp/prompt-forms-docs; git diff --check`)
  - *Behavior:* Plan Task 8: isolated desktop/mobile Studio verification, save/reload/import/export/history/Story/read-only/performance coverage, docs and final branch review. No GPU work or deployment.
  - *Evidence:* None; depends on PF7. Phase 21 is not complete until PF1-PF8 pass with fresh evidence.

#### Implementation-plan self-review (2026-11-15)

Spec coverage: authority/optionality/preservation -> PF1/PF3/PF5/PF6; Cast -> PF2; schema/Basic -> PF3/PF5/PF6/PF7; timing/guides -> PF4/PF5; Advanced -> PF6; dialogue -> PF7; integration/success criteria -> PF8; global constraints and exclusions -> all tasks. Five Review Focus conditions have tests assigned in the plan. Shared interfaces agree across tasks. Self-review fixed explicit shot/kind identity for field edits, revision tracking for stale/ABA Cast replies, cut/continue controls, and official speed/amplitude remaining Basic. The plan is 8 sequential tasks. User approved the handoff; proceed with recommended Native execution because interfaces/state are shared. Do not ask for the same approval again.

Plan and approved-spec status committed as 259776f (only those two files). Staged whitespace check passed. Original parent-checkout product edits and local roadmap/history documents remain uncommitted and preserved. An execution workspace must start from this local commit or a descendant containing it so both approved artifacts are present.

#### Accepted decisions (2026-11-15 follow-up)

- The user approved the design, then separately approved the implementation plan and recommended Native execution. Isolation is part of the approved plan. Execute the complete plan continuously; no deployment, service restart, generation, merge or release is requested.
- User selected approach 1: native prompt text remains authoritative; no canonical structured prompt document.
- Incorporate useful Singularity detail as optional form fields and editable suggestions. Do not strictly enforce its formatting, ordering, templates or extended relationship markers. Official H3 syntax and existing Studio rendering/transport remain the compatibility baseline.
- The original request still applies: explicit Cast-to-Subject creation, schema-driven Basic forms, optional advanced details, custom creative values, ordered timestamps and safe switching between Sections and Raw text.

Approved design calls: readable per-shot cue lines recover newly authored advanced fields without sidecar metadata; arbitrary existing prose remains Existing text; UI times use playback seconds and translate continuation replay offset; accepted guide positions are protected; populated advanced details survive switching to Basic. The user approved the written design on 2026-11-15.

#### Source-backed findings (2026-11-15)

- Existing path: select clip -> Prompt -> In this clip -> Add…; requires timeline.bible. web/h3c_timeline_editor.mjs builds the section at lines 779-783; CastPage.chips renders it through web/h3c_cast.mjs. scheduleAdd() lists unscheduled characters/props and calls saveSchedule(), which only assigns box.schedule and commits. No new Subject or prompt text is created. The user's desired action is a real behavior addition; visibility on the user's running browser has not been verified.
- Sections currently requires an exact three-section base or six-section reference prompt. web/h3c_prompt_sections.mjs returns source ranges for section/entry bodies; writePromptSections replaces only those bodies. renderPrompt() in web/h3c_timeline_editor.mjs renders textareas and optional-section toggles. An empty/unrecognized prompt cannot currently enter Sections.
- Existing structured contracts are useful vocabulary, not drop-in UI schemas: h3_continuity/h3_prompt_schema.py makes every object property required for strict model replies, including camera.type and actions. The human form must permit omission and custom creative values. h3_prompt_compile.py emits native sections, stable dialogue tags and retention entries; Story also has a separate story_fast/story_bible_write compiler path. Do not claim one compiler covers all authoring paths without checking.
- Bible identity behavior already exists: story_bible.wording(), pictures_at(), line() resolve the look and pictures at the clip and format the Subject definition. Existing apply/recompile operations distinguish managed wording from hand edits. New manual form data must not be stored in box.source, which is reserved for Story provenance.
- Frontend persistence explicitly enumerates box fields in web/h3c_timeline_model.mjs. A new form document requires deliberate parse/serialize/history/transport support; server preservation of arbitrary metadata alone does not make a new field survive the UI.
- Official references fetched online: base-en.txt and ref-en.txt under MiniMax-AI/MiniMax-H3/main/skills/h3-prompt-writing/references. Base modes have three sections; Ref2VA has six. Subject, Picture, Video and Audio labels have different roles. Images used only for identity belong inside a Subject definition; standalone Picture entries are for frame/composition/storyboard anchors. Native render labels are per-clip bindings of stable @image/@video/@audio slots, not persistent source identifiers.
- Official visual retention markers are fully_preserved, partially_preserved, attribute_transfer, weak_reference; audio markers are fully_copy, partially_copy, reference, weak_reference. Subject entries use selected shot numbers, Picture entries additionally identify their frame/reference role, whole-video entries can have structural scope, audio entries need not have shot scope. Summary task types form another small predefined set.
- Official base guide requires no timestamp on Shot 1 and strictly increasing later cut times inside the generation duration. UI should accept seconds, serialize MM:SS.mmm and reject equal, decreasing, missing-required or out-of-range times before committing. Confirm continuation/carried-frame clock against existing shot split and preview helpers before fixing the exact field contract; never resize clips to fit a prompt.
- Singularity guide explicitly calls itself practical writing guidance, not undocumented MiniMax implementation rules. It retains the six-section Ref2VA structure. Its composition/action/camera/physics/lighting/acting details belong within detailed_description shots; it does not define a rigid order for every subfield. A deterministic order can follow its master template and must be documented as our design choice. Advanced is an authoring preference, independent of t2va/flf2va/ref2va.
- Singularity adds newly_generated to its suggested visual retention values. This is an extension relative to the official guide and must be identified as such rather than silently added to Basic's official enum. Creative options are suggestions with custom text; syntax enums and freely authored prose are different contracts.

#### Candidate schema inventory (proposal, not approved)

All content fields optional; an enabled populated feature still needs valid internal structure. Opening/switching modes must not add defaults or change prompt text. Empty values emit nothing; do not infer silence or inject N/A. A blank clip needs a deliberate form-creation path rather than requiring a pasted complete template.

| Area | Proposed controls | Output destination |
| --- | --- | --- |
| Subjects/references | Repeatable type/target, Cast binding, identity description, source slots and roles; pictures/looks resolved at this clip | subject_definitions in Ref2VA; preserve valid base-mode behavior when no reference makes the clip Ref2VA |
| Summary | Optional task-type chips from official set, custom summary paragraph | summary |
| Retention | Target selector, shot multiselect, role/scope where applicable, marker selector, detail text | retention_analysis; e.g. <Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved - ... |
| Shots | Repeatable shot cards; generated shot number; no Shot 1 time input; later start in seconds; cut/continuation intent; composition/action prose | integrated_multimodal_description or detailed_description according to actual mode |
| Camera (official/basic) | Suggested movement, amplitude, speed, custom wording | Natural sentences within the relevant shot |
| Dialogue/audio | Optional speaker, language, verbatim words and delivery/voiceover/singing; soundscape and score; reuse current cue/manual ownership | Native <d> and speaker contracts, overall_soundscape, non_diegetic_music |
| Advanced action | Optional initial state, trigger/preparation, movement, contact/reaction, recovery/end state | Expanded causal prose inside the shot |
| Advanced camera | Optional position/shot size, direction, speed/amplitude, followed Subject and focus | Camera passage inside the shot |
| Advanced effects | Repeatable trigger, effect kind/form, direction/motion and physical consequence | Effects/feedback passage inside the shot |
| Advanced lighting/acting/continuity | Optional light/material/focus fields; gaze/expression/breathing/posture/hands; carried object/body/environment state | Appropriate prose inside shot; never new unsupported top-level H3 sections |

Suggested option sources: official camera list already in h3_prompt_schema.py; Singularity adds orbit, swoop, whip-pan, dive, barrel roll, handheld/static descriptions. Its effects include energy/magic, explosions, sparks, smoke/dust, fragments, liquid, portals and lightning. Its lighting guidance covers direction, temperature, exposure/contrast, reflections, haze, depth of field and motivated motion blur. These lists are suggestions, not a claim of model parameter support; permit custom creative descriptions.

#### Approaches to discuss

1. **Text-backed lossless forms (recommended, ponytail).** Keep box.prompt as the saved/rendered source. Extend existing range parser with typed optional rows and a small schema of field metadata, enums and suggestions. Parse recognizable structures; retain original prose and unsupported fragments. Change only edited entries. A toggle never reformats the whole prompt. This minimizes migration and keeps direct native prompting intact; arbitrary prose cannot reliably be reverse-engineered into every advanced subfield, so advanced additions need explicit ownership/provenance or an unstructured remainder. Do not promise lossless automatic decomposition.
2. **Canonical structured prompt document.** Save a versioned optional-fields document per clip and compile it to native text. Gives exact field persistence and a clearer generator but requires frontend/server/history/import/export integration and a policy for raw edits that cannot map back. Reusing strict Story schemas unchanged would violate optional/custom-field requirements. More scope and a possible two-source-of-truth problem unless authority transitions are explicit.

Both approaches should present the same requested form capabilities; this choice determines how edits and imported raw prompts are preserved, not whether the UI has fields. A full form framework or generic schema engine is not justified; use existing DOM components and small data tables.

#### Proposed sequence and checks (not an approved implementation plan)

1. Explicit Add from Cast behavior: resolve active look, allocate next unused Subject without renumbering existing subjects, update prompt/cast/schedule together as one undo step, avoid duplicates, preserve unrelated prose and Story provenance. Handle blank, base and reference prompts and missing descriptions/pictures deliberately. Adding a description alone must not silently add a first-frame constraint or promise visual consistency.
2. Minimal prompt field schema/parser/serializer and compatibility contract, followed by the Basic editor's repeatable definitions, retention rows and ordered shots. Build on current mention controls and optional sections. Use stable slots internally so reference reordering does not retarget an entry.
3. Add advanced groups incrementally; blank groups do not serialize, and switching visibility never discards existing content. Preserve unsupported/raw text visibly at the relevant section or row rather than disabling the whole form.
4. Focused tests for add-from-Cast numbering/looks/duplicates and one-step undo; parse/write round-trips including unknown text and dialogue; Basic/Advanced toggle invariance; omitted fields; enums versus custom creative text; time validation including continuation clock; reference/shot deletion consistency; save/reload and Story rewrite/provenance; preview targets and shot splitting. Then appropriate full tests and guide docs. No GPU generation needed for structural correctness.

Minimum reload: this ledger; web/h3c_cast.mjs; web/h3c_prompt_sections.mjs; relevant renderPrompt/renderCastChips portions of web/h3c_timeline_editor.mjs; h3_continuity/h3_prompt_schema.py and h3_prompt_compile.py; story_bible.py and story_bible_write.py; timeline_model persistence; both linked source guides. Product design context read through Impeccable context: existing PRODUCT.md, Operate surface, existing visual identity; no DESIGN.md found. Do not rewrite global product context as part of this task.
