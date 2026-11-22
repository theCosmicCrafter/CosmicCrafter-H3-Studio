# The Story bible

The Story bible is the Timeline's list of characters, places and props. Each entity has a name, a kind, its pictures, a description and its looks over time; each box records which of its subjects is which entity. It lives in the Timeline, so saving the workflow, Export and Import carry it. Rendering never reads it: the box prompts are still what renders. After rendering, the Story's Vision model can check each box against it, as [the continuity check](CONTINUITY-CHECK.md) describes.

## Build bible

Open the Studio's **Cast** page. Until a bible exists it says "Build bible links each box’s subjects to characters, places and props. Nothing that renders changes." and offers **Build bible**.

Build bible reads every `<Subject N> is …` line in the boxes' subject definitions, and the linked Story's saved plan when that Story wrote this Timeline. It works without a plan. It writes no prompt. Its summary reads like "4 entities from 4 boxes. Mara has 2 looks. Nothing that renders changed.", followed by any line it left unlinked and why, such as a line the bible can't reproduce exactly.

## The Cast page

One row per entity shows its first picture, its name and kind, the boxes it appears in, its number of looks and, in amber, how many of its boxes differ. Click a row to open the entity:

- **Name** and **Kind**.
- **Pictures**: **Replace…** swaps a picture for another connected image or visual RefMod in the entity's wording and in its boxes' lines. **Upload…** under the Replace… picker and under a look's picture picker uploads a new picture into the Timeline and uses it in the same edit, as [Timeline pictures](TIMELINE-PICTURES.md) describes.
- **Boxes**: one cell per box, colored by the look in force there. A cell is amber where the box differs and empty where the entity isn't linked. Click a cell to select that box.
- **Description**: edit it and press **Apply**; **Esc** cancels. Apply writes the new wording into every box where the description is in force, and marks its retention line partially preserved. A box written from the bible is compiled again whole, as [Cast edits after Write](#cast-edits-after-write) describes; in any other box only that subject's definition line changes, and shot text, dialogue, sound, music and timestamps stay as they are.
- **Looks**: a look applies from its box until the next look. Each row has its starting box, its wording with **Apply**, **Delete**, and its picture with **Picture…**, as [a look's picture](#a-looks-picture) describes. **+ Look from box N** starts a look at the selected box with the wording in force there.
- **Merge into…** links the entity's subjects to another entity, and the lines that were in step take its wording. **Delete entity** unlinks its subjects and changes no prompt.

After each change a one-line note says what happened, for example "Updated 6 boxes; box 6 differs and was left alone." If the Timeline changes while a change is on its way, nothing changes and the note says "The Timeline changed while the bible was updating; try again."

## Boxes that differ

A linked subject differs when its line isn't the line the bible gives it, for example after you edit the Prompt tab or Write rewrites the box. Bible edits leave differing lines alone. The entity lists each one with three choices:

- **Use the bible’s wording** writes the bible's line into that box.
- **Make it a look from box N** keeps the line and makes it the look from that box on.
- **Someone else…** links the subject to another entity, or to a new one made from the line.

## The Box page chips

Above the Box page's tabs, chips list the selected box's subjects. "Mara · from box 5" names the entity and the look in force; an amber chip differs; a grey "Subject 3 · not linked" chip has **Link…** to link it to an entity or to a new one. Click a chip to open its entity on the Cast page.

A box that Write rewrites as plain prose loses its links. When the Studio opens, or switches to the Cast or Box page, it links those boxes again by the Story's plan or by picture, and lists any subject it can't match.

## Writing with the bible

Write uses the bible when the Timeline has one, and when it plans an empty Timeline, which starts one. A Timeline with boxes and no bible writes as before; build its bible first to write with it.

**Planning.** The planner reads the bible and never changes its entities. It may add the characters, places and props the story needs, each with a kind, a description and a voice, and give them connected pictures that no entity has. A picture that a planned box lists and no entity has becomes a character named after the picture's title. Each box gets a schedule (the entities in it and its place) and a join. A schedule or join you saved is kept, and a join that the box's Cut and New scene flags rule out is corrected, with a note.

**Schedules.** With a bible, the Box page's chips show the box's schedule: a chip per entity, which opens it, with × to take it out, then **Add…** and **Place**. A box without a schedule shows its linked subjects, and **Add…** starts a schedule from them. Merging or deleting an entity updates every schedule.

**Joins.** With a bible, the Box page's **Join** selector replaces the Cut and New scene switches: Continue, Transition, Cut or New scene, with an optional note. It writes the same flags, so rendering is unchanged, and the writer stages the join it is given.

**Style and voices.** The Cast page's **Style** row, above the list, holds the look every box shares, and each entity's **Voice** says how it sounds. **Apply** saves either one; an empty value removes it. A box written from the bible takes the change at once, as [Cast edits after Write](#cast-edits-after-write) describes; any other box takes it the next time Write writes it. A character can also have a recording of its voice, as [Voice clips](#voice-clips) describes.

**The compiled prompt.** The writer names entities by id, and code writes the prompt from the wording in force at that box. In a Ref2VA box, each entity whose picture the box renders gets its definition line; every other entity in the box gets a sentence such as "Tom is a tall man in a grey suit.". The style and each speaker's voice come from the bible. The writer's reply is kept as the box's source. An entity whose picture isn't connected, or doesn't fit in the box, is left to the writer's prose, with a note. A definition line you edited by hand gets the bible's wording back when Write rewrites its box, with a note; edit the entity on the Cast page instead.

**What the writer is told.** With a bible, the planner and each box writer get instructions of their own. They start with the order to follow when things conflict: the Guide, then the idea, the bible, the box's plan, the shot rules, and last the general H3 guidance. A [template](STORY-TEMPLATES.md#what-write-does-with-a-template) ranks after everything you wrote: after the bible for the planner, and after the box's plan for a box writer. Every box of a Write gets the same instructions. The bible takes the place of the continuity sheet, so a plan made with it has no sheet, and box writers never get one, not even from a plan saved before. Story feedback and Update prose don't send a sheet or ask for one either, and a plan saved before keeps the sheet it has.

**Looks.** When the writer changes how an entity looks, the change becomes a look from that box, and a note says so. If the entity already has a look from that box, Write keeps the existing one and says so. In each box where an entity in the schedule has a look in force, Write asks the writer to name that look in every shot that shows the entity, because the video follows the shots more than the definition line.

**Undo.** The Story's **Undo** puts back the bible and each box's links, source, schedule and join, where you haven't changed them since. If the bible changes while Write works, Write keeps yours and the note says so.

### A look's picture

A look can have its own picture. When a character changes outfit, choose the picture that shows the new outfit with the look row's **Picture…**; **None** takes it away. Every box where that look is in force shows its picture instead of the entity's and reads fully preserved, and wording that named the old picture, such as "in @image1", names the new one. A later look without a picture, like soaked, keeps the picture in force and says the change in words, and its row says so. Boxes that Write wrote take the new picture at once; a picture that doesn't fit in a box is left out, with a note. Write and the planner never choose a look's picture.

## Voice clips

A character can have a voice clip: a recording of its voice that H3 hears in the boxes where the character speaks, so the voice stays the same from box to box. On the Cast page, open the character and press **Upload…** in its **Voice clip** row, under **Voice**, or drop an audio file onto the row. The file goes to ComfyUI's `input/h3_audio`, as lane uploads do, and the Timeline keeps it on a slot of its own, from `@audio4` up. The row then shows the file and its length, such as "tom.wav · 12.0 s", with **Play**, **Upload…** and **Remove**. H3 hears the whole file each time, so over 30 seconds the row says that a shorter sample costs less memory and time. A file that can't be read isn't added, and the page says why. Places and props have no voice clip.

**Which boxes send it.** A box written from the bible sends the clip when the character has a line in it, voiceover included. A box where the character is silent has no use for the voice, and each clip takes one of H3's three audios there and the time to read it whole. The prompt gets two lines for each voice: under the subject definitions, "@audio4 is the voice-timbre reference for Tom (S1).", where a character the box shows by its picture is named by its label, such as "<Subject 2> (S1)"; and under retention, "@audio4: reference - Tom (S1) follows @audio4's voice timbre and measured delivery without copying the original signal." A box that sends a voice is Ref2VA, so its start and end frames become guides. Unnamed speakers, such as a radio announcer, never get a clip. A box you edited by hand keeps its text; **Recompile from source** brings the voice in.

**Room.** The voices take what is left of H3's three audios in the box after its lane clips and the audios it mentions, in the order the characters first speak. A voice that doesn't fit is left out, with a note such as "Box 2: Tom speaks, but H3 takes no more audios there, so Tom's voice (@audio4) isn't sent."

**The summary.** A start-frame, end-frame or text-only box needs the Ref2VA summary to send a voice, and Write asks for it when a character with a clip is scheduled in the box. A box written before its character had a clip has none, so it keeps its prompt, with the note "Box 3 was written without a summary, so it can't send Tom's voice; write it again to add it." The notes show in the Story panel after Write, and on the Cast page after an edit that changes a voice clip.

**The reference switch.** The Studio lists each clip among the Timeline's audio references as "Tom’s voice", or by its file name when no character has it, with its switch. Switching it off works as for any audio: H3 doesn't hear it, its mentions read "the described sound", and no prompt changes.

**Changing it.** **Upload…** on a character with a clip replaces the file and keeps the slot; the boxes that send it then need rendering again. **Remove** takes the clip off the character and out of the Timeline, and the boxes compile again without it. Deleting a character removes its clip, and so does making it a place or a prop. Merging keeps the kept character's own clip; if it had none, it takes the merged one's, and any other clip leaves the Timeline. Each of these is one Cast edit, so Ctrl+Z undoes it.

**Rendering.** A box that sends a voice needs an audio VAE connected to Timeline; without one, the render stops with "box 1 sends Tom's voice, so connect an audio VAE to Timeline". A missing file stops it too, naming the box, the slot and the file. Voice clips never play in the full video. Story Export and Import carry the clips' file references, and the files stay in `input/h3_audio`. An older H3 install doesn't know voice clips: a box that mentions one stops with "not connected", and an older Studio drops the clips at its first edit.

## Remembering the cast

On a Timeline with a bible, a box's **Visual memory** in the Box tab can be **Cast**. A Cast box shows the video model earlier moments of what its pictures don't show: its characters as they look now, and its place.

At a cut, every enabled Visual memory mode also supplies the full preceding video's original latent, even when Cast pictures are present. It preserves visual context for object appearance, room layout and movement while the next shot starts from a fresh target. **New scene** keeps that visual history and lets the new prompt define the new setting, time and appearance. **Off** disables it.

**Pins.** To choose the moment Cast remembers, play a box's take in the Studio, pause where a character or place shows well, and press **Pin for…**, beside **Open in new tab** and **Download**. It lists the box's scheduled characters, then its place. Choose one, and the note under the player says, for example, "Pinned box 2 at 3.5 s for Maya." **Pin for…** shows only on a box's current take. On the Cast page, each character and place lists its **Pinned moments**, newest first, with **Remove**; a pin whose box is gone, or that is past its box's end, reads "has no effect". A pin is a Cast edit, so Ctrl+Z undoes it, and deleting a box removes its pins.

**What a Cast box remembers**, in this order, up to 3 moments less the box's RefMods videos:

1. Each scheduled character that no picture in the box shows as it looks now. It's the character's latest pin since its current look began; without one, the middle of its last shot in the first box of that look that schedules it, or 5 frames before that box's end. With neither a pin nor such a box, the character has nothing to remember yet.
2. The place, unless the box continues the box before at the same place. It's the place's latest pin in its current look; without one, 5 frames before the end of the latest earlier box set there.

At a cut, the full preceding video comes first and replaces automatic moments from that same video. It is independent of Cast's picture filters and moment budget. Explicit Selected moments remain additional references.

A moment is remembered once, and only moments from an entity's current look count, so a look change drops the older ones. A box without a schedule, or on a Timeline without a bible, remembers what Same scene does. The Box tab lists the moments, such as "Box 1 · 2.0 s · showing Tom", and the prompt says what each shows: "<Video 1> is an earlier moment of this film showing <Subject 1>."

**Rendering again.** A box needs rendering again when its moments change or when a box it remembers is rendered again. So a new or removed pin, or a retake, marks only the boxes it touches. Render the boxes a Cast box remembers first; until then its render stops with a message that also offers setting Visual memory to Off.

**Write.** A box that Write writes with the bible moves from Same scene to Cast, and the Story's **Undo** moves it back. Story feedback on a box written from the bible does the same. Boxes on Off or Selected moments keep their choice, and the boxes Write plans start on Cast. Each box's request to the writer lists the earlier boxes, one line each: who and where, the box each look started at, how the box ended and what was said, for example `Box 1, The kitchen: e1 Maya, e2 Tom. Ended: e3. e1 sits. The cup is on the table. Said: "It's late."` A box this Write wrote gives its line from this Write, and any other box from its saved source. A Timeline without a bible writes as before.

## Cast edits after Write

A box that Write wrote from the bible keeps the writer's reply as its source. While the box's prompt is still what that source compiles to, every Cast edit compiles the whole box again: its definition lines, the sentences for the other entities in it, its voices and the style all take the new wording, and the shots, dialogue, sound and timing stay the writer's. An entity reads partially preserved in the box's retention line where its wording changed since Write, or where a look without a picture of its own is in force.

A box you edited by hand gets only the line-by-line update described above, so your edits stay. Its chips on the Box page start with "Edited by hand" and **Recompile from source**, which compiles the box again from its source and the bible and drops your edits to its prompt.

**Update prose with the writer.** A new wording can leave shot text that still describes the old look, such as a dry coat that is now soaked. After a Cast edit that changes an entity's wording in boxes with a prompt, and while a Story is connected, the Cast page offers **Update prose with the writer** with the boxes it sends, for example "Sends boxes 1 and 2". It sends only those boxes, with the entity and its wording before and after in each, and the writer patches only the text that the new wording contradicts. It runs like Story feedback: its progress is in the top bar, and either every patch lands or none does. The next change to the Timeline takes the offer away.

**Story feedback** on a box whose prompt is still what its source compiles to patches the source instead of the prompt, and the box is compiled again from it, so later Cast edits keep the change. A patch that would break the source, or change its shot times, subjects or looks, publishes nothing.

**Merge and Delete.** Merging an entity into another makes every source that names it name the other one instead, and a box still compiled from its source takes the other entity's wording. Deleting an entity drops the sources that name it; those boxes keep their prompts and get line-by-line updates from then on.

**Undo.** A Cast edit, Recompile from source included, is one step of ComfyUI's Undo, as below. A prose update or Story feedback is undone with the Story's **Undo**, which puts back the prompts and sources it changed, where you haven't changed them since.

## Undo

Each Cast change, Build bible included, is one step of ComfyUI's Undo (Ctrl+Z): it reverts the bible, the prompts and the links together, and the Studio stays open on the restored Timeline. Ctrl+Y, or Ctrl+Shift+Z, redoes the step. Both work while the Studio is open, except in a text field, where Ctrl+Z undoes your typing. A box that Undo brings back unlinked stays unlinked until you open the Studio again or switch it to the Cast or Box page.

## Preparing reusable images

The optional **Prepare references** section on the Cast page creates reviewable candidates for identities, scheduled appearances, locations and arbitrary objects. An extra can be a weapon, car or prop, and **Add object reference** adds missing extras alongside existing pictures. Generation switches start off and are independent. Approve each candidate before using it; composed location layouts are separately approved and remain distinct from accepted First guides. See [Qwen Story Studio](QWEN-STORY-STUDIO.md#optional-reusable-references) for controls, native settings and generation transfer.
