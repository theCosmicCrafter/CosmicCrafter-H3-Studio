# Incompatible saved overlap: proposed recovery

Status: approved by user on 2026-11-06 ("cool, proceed with those changes").

## Intent
Allow regenerating an earlier clip when the saved following continuation cannot constrain its ending, with an accurate warning before queueing and preservation of existing videos.

## Diagnosis
At main 3b2d569, timeline_node.py:768-813 inspects the immediately following saved box. For a continuing next box with the same id, reuse requires an existing saved latent file, matching latent width/height, and positive saved context_frames. When those conditions fail and no explicit rebuild exception applies, selected-box rendering raises the reported error. A prior cut now changed to Continue is one possible zero-context case. The user's exact failing condition is unknown: no live manifest was inspected.

A compatible next box constrains the new ending through latents.build_ending. That helper has further size, length and audio checks. A complete implementation must preflight these too, without changing approved durations to fit them.

nodes.py:347-355 archives only the selected Timeline box by id and keeps all other saved segments regardless of preserve_following. timeline_node._status and timeline.next_box treat outdated takes as present. Therefore bypassing the exception alone neither clears following renders nor makes Render remaining rebuild them.

## Approaches
1. Keep the hard error: protects the join but provides no practical recovery.
2. Proceed and keep following clips as outdated: preserves playback but still needs individual regeneration; ordinary Render remaining skips them.
3. Recommended: confirm before queueing; after a successful replacement save, archive affected dependent renders as takes and mark those clips as needing a render. Existing videos remain available in Takes; ordinary Render remaining can rebuild missing clips in order. User approved this approach.

## Proposed interaction
Title: Regenerate clip 1 and rebuild continuity?
Message: Clip 2's saved starting frames cannot be reused with this render. If you continue, [affected clip list] will be marked as needing a render and removed from the current assembled video. Their existing videos will be kept in Takes. Render those clips again to restore continuity and the complete video.
Actions: Cancel / Regenerate clip 1.

Use actual clip numbers and the specific incompatibility reason. Show no warning when the join can be preserved. Queue only the requested regeneration; rebuilding the affected clips is a separate explicit Render remaining action.

## Constraints and implementation notes
- Compute the actual dependency closure: Continue links, visual memory (including dependencies across cuts), and bridges/replacement regions that read changed footage. Preserve independent later clips; an independent cut stops continuation propagation but is not proof that memory is independent.
- Confirmation is read-only. Queue failure, render failure or cancellation before a successful replacement save leaves existing renders in place. Revalidate the exact approved affected set against manifest/settings at execution/save, and reject changed state rather than clearing unapproved data.
- Persist archival and new render state together with safe failure handling. Do not delete any takes. Do not promise universal restoration of incompatible takes: current take selection checks both neighbors.
- Update full/partial video state to reflect missing clips, and keep prompt, duration, seed and reference edits intact.
- Cover both classic queueing in web/h3c_timeline.js and project-backed planning in web/h3c_project.mjs / timeline_api. Do not expand generation scope implicitly.

## Evidence
CPU-only unittest discovery for test_durable_renders.py: 18 tests passed on 2026-11-06. Tests cover archival by box id, retaining other boxes, outdated status, and assembly. No GPU generation, UI implementation, deployment, restart, or live workflow inspection.

## Implementation status
Implemented and verified locally. See the IO1-IO3 roadmap ledger and implementation plans for current evidence. Classic consent additionally binds saved editor state; static linked settings resolve before preflight and dynamic producers defer to execution. Incompatible recovery requires one take initially. No live rendering or deployment.
