# Troubleshooting and limits

## The nodes don't appear

- Restart ComfyUI **and** refresh the browser so the matching frontend loads.
- Check the console for an import error. Confirm `requirements.txt` was installed into the Python that runs ComfyUI.
- Make sure only **one** copy of H3 Continuity is installed; two copies register the same nodes and routes.

## Open Studio does nothing, or the Studio looks old

The page is still running the frontend it loaded before the update. After updating the node pack, restart ComfyUI and refresh the page. A normal refresh is enough: an update gives every changed frontend file a new address, so the browser fetches it again instead of using a cached copy.

## The Timeline opens read-only

"This Timeline needs a newer H3 Continuity (…)" means the Timeline was saved by a newer version that uses a feature this one doesn't have, named in the brackets. To keep what it doesn't understand, the Studio doesn't save any change to that Timeline: an edit is undone at once, and **+ Clip**, Render and Generate are off. You can still select clips and play their takes. Render, Write and the continuity check refuse it on the server too. Nothing in the Timeline is lost. Update the node pack, restart ComfyUI and refresh the page to edit or render it.

## A clip says it needs a render

A clip is current only while its prompt, seed, length, join, pictures, RefMods, guides, audio clips, timed text, memory and the node's settings match its saved render, and (for a continuing clip) the clip before it. Point at the clip's marker for the reason. Nothing renders until you ask.

## "Render box N first"

A bridge, a memory moment or a continuing clip needs a rendered neighbour or source. Render the named clip first.

## A long Render fails with "Unable to allocate" or "Cannot allocate memory"

ComfyUI ran out of memory on the PC: RAM and the Windows page file together, not the GPU. The failing node is usually one that loads or decodes a whole finished video after H3 Timeline, such as a refinement or upscale step. Back-to-back runs raise the peak, and ComfyUI recovers once it idles. Render stops at the first failed run and keeps the rest unqueued, so press **Render** again after the PC has been idle for a minute. If the same clip fails twice, shorten the clip, lower the size that step works at, or make the page file larger.

## A continuing clip refuses to render

After a clip that [drops frames](../build/exact-lengths.md#cuts-after-dropped-frames), the next clip must be a **Cut**, and a continuing clip needs the clip before it to play at least `context_frames` frames.

## The check won't start

It needs a linked H3 Story node and an empty ComfyUI queue. See [the continuity check](../continuity/check.md#the-queue-and-the-gpu).

## Take actions are greyed out

**Use** and the deletes are off while a run of this sequence is running or queued, and briefly after an edit until the Studio reads the new status.

## Write is refused

A missing or unreadable [template](../story/templates.md#a-missing-template), a running continuity check, or an unreachable endpoint. The Story panel names the cause.

## Boxes appear as *clips*

The Studio says **clip**; older notes, saved JSON and some messages say **box**. They are the same thing.

## Known limits

- **Quality is the model's.** Continuity features give H3 more context; they don't guarantee identity or geometry. Inspect each join.
- **Arbitrary-view geometry from still generators is experimental.** Reference delivery does not establish exact reconstructed geometry.
- **Long clips** (past 362 frames) need ComfyUI's Context Windows node and `max_frames`; the Studio keeps `max_frames` but can't set it, and the Story planner stops at 362. Results were measured on one GPU setup and judged from frame statistics, not by eye. See [Long clips](../build/long-clips.md).
- **Bridges** send no pictures, references, guides, timed text or memory. Inserted bridges lengthen only the full video; replacements keep its length.
- **Replacement bridges are unavailable.** Generated candidates still jumped at their joins in tests, so nothing renders or plays a replacement and the original cut plays. A cut inside a locked recording stays a cut.
- **Dialogue cues** are typed, imported or taken from the Story; nothing transcribes, aligns or checks lips for you.
- **Voice clips** never play in the full video.
- **One Timeline per sequence.** Two tabs on the same sequence can fight over which take is in use.
- **Models and providers are separate.** H3 Continuity downloads no model weights and provides no credentials; the optional MiniMax prompt guides are not bundled and are subject to MiniMax's terms, including territorial restrictions.
