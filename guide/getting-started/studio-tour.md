# The Studio tour

Press **Open Studio** on the Timeline (or Story) node. The Studio fills the window; the close icon at the top left returns to the graph. **Esc** also closes it. Compact action buttons use icons with names on hover or keyboard focus; navigation tabs retain icons and labels.

[![The Studio](../assets/screens/studio-overview.png)](../assets/screens/studio-overview.png)

## Top bar

| Control | What it does |
| --- | --- |
| **✕** | Close the Studio. |
| **References** | Show or hide the left-hand references column. |
| *Project name and status* | The sequence name, the clip count and length, bridges and the render state ("All 6 boxes are rendered."). |
| **Undo / Redo** | Step backward or forward through Timeline edits. |
| **History** | Open the list of edits and jump directly to any retained state. |
| **New project** | Start a fresh project in this workflow. See [Full video and projects](../output/full-video-and-projects.md). |
| **Project settings** | Shared prompt, reusable **Still prompt conversion instructions**, settings for [long continuing chains](../continuity/long-chains.md#in-the-studio), and generation history. |
| **Download video** | Save the full video (enabled once every clip is rendered). |
| **Revise story** | Open the Story page at its feedback field to [patch a written story](../story/writer.md#editing-a-written-story). |

## Left: References

Every picture the Timeline knows about, with its `@imageN` name, a thumbnail, an **Enabled** switch and **Replace**. Turn a picture off and H3 no longer sees it. Details in [References and pictures](../build/references.md).

## Centre: pages

| Page | Use it to |
| --- | --- |
| **Viewer** | Play the **Full video** or a single clip's take. **Open in new tab** and **Download** are next to the switch. |
| **Story** | [Write the story](../story/writer.md): idea, template, scope, advanced model settings and feedback. |
| **Cast** | Build and edit the [Story bible](../story/cast.md): characters, places, props and looks. |
| **References** | Upload [Pictures](../build/references.md#pictures-saved-in-the-timeline) and manage reusable **RefMods** in one page. Existing links to either section still open it. |

!!! note "RefMods"
    RefMods are references stored as encoded H3 conditioning instead of pixels. The RefMods page lists them and needs the companion **ComfyUI-MiniMaxH3Mod** node pack (its numbered RefMod encoder); without it the page says to install it. They share the Timeline's reference slots, and a Timeline picture cannot take a RefMod's slot. This guide does not cover RefMods in depth.

## Right: the clip panel

The inspector follows the selected clip, audio lane, text lane or overlap. The clip header shows its number, length and frame count, with visible move, duplicate, delete and generate icons. **Generate clip N** requests one take; saved versions remain in Takes. The icon-and-label tabs support arrow keys, Home and End. Settings groups use full-width disclosure headings.

[![Prompt tab](../assets/screens/clip-prompt.png){ width=240 }](../assets/screens/clip-prompt.png)
[![Settings tab](../assets/screens/clip-settings.png){ width=240 }](../assets/screens/clip-settings.png)

| Tab | Contents |
| --- | --- |
| **Prompt** | The clip's prompt as **Sections** or **Raw text**, plus the references it mentions. See [Writing prompts](../build/prompts.md). |
| **Shots** | The First, Last and timed-shot guide images. See [First and last frames](../build/frame-guides.md). |
| **Takes** | The continuity check and saved takes. See [Takes](../continuity/takes.md) and [The continuity check](../continuity/check.md). |
| **Settings** | First and last frame, join, length, seed, bridge and visual memory. See [Timeline and clips](../build/timeline.md). |

## Bottom: the Timeline

[![The Timeline strip](../assets/screens/timeline-strip.png)](../assets/screens/timeline-strip.png)

From top to bottom: the icon toolbar (**Add clip**, **Render next**, **Render remaining**, **Prepare all still prompts**), frame markers, the time ruler, and your tracks. The persistent **Add lane** strip has video, audio and text icons. See [independent lanes](../build/timeline.md#independent-video-audio-and-text-lanes) for expand/collapse, snapping, overlaps and deletion.

- Each clip shows its number, length and render state (a ✓ once rendered, a thumbnail of its last frame).
- A **✂** marks a clip that cuts. The green diamond on a join is a [bridge](../continuity/joins-and-bridges.md#bridges).
- Drag a clip's right edge to resize it, or drag after the last clip to draw a new one. Click a clip to edit it.
- The audio and text icons add [audio](../sound/audio.md) and [timed text](../sound/timed-text.md) lanes.

## Undo, redo and history

Press **Undo** to reverse the last Timeline edit, or **Redo** to restore it. Outside a text field, **Ctrl+Z** (Mac: **Cmd+Z**) undoes; **Ctrl+Y** or **Ctrl+Shift+Z** (Mac: **Cmd+Shift+Z**) redoes. Text fields keep their own typing undo.

**History** lists named states such as *Add clip*, *Edit clip 2 prompt* and *Change width*. Select a row to restore that point, including all intervening edits. The current state is marked; later states remain available until you make a new edit, which replaces that later branch. Typing during one visit to a field is grouped as one edit, and a drag is one edit.

The latest **100 edits** are kept for each Timeline during the current session. Closing and reopening Studio keeps them; loading a different project, reloading the workflow or refreshing the page starts a new history. On a phone, the controls are under **More**.

History restores Timeline content (clips, prompts, guides, Cast, pictures, references, audio and text) and the Timeline's size/context settings through normal autosave. Writer results applied to the Timeline are included. Independent Story-node inputs and graph wiring keep their existing ComfyUI behavior. History does not cancel jobs, erase rendered files or recover permanently deleted files; live job receipts continue following the server.
