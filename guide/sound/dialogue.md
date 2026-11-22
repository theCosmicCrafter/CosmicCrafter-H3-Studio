# Dialogue cues

A **dialogue cue** holds a recording's exact words at the recording's own times: who speaks, whether they are seen speaking, and whether you have checked the cue against the recording. Clips speak the cues in their window as `<d>` lines, and [replacement bridges](../continuity/joins-and-bridges.md#replacement-bridges), unavailable for now, keep the footage where someone speaks on screen.

Cues belong to a recording on an [audio lane](audio.md), not to a clip. Splitting, moving or re-rendering clips never rewrites them, and moving or trimming the recording's clip moves where they play.

With **Lock audio to boxes**, cues follow each box's assigned source window when it moves or earlier lengths change. New and duplicated boxes receive no source cues from that lane. Splitting preserves source ownership; shortening through a cue still needs review. The recording's words and original timestamps stay unchanged. This box binding is separate from **Locked to the sequence clock**, which restricts bridges.

## Add cues

Upload a recording to `audio1`, `audio2` or `audio3`, then open **Dialogue cues** on the Studio's Audio page and choose the **Recording**.

| Control | Adds |
| --- | --- |
| **Import transcript…** | One cue per segment of a timed transcript of this recording (Whisper-style JSON with `segments`, `chunks` or a list of lines). Times are the recording's own; segments keep their speaker; empty segments are skipped. |
| **From Story** | The dialogue the [Story](../story/writer.md) planned for each clip, placed through this recording's clip onto the recording. Shown when the Story planned dialogue. Lines outside the clip's window are skipped. |
| **New cue** | A cue you type: start and end in seconds of the recording, the words, the speaker and the portrayal, then **Add cue**. |

Transcript cues start with an **Unknown** portrayal, because no one has looked at the footage yet. Story timing is planned, not measured. Either way, a new cue is **not checked**.

Cue words are only the spoken words: H3 control tokens such as `<d>`, `<|…|>`, `<scenetrans>` and `<cutoff>` are refused. [Timed text](timed-text.md) is separate: it is on-screen lettering, and importing it never makes cues.

## Edit and check a cue

Each cue has **▶**, which plays just that cue from the recording, its start and end, the speaker, the portrayal, **Checked** and **Remove**, with its words underneath.

| Portrayal | Means |
| --- | --- |
| **On screen** | The speaker is visible and their lips move. A replacement can't cover it. |
| **Voiceover** | No visible lips move with it. A replacement may continue over it. |
| **Unknown** | Not decided yet. A replacement treats it like on-screen speech. |

Tick **Checked** once the words and times match the recording, after listening with **▶**. Editing the words, the times or the recording clears the check; editing the speaker or portrayal keeps it. Checking binds the cue to the file its lane plays now.

Under each cue the Studio says what the Timeline made of it:

| Line | Means |
| --- | --- |
| Checked · plays 4.00–4.50 s in the video. | Where the cue lands on the Timeline's clock. |
| Not checked · … | It still compiles into the clip, but a replacement near an on-screen or unknown cue waits for the check. |
| … cut by the clip window: extend the clip or edit the words. | The recording's clip starts or ends inside the cue. The clip it falls in can't render until you fix it. |
| Outside the clip window, so no box speaks it. | The recording's clip doesn't play this part of the recording. |
| @audio1 has a different file than this cue was written for: … | The lane's file changed. Play the cue, fix its words and times, and tick **Checked** to bind it to the new file, or remove it. |
| @audio2 isn't in the Timeline or is turned off, so no box speaks this cue. | Its lane is gone or disabled. |

The video time of a cue is the clip's **Video start**, plus the cue's time, minus the clip's **Source in**, rounded outward to whole frames.

## How clips speak them

**Dialogue**, at the top of a clip's **Prompt** tab, chooses where its `<d>` lines come from. It appears once the Timeline has cues.

- **From the cues** (default): the cues in the clip's window become its `<d>` lines, timed on the clip's own clock, which for a continuing clip starts with its carried frames. The block opens with *Dialogue from the recording: speak only these exact words at these times; add no other speech.*
- **Typed in the prompt**: the clip keeps your own `<d>` lines and leaves the cues out.

A line that crosses a cut is one line. The clip it starts in is told it's still being spoken at the final frame; the next clip is told to finish the line already in progress, not start a new one. A voiceover line is phrased as an off-screen voiceover with no on-screen lips moving.

A clip that has typed `<d>` lines *and* cues covering it stops with *box 3 has typed <d> dialogue and dialogue cues from the recording also cover it*, so you choose: remove the typed lines, or set the clip to **Typed in the prompt**. Clips with no cues keep typed `<d>` lines as before.

At a cut where either clip speaks, [Visual memory](../continuity/visual-memory.md) leaves out the full preceding video, whose lip movement H3 would otherwise copy over the new clip's lines. The new clip remembers the five frames before the cut instead.

Changing what a clip is asked to say, its words, times, speakers or portrayals, makes it need a render. So does the clip after a cut, when the change decides whether either side speaks. Ticking **Checked** doesn't. A cue can't retime a clip that is already rendered: the words in the render move only when the clip renders again.

## Lock a recording

**Locked to the sequence clock** in the recording's audio settings, or **Lock recording** in **Dialogue cues**, keeps the recording where it is in the full video. The picture then adapts to the recording:

- no bridge may add time inside it, so **Insert bridge** is off and its cuts stay cuts. [Replacement bridges](../continuity/joins-and-bridges.md#replacement-bridges), which would bridge such a cut within the video's length, are unavailable for now;
- the Timeline's hint line names a lock that can't hold, for example:
    - *@audio1 is locked to the sequence clock but isn't in the full video: turn on In the full video, or unlock it.*
    - *@audio1 is locked to the sequence clock, but the bridge before box 4 inserts 1.21 s inside it, so the picture after it drifts from the recording: remove the bridge, so the join plays as a cut.*

Locking never moves, cuts or re-renders anything, and it doesn't change an existing bridge: remove an inserted bridge inside the recording. All locked recordings share one clock; none is moved to fit another.

!!! warning "A lock warns; it doesn't stop a render"
    The hint line, and `timing_conflicts` in a project's status over the [API](../automation/api.md), only *name* a lock that can't hold. A bridge that would add time inside a locked recording is still planned for rendering.

!!! warning "Without a lock, a bridge moves the picture, not the recording"
    A cue's time is on its clip's own clock, which never includes bridge time. Take a recording in the full video with a cue at 4.20 s, in a clip that starts at 3.75 s, and an inserted 29-frame bridge before that clip. The clip's speech still starts 0.45 s into the clip, but the clip now starts at 4.96 s in the full video, so the picture speaks at 5.41 s while the recording says the line at 4.20 s, 1.21 s apart. Nothing warns about this when the recording is not locked. To keep a recording and its picture together, lock it and keep the cut.

## Limits

- There is no automatic transcription, forced alignment or speaker detection. Cues come from a transcript, the Story or typing, and **Checked** means you listened.
- Nothing measures lips in the rendered footage. A cue's times are where the words are in the recording; whether a render's mouths match is for you to watch.
- Cue times are not changed to fit a clip window: a cut cue stops the clip until you extend the clip or edit the words.
- An inserted bridge does not move cues. Only a locked recording is protected from one, and only by a warning.

!!! note "Older installs"
    An older H3 Continuity install ignores dialogue cues and locks, and its Studio drops the cues and each clip's **Dialogue** choice when it saves.
