# Takes

Each new render of a box moves the one before it into the sequence folder's `takes/`, and a new render of a bridge
does the same for the bridge. The Studio's Box tab lists those takes: it plays them beside the take in use, puts one
back in place without rendering, renders several at once and deletes the ones you don't need. A Timeline whose takes
you never open renders exactly as before.

## The Takes section

In the Studio (**Open Studio** on the Timeline node), select a box and open the Box tab. A **Takes** section ends the
tab when the box has a take in use or saved takes, and a bridge before the box has its own under the bridge's panel,
**Takes of the bridge before box N**. The first line is the take in use, such as "In use: rendered 10-06 14:03 · seed
1234". Then come the other takes, newest first, each with when it was rendered, its seed, whether it can be used, and
**Play**, **Use** and **Delete**.

A take can be used when it fits the box as it is now and both boxes beside it, so that using it never makes a
neighbour render again. Otherwise its row says why, from the first rule it fails:

| Line | Means |
| --- | --- |
| Can be used | Its seed on the box makes the box current, and it joins the boxes on both sides. |
| Can't be used: its files are missing | Its video or latents are gone from its folder. |
| Can't be used: seed not recorded | It was saved before takes recorded their seed. It can still be played and deleted. |
| Can't be used: it was rendered as box 4 | It was made for another place: boxes were added or removed before it. |
| Can't be used: the box changed after this take | Its prompt, length, cut, Studio pictures, RefMods, guides, clips, timed text or memory changed. |
| Can't be used: the node's settings changed | The node's width, height, context, audio or reference size changed since. |
| Can't be used: a box it remembers has another take | A box it remembers a frame of rendered again, or has another take in use. |
| Can't be used: the box before changed | It continued from the box before, which now ends with other frames. |
| Can't be used: the box after changed | The box after continued from this box, and this take ends with other frames. |

The joins compare the frames each box carried with the saved latents of the box beside it, within 0.001, the
tolerance H3 Save warns at. A take that carried no frames, as on a cut or box 1, has no join with the box before, and
a box after that is a cut or isn't rendered has none to check.

A bridge's take can be used when its files are there, its seed is recorded and, with its seed on the bridge, the
bridge is current. Otherwise its row gives the bridge's own reason, such as "box 3 rendered again" or "render box 3
first" (see [Bridges](TIMELINE-BRIDGES.md#when-a-bridge-needs-a-render)).

Like the Timeline's status, the list can't see the pictures connected to the node. A take rendered with other
connected pictures can be used, and the box's next run renders it again, as it would the take in use. Pictures chosen
in the Studio are part of the box, so a take made with other ones says "Can't be used: the box changed after this
take".

## Using a take

**Use** puts the take in place: the take in use moves to `takes/`, the chosen take's files move back into the
sequence folder, and the box gets the take's seed, as one Undo step. Nothing renders. While files move or are
deleted, the player lets go of its video and shows "Moving the take…", since Windows can't move a file that is open.
When a move fails, every file goes back where it was and the section says why.

Using a take can put other renders out of date. Use first lists them and asks:

- later rendered boxes that remember a frame of this box: "Boxes 7 and 9 remember a frame of box 3 and will need a
  new render.";
- a rendered bridge on either side of it: "The bridge before box 4 will need a new render."

**Use this take** goes ahead, and **Cancel** keeps the take in use. Those boxes and bridges then show as out of date
until they render. Each take keeps its files' stamps, so using the earlier take again makes them current again. Once
every box is done, the status rebuilds the [full video](TIMELINE-FULL-VIDEO.md) with the take, as after a render.

## Undo and older workflows

Whenever the Timeline names a seed that a saved take fits, that take is put back. Each time the Studio asks for the
Timeline's status, the server goes through the boxes that aren't current, in Timeline order, then the bridges, and
puts back the newest take that can be used and has the seed the Timeline names. So **Undo** (Ctrl+Z) after a Use or a
render brings the earlier take back with its seed, **Redo** (Ctrl+Y) brings the newer one back, and the same goes for
the Story's **Undo** and for opening an older copy of the workflow. The head says what was put back, for example "Put
back box 3's take rendered 10-06 13:50."

Takes saved before takes recorded their seed are never put back this way, and can't be used. A status request without
`"follow": true`, such as an outside tool's, moves nothing.

Two browser tabs, or two Timeline nodes, open on the same sequence with different seeds for a box each put back their
own take when they ask for the status, so the take in use can go back and forth. Keep one Timeline per sequence open.

## Comparing takes

**Play** on a row shows that take in the Studio's player, with a badge such as "Box 3 · take rendered 10-06 13:50 ·
seed 999". **Switch** flips to the take in use at the same moment, playing or paused as it was, and back again, so two
takes can be compared shot by shot. Selecting another box plays that box's own take. **Pin for…** shows only on the
take in use (**Box take**).

## Making several takes

The number beside **Render box N · new seed** sets how many takes to render, from 1 to 10. With 3, the button reads
"Render box 2 · 3 takes" and queues three runs of that box, one after another, each with a new seed. The last one is in
use when they finish, the others are listed under Takes, and the number goes back to 1. **Retake** on the
[continuity check](CONTINUITY-CHECK.md) renders one take.

## Deleting takes

Each delete counts first and asks, with the count and size: "Delete 12 takes (1.4 GB)? This can't be undone."

- **Delete** on a row deletes that take.
- **Delete other takes** deletes every saved take of this box, or of this bridge, and keeps the take in use.
- **Delete unusable takes in this sequence** deletes every take that can't be used now, for any box or bridge. That
  includes takes without a seed, takes of boxes the Timeline no longer has, and folders whose latent can't be read.

A deleted take is gone for good: its folder under `takes/` is removed with its entry in the manifest. The deletes never
touch the take in use or anything outside `takes/`.

## While the sequence renders

While a run of this sequence is running or waiting in ComfyUI's queue, Use and the deletes are off, with "Wait until
this sequence's runs finish." as their tip, and nothing is put back. A run counts when its H3 Timeline or H3 Sequence
node has this sequence's name, or a linked name that could be it. Play still works. Right after an edit they are off
too, with "Wait for the Timeline's status to catch up with the last edit.", until the Studio has read the new status.

## Files

Takes live in the sequence folder, `output/h3_sequences/<name>/takes/`, one folder each, named for the files' stem and
when they moved there: `seg_0003_20261006-135000` or `bridge@<id>_20261006-135000`, with `-2`, `-3` and so on when two
move in the same second. The manifest lists them under `takes`, each with the box's `index` or the bridge's `bridge`
id, when it moved (`archived`) and its `folder`. A take's latent file keeps its own saved entry, which is how the list
knows what each take is.

The saved records of boxes and bridges have a `seed` key. An older H3 install ignores it, and its Studio doesn't list
takes.
