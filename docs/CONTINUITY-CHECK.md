# The continuity check

After rendering, the Story's Vision model can check each rendered box against the [Story bible](STORY-BIBLE.md),
its pictures and the box before, and every check measures how far the box's colours drifted. The check only reads
the renders. Nothing renders again unless you press **Retake**.

## Check and Check all

In the Studio, the Box page of a rendered box shows **Continuity check** between the box's chips and its tabs, on
every tab. **Check** checks that box, even when it has a current result. **Check all**, with the Story's actions on
the Story node and in the Studio's top bar, checks every rendered box without a current result, in Timeline order,
with one load of the model. Both need a linked H3 Story. Their progress shows in the Story panel, and **Cancel** stops
the check and keeps the boxes it finished.

The Vision model is the Story's `vision_model`, at `vision_base_url`, or at `base_url` when that is empty, with the
Story's `thinking`. For each box it gets:

- frames of the render: the middle of each shot, from the box's source, after the frames the box replays from the box
  before, then its last frame. More than 5 shots give 5, evenly chosen. A box whose source has no shots, such as one
  Write didn't write from the bible, gives 3 evenly spaced frames. Each frame is labelled with its shot and its time
  in the box;
- the pictures of the box's scheduled characters, props and place, as the look in force at the box has them, and the
  bible's wording for each at that box;
- the join and its note and, unless the box starts a new scene, the box before's last frame and how it ended.

It reports only differences a viewer would notice: a character, prop or place that doesn't match its pictures or its
wording, or a join that doesn't match the box before. Camera moves, framing, motion, blur and artefacts aren't
reported.

## Reading the result

The first line says where the box stands: "Not checked yet.", "Checked at 10:42 with vision-8b.", or "The last check
was of an earlier render." Below it, the problems are grouped under the box's characters and props by name, then
**Place** and **Join**, with the shot where it shows when the model names one, such as "Her hood is down (shot 2)."
"No problems found." means the model found none. "The check couldn't read the Vision model's answer." means its
reply didn't fit; press Check to ask again.

**Retake** shows when the check found problems, drift, or an answer it couldn't read. It is the box's **Render box N
· new seed**: it gives the box a new seed and renders that box alone, and it is off when that button is. Boxes that
continue from it keep their renders, and the old render moves to the sequence folder's `takes/`. The Box tab's Takes
section can play the old render and put it back (see [Takes](TIMELINE-TAKES.md)).

**Drift** compares the box's colour with its scene's first box, the nearest box at or before it that cuts to a new
scene, or box 1. The colour is the mean in CIELAB of the frames the check looks at. A shift of 8 or more on the a\*b\*
colour plane names its larger direction: warmer or cooler, redder or greener. A change of 10 or more in L\* reads as a
percentage of the first box's lightness. Together they read like "Drift: warmer and 12% darker than box 1." Below
both steps there is no drift line, and the scene's first box has none.

## When a result is current

Results are saved in `checks.json` in the Timeline's sequence folder, `output/h3_sequences/<name>`, one per box,
with the render each was made for. Rendering the box again, Retake included, makes its result stale: the Box page says
"The last check was of an earlier render." and Check all checks the box again. A Timeline nobody checks has no
`checks.json`, and the check writes no other file. Deleting `checks.json` forgets every result.

## Without a Vision model

Without a `vision_model`, Check and Check all measure drift only, and the Box page says "Checked at 10:42: drift
only, because the Story has no Vision model." Once the Story has a Vision model, Check all checks those boxes again.

## The queue and the GPU

A render that is running or waiting could replace the boxes being checked, and would share the GPU with the Vision
model. So the check starts only when ComfyUI's queue is empty, and otherwise says "ComfyUI is rendering or has
prompts waiting. Check when its queue is empty." It doesn't start while a Write or another check runs either, and
while it runs, Write says "A continuity check is running. Cancel it or wait."

With `free_vram` on and the Vision model on this PC, the check takes a turn in ComfyUI's queue as Write does:
ComfyUI frees its models, and prompts queued meanwhile wait for the turn to end. After the last box the Story unloads
the Vision model once, and also after Cancel. The end message says what the unload did, for example "Checked 3
boxes: 1 with problems, 1 drifted. LM Studio unloaded the model."
