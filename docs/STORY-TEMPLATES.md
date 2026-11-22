# Story templates

A template is a video you want this one to resemble, written as text: its sequence, its style and its rules. Pick one
on the Studio's Story page, and Write shapes the plan after it and stages every box in its style. Your idea still says
what the video is about: the template's own characters, names, places and words are only examples.

## Picking a template

In the Studio (**Open Studio** on the Timeline node), the Story page has a **Template** row after **Idea**. Its list
has **None**, then your templates grouped by subfolder, then **Examples**. Under it, the row shows the template's
description and what it loads, for example "SKILL.md and 2 references, 18,400 characters". It also shows the
references it skipped, a note when its front matter couldn't be read, and a problem when Write would refuse it. The
last line names your template folder, with **Refresh** for files you add while the page is open. The list loads each
time the Story page opens.

The choice is the Story node's `template` setting. It's hidden on the node and saved with the workflow, and **Export
story** keeps it too, but not the template's files.

## Your template folder

Your templates live in ComfyUI's user folder, in `h3c_templates`, for example `C:\…\ComfyUI\user\h3c_templates`. H3
creates the folder when the Story page first lists it. Add templates there:

- **A single file:** any `.md` file is a template. Its id is its path in the folder, such as `night.md` or
  `ads/night.md`.
- **A skill:** a folder holding a `SKILL.md`, in any letter case, is one template. Its id is the folder's path, such as
  `skills/recipe-video`, and its other files are references that `SKILL.md` can load. H3 doesn't look for templates
  inside a skill.

Subfolders group the list. H3 searches up to 8 levels down and skips files and folders whose names start with `.`. It
follows folder links, so a junction (`mklink /J`) or a symlink can bring in templates you keep elsewhere without
copying them. A folder reached twice is listed once.

## Front matter

A template can start with a front matter block that gives its name and description:

```
---
name: Trailer
description: A trailer for a longer story.
---
```

It is read as YAML, so JSON works too. Without it, the name is the file's name without `.md`, or the skill's folder
name. A block that can't be read leaves the same name and a note, and the text after it still loads. Write never sends
the front matter.

## A skill's references

A skill sends its `SKILL.md`, then each file it refers to in the order first mentioned, each after a line such as
`File references/sequence.md:`. These count as references:

- a markdown link's target, such as `[the sequence](references/sequence.md)`;
- a file name in backticks, such as `` `steps.md` ``;
- a `skill://<name>/<path>` address, which loads from the skill itself when `<name>` is its folder's name or its front
  matter's, and otherwise from the skill folder called `<name>` beside it.

Only `.md`, `.txt`, `.json`, `.yaml` and `.yml` files load, each once. Web links and `#` anchors aren't references. A
reference that is absolute, uses `..`, doesn't exist, isn't UTF-8 or has another extension is skipped, and the row
lists it after "Not loaded:". References inside the referenced files aren't followed.

## Limits

A template's whole text, with its references, can have up to 100,000 characters. It is read as UTF-8, with or without
a BOM. A template that is too long, or whose `SKILL.md` or single file isn't UTF-8, shows its problem in the row, and
Write refuses it.

## The examples

The list's **Examples** come with H3, from its `examples/templates` folder, so updating H3 updates them:

- **Music video**: performance and story intercut over the song's sections, cut on the beat.
- **Trailer**: a skill whose `SKILL.md` gives the style and rules and whose `references/sequence.md` gives the
  sequence, from the cold open to the final sting.

They are read-only. To change one, copy it into your template folder and edit the copy.

## What Write does with a template

Write reads the template when it starts, so an edit to the file reaches the next Write. Its notes name the template, for
example "Template: Trailer, 3,200 characters."

- **The planner** gets the template after the Guide. It spreads the template's sequence over the boxes in order,
  stretching or repeating it to fill them, and each box's beat starts with the part of the template that box plays.
  The template's own length is not the video's.
- **Each box writer**, for Write and **Rewrite box**, stages its box's part in the template's style: its look,
  camera, editing rhythm, transitions, typography and sound.
- **Story feedback** and **Update prose** keep revised boxes in the template's style.

When things conflict, the template ranks after everything you wrote. With a
[bible](STORY-BIBLE.md#writing-with-the-bible), the planner follows the Guide, then the idea, the bible, the template
and last its planning rules. A box writer follows the Guide, then the idea, the bible, the box's plan, the template,
the shot rules and last the general H3 guidance. Without a bible, the Guide and the idea win over the template.

A plan made with a template is planned again when the template's text changes. A Story without a template writes
exactly as before. The Vision check, Build bible, bridge prompts and Prepare don't use the template.

## A missing template

When the saved template isn't in the list any more, after a rename or a delete or in a Story from another PC, the row
shows it as "<id> (missing)" and says that Write needs it back in the folder, or another choice. Write, Rewrite box,
Story feedback and Update prose refuse it before sending anything, and the refusal names the template and the folder.
Put the file back, or choose another template or **None**, to write again.
