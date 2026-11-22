# Studio tracks and editing workspace

Status: approved direction, 2026-11-14 (user: "great, let's continue"). Builder check completed; bridge policy clarified below. Implementation plan requires review before execution. No product code changed.

## Intent and confirmed decisions

Make adding video discoverable and use the workspace like a video editor. The user's seven screenshots identify the current friction; their Resolve screenshot establishes the interaction and layout direction. This is an Operate surface: precise, compact and familiar.

The user explicitly selected independent video tracks. Each track holds clips with their own placement; clips snap to clip boundaries on other tracks. Upper tracks show over lower tracks; gaps reveal lower tracks. The existing multiple-video switch, fade and sound controls must remain usable for overlapping videos.

This supersedes the original video-layers design's decision to avoid independent tracks. Existing stacks and projects remain readable and editable. Rendering, save/load, history, previews and export must support the new timing; this is more than CSS work.

## Approaches

1. Expose the existing per-clip stack Add Video control in the timeline. Smallest implementation, but the user explicitly rejected this because it cannot place independent clips.
2. Independent typed tracks with explicit clip placement, coupled to a compact workspace and shared overlap controls. Selected by the user. Requires changes to timing, rendering and assembly as well as the editor.
3. A full compositing editor with transforms and opacity automation. Not requested; upper-track visibility and the existing transition controls cover the stated behavior.

## Visual direction

Use the existing cool graphite identity with Resolve's information hierarchy. Base palette: canvas #15171C, panels #1D2027, raised controls #2B303A, separators #3C4350, text #E0E3E9, selection #729CDD. Audio keeps its existing teal waveform coloring. Color identifies selection, state and media type rather than decorating panels.

Keep the platform sans font, 12px secondary labels, 14px controls and 16px panel titles. Left align all editor labels and forms. Use a coherent set of 16–18px stroke SVG icons with accessible names, tooltips, keyboard focus and disabled explanations. Desktop icon targets are at least 28px, touch targets 44px. Navigation tabs have icons plus labels; compact action toolbars use icons only. This distinction keeps navigation learnable while removing repetitive button text.

The distinctive element is the working timeline with fixed track headers and aligned clip boundaries. Avoid marketing treatments, display fonts, decorative cards and ornamental motion. Reviewed against the brief: familiar editing conventions serve this product better than introducing a new visual identity.

```text
Project name                    undo redo history | new settings download | close
-------------------------------------------------------------------------------
Library / references | Viewer  Story  Cast  References       | Clip 3       actions
                     |                                      | generate
                     |             Viewer                   | icon tab strip
                     |                                      | property groups
---------------------+--------------------------------------+------------------
Timeline   add clip / render next / render remaining / prepare stills    zoom
             First / Last / Shot markers for selected video
V2   delete |           [ Clip B --------- ]
V1   delete | [ Clip A ------------------------- ][ Clip C ----------- ]
A1   delete | [ waveform --------------------------------------------- ]
             Add lane: video / audio / text
             time readout / selection / snap state
```

## Combined and expanded timeline (latest user proposal)

Keep the current compact combined video presentation, with an expand/collapse control revealing individual video tracks on the same ruler. The combined row represents final visible output and switch/fade points. Expanded rows expose independent clip placement and cross-track snapping; audio and text remain below. Collapsing changes presentation only, never placements, selection, generation or output. Reuse the existing stack presentation and controls where possible; independent placement still requires the underlying model work. This interpretation was approved by the user; it does not revert the independent-track requirement.

## Timeline and track behavior

- Replace empty Audio and Text placeholders with one persistent add-lane strip: video, audio, text. Each icon names its action on hover/focus.
- Video creates an empty independent track above existing video tracks and selects it. Add Clip inserts on the selected video track at the playhead. Audio/text create an empty typed lane, then offer the existing file/connected-source or Whisper import flow. Cancelling import leaves an empty lane that can be deleted immediately.
- Lane identity and order persist in the project, including intentionally empty lanes. Audio retains native H3 reference capacity limits with visible explanations; adding lanes must not silently increase model inputs. Text remains timed text, using the existing Whisper JSON workflow.
- Track headers stay visible while the time area scrolls. They expose type, track name and delete. Any lane containing authored clips, an audio source or text cues requires confirmation naming the lane and its contents. Empty lanes delete immediately. Undo restores the lane, its order, clips, placement and associated settings. Removal never deletes media files.
- Clip movement changes placement without shifting other tracks. Snap starts and ends to other clips' starts/ends across video tracks and to the playhead. Preserve existing beat snapping; a temporary bypass allows precise unsnapped placement. Show a vertical alignment guide while snapped. Resize preserves H3 frame rules and exact-length behavior.
- Proposal for overlap controls: default visibility follows track order. Selecting an overlap exposes the existing switch point, fade length and sound choice in the inspector. They act on the two overlapping clips, bounded to their common time. Existing stacks keep their current settings. Selecting a third overlapping video must identify the affected pair explicitly, rather than silently changing an unrelated transition. No new transform/opacity compositor is implied.
- Proposal for generation: Continue refers to the preceding adjacent clip on the same track. A gap requires Cut or New scene, with an explanation. Audio and text use absolute film time. Existing saved projects migrate to one video track with their original timing and stack settings, without rerendering unchanged media. Timeline length is the latest clip end; output length also includes insertion bridges; a picture gap across every track is black. Reject unsupported track data read-only in older versions through a new feature requirement.
- Proposed sound default is the visible video's generated sound, respecting the existing original-soundtrack policy. Cross-track transition sound uses the same choices as current stack transitions. Overlapping text tracks remain independent and must not overwrite each other's cue data.
- Fill the timeline pane with its actual track area; remove the unused footer gap. Keep the existing draggable viewer/timeline divider and saved sizing. When more tracks exist than fit, scroll vertically inside the timeline. Put the one-line editing hint in a compact status footer.

## Toolbars, tabs and inspector

- Timeline actions sit on one horizontal icon toolbar: Add clip, Render next, Render remaining, Prepare all still prompts. Show counts/status in tooltips or adjacent compact status text. Move Still prompt conversion instructions to Project settings, retaining its existing storage and behavior.
- Main project toolbar uses icon actions for Undo, Redo, History, New project, Project settings and Download video. Preserve disabled/busy behavior and history shortcuts.
- Center navigation becomes semantic icon-and-label tabs: Viewer, Story, Cast, References. References contains Pictures and RefMods as two labeled sections, with existing deep links routing into the correct section.
- Inspector header shows the selected clip/track and duration. A compact visible action row exposes move earlier/later, duplicate and delete, replacing the Clip actions accordion. Generate becomes a primary icon action with a precise tooltip and running state. Remove the takes count input from this header; Generate requests one take.
- Inspector tabs: Prompt, Shots, Takes, Settings, with one consistent icon vocabulary. Property groups within Settings follow the Resolve pattern: full-width disclosure header, concise aligned label/value rows, clear selection context. Preserve all current fields, mode warnings and reference navigation. Selecting audio, text or an overlap gives the corresponding inspector content, never stale clip settings.
- On narrow screens retain the existing page/drawer navigation; tabs may scroll horizontally, and fields stack into one column. Do not squeeze three desktop columns into a phone viewport.

## Cast reference preparation

Replace the expanded form for every asset with a master/detail view. A compact toolbar shows category filters (Characters, Locations, Objects), a count of references needing work, Generate missing, generator settings and batch progress/stop. Keep batch inclusion distinct from whether an approved reference is enabled for generation.

The reference list shows thumbnail, name, category and plain status (Missing, Candidate, Approved, Outdated). Selecting an asset opens its detail editor: larger approved image/candidate preview, visual description, used-in-clips link, Generate/Upload, and candidate choices with Use as reference. Seed and dimensions move under Advanced. The Add object form opens on demand from Add object. Uploaded references remain immediately ready; generated candidates still require approval. Keep existing approval fingerprint checks, stop-after-current behavior, pending states and errors.

List/filter selection is session UI state; edits and approvals retain their current project history. On phones the list and detail become navigable panes with a Back action. Preserve selection/focus through asynchronous catalog refreshes and show the selected asset's failure locally.

## Implementation boundaries and verification

Primary UI surfaces: web/h3c_studio.mjs, h3c_timeline_editor.mjs, h3c_audio_lanes.mjs, h3c_reference_preparation.mjs, h3c_frame_images.mjs. A shared icon helper avoids repeated SVG fragments. Track placement affects both JS/Python models, planning, predecessor lookup, audio/text clocks, saved segment identity, assembly, partial preview, API schemas and history; inventory all consumers before implementing the track model.

Build in reviewable slices: (1) typed tracks, placement and compatibility; (2) generation/assembly and overlap controls; (3) timeline editing/lane lifecycle; (4) workspace and inspector; (5) cast preparation. Do not ship decorative empty video rows before playback/export can honor them.

Required evidence: old single-track fixtures keep timing/output; cross-track snap/bypass; gap/top-track/overlap playback; same-track Continue and gap validation; unchanged audio/text film clock; nonempty deletion cancel/confirm/undo; independent text preservation; migrated stacks; save/load and older-reader protection; render/partial/export agreement. Cover icon accessible names, tab keyboard behavior, read-only guards, async reference refresh and approvals. Run the full existing suite, module stamping, strict docs and desktop/mobile browser checks. Visually inspect the seven requested areas in a realistic populated project at desktop and phone sizes.

## Builder check and bridge clock policy

The independent builder check found one important contradiction: insertion bridges add output time, so latest clip end alone cannot define movie length. Preserve the existing two clocks. Clip placements, audio conditioning and timed text use the bridge-free Timeline clock. An insertion bridge is a global output event: it pauses Timeline advancement, plays its generated frames, then resumes every video track at the same Timeline frame. Output length is latest clip end plus inserted frames. Keep the current continuous-versus-box-bound original soundtrack behavior through those insertions; do not silently retime a recording. Replacement joins substitute existing coverage between adjacent clips on the same track, with no extra time. The combined output row and playhead map between both clocks explicitly. This is a builder clarification that preserves existing behavior, not a new ripple-edit feature.

Same-track clips cannot overlap. Continue requires exact adjacency on the same track; first clips and clips after gaps require Cut/New scene. The existing Cut requirement after legacy stacks remains. Moving a clip does not silently change its join; invalid joins are flagged before generation.

User chose native implementation in this session with one independent whole-change review. No per-task implementation delegates.

## Approval and scope

The user approved continuing with this design. The overlap interaction, same-track Continue rule, empty-lane persistence and compact inspector arrangement are builder decisions captured here. A plan review is the remaining pre-implementation gate required by writing-plans. No live project edits, GPU generation, release, deployment or ComfyUI restart are needed for design review.
