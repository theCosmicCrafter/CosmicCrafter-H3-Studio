# Timeline timed text

In the Studio (**Open Studio** on the Timeline node), press **+ Whisper JSON** above the Timeline boxes to choose
a local transcript. Supported JSON
contains Whisper `segments` (optionally with word timings), `chunks` with two-value timestamps,
`words`, or a raw timing array. Phrases, Unicode, whitespace and supplied word precision stay exact.
The browser parses the file locally and hashes its original bytes; it does not upload the transcript.
Import errors leave the previous attachment intact. H3 control tokens such as `<d>`, `<|…|>`,
`<scenetrans>` and `<cutoff>` cannot appear inside literal phrases or words.

Open **Timed text · Whisper JSON** to enable or remove the attachment, choose **Text audio lane**,
set **Sync text to audio**, or describe the text's typography, placement and motion in **Text visual direction**.
Imported text initially uses independent timing. While independent, set **Text video start (s)**,
**Text source in (s)** and **Text length (s)**. While synced, the chosen lane's live placement and
source window drive text; moving or trimming audio never rewrites transcript timestamps. Source-in
30 and movie start 0 places source cue 30 at movie 0. Turning sync off copies the current resolved
clock. A missing selected lane stays selected and shows an inline message. Disabling audio
conditioning does not disable its text clock.

The cue display shows the selected box's source window, local cue milliseconds, carried replay,
continuing phrases and replay-only phrases at 24 fps using delivered, snapped box lengths. A
projected cue with `continues_after:true` remains active beyond the box: its clipped end is a
coverage boundary, so the prompt retains its lettering through the final generated frame.
A cue ending exactly at the boundary or at the selected audio/text range does not carry this flag. Exact
phrases enter native H3 visible-lettering prompts separately from spoken `<d>` dialogue. Under the
Prompt tab, **Effective H3 prompt and text window** shows the backend's final reference-rewritten
prompt and projected window once current settings/status resolve. Edits refresh render status and
saved Timeline state; they do not start Story writers. Completed outputs whose effective text
changes become stale according to the backend's continuity checks.

Timeline JSON and revisioned saved snapshots retain the attachment. Story results carry their
original text and resolved clock. If those inputs change during Write, subsequent results stop
applying and show a note; earlier applied prompts and concurrent user edits remain. Undo changes
only the Story-owned prompts/metadata and leaves current text and audio edits intact.

A saved guide or plate can carry a lettering contract: `visible_text` and `text_contract` record the
literal phrases and text direction active where the image applies. Earlier versions recorded them when
they generated a still or plate; an external caller can pass them with an accepted image (see
[External Timeline](EXTERNAL-TIMELINE.md)). Editing the timed text never rewrites a saved contract.
Before rendering, the backend compares each contract with the timed text now active at the guide's
frame, or at the first frame of each box that uses the plate, and stops with "timed text changed;
restore the text or remove this lettering image" when they differ. Images without a contract, such
as ordinary identity and world plates, are not checked. Continuation frame 0 is the previous box's
final frame; frame 1 is the first appended frame. A contract records which lettering was requested;
check the images themselves for actual spelling and visual quality.

Cue intervals are native H3 prompting requests. Inspect actual rendered spelling, onset, clearing
and continuity; the model can miss those requests even when source clocks and frame counts pass.
