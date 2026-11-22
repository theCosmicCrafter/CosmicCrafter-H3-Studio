# Start a new generation

Approved outcome: user requested this after continuity recovery, keeping Timeline/prompts and old generation while every active render starts empty.

## Approach
Use a separate, empty native sequence folder instead of moving or deleting media. This clears all active clip/bridge renders at once and preserves every old video, latent, take and full-video export in the old folder. Keep exact Timeline text, prompts, guides, seeds, references, Story content and render settings. Project settings shows earlier generations with full/partial and individual clip links, including unfinished generations. Preserve a Timeline/settings snapshot in the new manifest history.

Alternatives considered: archiving all clips into Takes would mix generations and require copying the old full video before it is overwritten; deleting files would violate preservation. A fresh render folder reuses the existing name-based saved-render isolation with no media moves.

## Interaction
Project settings: Start a new generation. Confirmation explains all clips start unrendered, prompts/references remain, old videos stay available, and no render is queued. After success, status shows no active renders; render using existing controls. Previous generations stays accessible in settings.

## Safety and scope
Wait for uploads/writing/render jobs to finish. Confirm before changes, save existing edits, reject stale UI changes during requests. The backend rechecks queue state. Write the fresh manifest before switching node identity. A failed request leaves old state untouched. Attached projects start in a fresh native render workspace using their current generator graph; the old API project remains intact. No deployment or live rendering.
