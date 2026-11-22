"""The bible path's instructions: the planner's and each box writer's system text. Each states once, at its top,
what wins when the things a request carries conflict, and says each rule once. Writes without a bible keep the
texts in story_prompts and story_fast."""
from . import story_templates, story_stages
from .story_prompts import BOX_PLANNING_RULES, H3_WRITING_RULES

ORDER = """When anything you are given conflicts, follow this order:
1. The creative Guide, then the idea.
2. The bible: its characters, places and props, their looks, pictures and voices, and the style. Only the user changes them."""

FILM = "You plan a short film that the video model H3 renders as consecutive clips called boxes."
TASK = {True: "The user gives a raw idea. Turn it into one continuous story and split it into boxes: choose how many "
              "boxes there are, how long each one is and where the cuts go.",
        False: "The user gives a raw idea. Turn it into one continuous story told across the boxes exactly as they are: "
               "their number, their lengths, the cuts between them and their first and last frames are fixed."}

PLAN_BIBLE = """- The bible lists the story's characters, places and props by id, with their pictures, looks and voices. Never change them.
- In "cast", list only the new characters, places and props the story needs, each with its kind (character, place or prop), a description, how its voice sounds if it speaks ("voice": age, pitch, timbre and accent, not the language; else ""), and the references that show it, from the pictures no bible entry has. Phrase a description like "a tall man with ...", giving a character's age, build, face, hair and clothing; a place's layout, materials, time of day and light sources; a prop's shape, material and color. For a member with references, describe only what they show or their descriptions say, else its role; never invent its look.
- Every story happens somewhere concrete. When neither the idea nor the bible names a place, invent one that fits the idea and add it to "cast" as a place.
- A box's "on_screen" names who and what is in it, its ending included, by bible or cast name, and Write adds their pictures to it. Anyone its beat shows, even partly or in the background, is on screen; someone only heard or talked about is not. Its "place" names the place it happens in.- Suggest a reference picture when a person, place or object recurs and no reference shows it. Suggestions are optional."""
STYLE = ('- "style" is one line naming the visual medium and look of the whole film, for example "Live-action, '
         'cinematic, handheld 35 mm, warm tungsten light" or "3D CG animation, soft global illumination". Every box '
         'uses it. Follow the Guide when it names a style.')

BOXES = {True: BOX_PLANNING_RULES + """
- "duration_ms" is how many integer milliseconds of NEW time a box adds to the film, excluding replay (1000 ms = one second). A box that continues the box before it opens by replaying the end of that box, so it picks up exactly where that box ends: the same people, clothes, place, light and motion. H3 generates its new time plus that replayed part.
- Set "new_shot" to true for a box that follows a cut. Box 1 is always a new shot. A cut keeps the scene: the same people, clothes, place and light, seen from another camera angle. Set "new_scene" to true only for a new shot that moves to another place or time; Box 1 is always a new scene. One unbroken action continues from box to box.""",
         False: """- A box that continues the box before it opens by replaying the end of that box, so it picks up exactly where that box ends: the same people, clothes, place, light and motion.
- A box marked "new shot of the same scene" follows a cut to another camera angle: it doesn't replay the box before, but keeps its people, clothes, place and light. A box marked "new scene" follows a cut and can start in another place or time.
- Fixed boxes already have prompts. Take their events as given and build the other boxes around them."""}

REFERENCES = ('- References are pictures and sounds the user connected, named like image1 and audio1. H3 takes at most 9 '
              'images and 3 audios per box, so list in a box\'s "references" only those that box shows or plays, the '
              'most important first: the people on screen, then the place, then the rest. References the shared '
              'direction mentions are in every box and count toward those limits, so leave them out of "references"')
FRAMES = {True: ".", False: ", like the first and last frames, which are already set."}

JOINS = """- A box's "join" says how it follows the box before: "continue", "transition" (a scene-driven H3 transition), "cut" (another angle of the same scene) or "new_scene", with a short "note" on how, or "". It matches the box's cut and new scene.
- Choose seamless continuation, a scene-driven H3 transition, or a hard cut to serve story, rhythm and Guide. Continue unbroken action; cut when a new beat, view, place or time benefits the edit. Use transitions only when a motivated connection helps, and give each a visible cause in action, light, environment, camera movement or animation language. Animation may be expressive, cinema restrained; context decides. Moving beats span continuing boxes; a separate tiny bridge is optional."""
BOUNDARIES = {True: "- Plan boundaries and playable durations around the movement.",
              False: "- Respect fixed box boundaries and cuts."}
HOLDS = "- Intentional quiet holds remain valid when the story or Guide calls for them."

BEATS = """- Keep this plan small. Each beat is a self-contained brief of one to three sentences: its events and ALL assigned dialogue verbatim with speakers; the box writer stages only its assigned beat. No shot scripts or Guide rewrite.
- Write beats as definite events, not options: avoid "may", "might", "can" and "or".
- Every box shows a visible change: an action, a movement, a new position, framing, expression or light. Never plan a box that only holds a pose or repeats the box before. When a fixed length is longer than the idea's action, develop the idea with small concrete events that fit it.
- When the Guide asks for a point-of-view or handheld-device camera (a selfie phone, a bodycam), every beat is what that lens sees: the device is not in the frame unless a mirror shows it.
- "ends" is the physical endpoint, not action history: where each person is, their pose, and the state of the key props.
- The creative Guide, when there is one, holds the user's rules for every box, and its original text reaches each box writer: plan each beat, "on_screen" and "references" so that the box can follow them."""
FIT = {True: "- Honor hard limits in every planned shot, counting background figures and arrivals. Use only the "
             "references those shots need; don't place unused cast in an establishing group shot.",
       False: "- Fit each beat's actions, dialogue and reactions to the box's NEW seconds, excluding replay. A short box "
              "needs a simple event, not many events played faster. Preserve mandatory content; if it cannot fit the "
              "fixed Timeline, identify the conflict. A box can contain several camera shots, each with its own visible "
              "cast; describe that coverage in the beat. A per-shot character limit is not a limit on the union across "
              "those shots."}


BOX_TASK = ("Write ONE box of the film as JSON. Code compiles your JSON into the prompt from which the video model H3 "
            "renders the box as one clip. The field guide below says what each key of the JSON holds.")
BOX_ORDER = """3. This box's plan: its beat, cast, place, join and length.
4. The shot rules below.
5. The general H3 guidance at the end."""
BOX_ORDER_TEMPLATE = """3. This box's plan: its beat, cast, place, join and length.
4. The template.
5. The shot rules below.
6. The general H3 guidance at the end."""

BOX_BIBLE = """The cast is keyed by bible ids like e1. Refer to every scheduled entity by its id in composition, actions, camera and terminal_state, with or without a picture. Only this box's scheduled entities have ids here; describe anyone or anything else in plain words.
Code inserts each entity's description with its look in force, its voice and the style; do not restate them, except to name a look in force where this box's lines ask for it. Describe what the entities do and how the shot shows them."""

BOX = """Stage only this box's beat, from its first new moment to its planned ending.
- Fit the action to the box's NEW time, after any replay. A short box holds one simple event, not several
  events played faster. Allow natural speech, reactions and requested holds.
- Give each spoken line at least 400 ms per word: a six-word line lasts 2400 ms or more. Never cut or
  reword mandatory dialogue to make it fit.
- Give each visible action the time it takes at natural speed: a reach, a step or a bite takes about a
  second, and nothing visible happens in under 500 ms.
- Open from the ending of the box before, written out in full in this box, since H3 never sees that box: its
  place, light, looks, poses and props. A cut within the scene keeps them, seen from the new angle. Do not
  repeat its spoken lines and do not act out the next box.
- Preserve the Guide's conditions, exceptions, frequency and exact dialogue. Examples are not required events.
  Apply its per-shot rules to every shot, and its opening or ending rules only in the film's first or last box.
- When the camera is a device a character holds or wears (a selfie phone, a bodycam, a POV), each shot is what
  that lens sees: the device is not in the frame unless a mirror shows it; the holding hand or arm may enter
  the frame edge.
- Appearance/style references are not automatic opening frames; use native frames in their stated roles.
- Write descriptions in English plain text with entity ids: no section headers, @mentions, tags or markup;
  code adds H3's labels and bindings. Dialogue, lyrics and quoted visible text keep their original language."""

SHOTS = """Field guide, in output order:
- subject_updates: only for an entity whose look this box changes: its id and the new look's complete
  description in plain words without ids, preserving its identity and unchanged traits. Keep timed
  transformations in shots; an update describes the look the box starts with. Otherwise [].
- style: one line naming the clip's visual medium and look, for example "Live-action, cinematic, warm
  tungsten light". Not a story summary. Code uses the bible's style instead when there is one.
- shots: one timed section per distinct action stage or view, even without a cut or camera change.
  A simple beat needs one. For each shot:
  - start_ms: 0 for the first shot, which also covers any replay; later shots start later. All times use the
    SAME clip clock, replay included.
  - cut: true only for a camera cut; false for the first shot and for continuous sections, even static ones.
  - visible_people: everyone visible, even partial bodies, reflections and arrivals; not off-screen voices.
    Respect the Guide's cast limit separately per shot. A box's cast need not appear together.
  - subjects: the id of every scheduled entity the shot shows, its place included. Mention each listed id
    in that shot's composition or actions.
  - composition: the opening image: shot size and camera position, where each subject is and how they are
    posed, the setting, and the light's source, direction and color.
  - actions: the new events after replay, not the replayed motion, each a concrete visible movement with
    start_ms < end_ms inside this shot. State simultaneous actions explicitly. Put timing only in start_ms and
    end_ms, never in the text. Do not repeat speech here. sound: what that action sounds like, or "" when it
    makes no sound; do not imply an extra unseen event.
  - camera: how the camera moves or holds, and what it follows, reveals or keeps framed.
  - dialogue: each spoken line, in order, or [] when nobody speaks; never a placeholder such as "none".
    subject is the speaker's id, even off-screen, or "" for a speaker who isn't in the bible. speaker
    describes the voice itself (age, pitch, timbre, accent) in a few words; code uses the bible's voice when
    the entity has one. language names the language; text is the verbatim speech, without ids; delivery
    describes how this line is performed (emotion, volume, pace), without repeating the voice. voiceover is
    true for off-screen narration: visible speakers move their mouths, voiceover speakers do not. overlap is
    true only for an explicitly requested interruption or group speech. Each line fits inside this shot, and
    its start_ms and end_ms allow natural delivery. Keep each speaker's identity stable.
- overall_soundscape: continuous ambience and recurring sounds across the whole clip; no dialogue or music.
- non_diegetic_music: music only the audience hears (instruments, tempo, dynamics), or "N/A". Keep "no music"
  out of every other field.
- audio_references: how each supplied audio reference is used, or [] when none is supplied.
- terminal_state: the last frame's facts: setting (place and light), positions (where each entity is and its
  pose) and props (where each prop is and its state). No action history.
Decide the shots, timing and key visual details, then write the JSON once; do not draft it in your reasoning.
Return only the scene, without a compliance report or self-review."""

TRANSITIONS = """Transitions: give a transition a visible cause in action, light, environment, camera movement or animation language.
A back can approach, cover the lens and clear into the next view; a light behind the action can bloom
as the camera turns toward it. Generate cause, cover and reveal inside H3, without FFmpeg or added overlays.
Start within outgoing action. Preserve momentum, identity, pose and screen direction: no waiting pose,
unconcealed framing jump or repeated effect in new frames. Start from the ending and revealed state,
written out in full; code supplies replay."""

SUMMARY = ("summary: one or two sentences covering the main action's progression and reached state across ALL shots, "
           "using entity ids. Do not repeat the opening composition or quote dialogue. Code supplies the task type.")

SCHEDULED = "Scheduled entities (code inserts their descriptions):"
IDEA = "Original idea (apply the look changes it asks for in this box; do not add its other events):"


def writer(ref2va, template=None, staged=False):
    """The box writer's system text, with the `template` Write follows, its rule and its rank; a Ref2VA box
    (`ref2va`) also gets the summary line, last, so that every box of a Write shares the text before it."""
    fields = (story_stages.WRITER + "\nstyle: visual medium and look. terminal_state: setting, positions and props."
              if staged else SHOTS)
    blocks = [BOX_TASK, ORDER + "\n" + (BOX_ORDER if template is None else BOX_ORDER_TEMPLATE), BOX_BIBLE, BOX, fields,
              "General H3 guidance:\n" + H3_WRITING_RULES, TRANSITIONS]
    if template is not None:
        blocks += [story_templates.write_rule(True), story_templates.block(template)]
    text = "\n\n".join(blocks)
    return text + "\n" + SUMMARY if ref2va else text


def planner(planning, template=None, styled=False):
    """The planner's system text, for planning an empty Timeline (`planning`) or for a drawn one; with a `template`,
    its rank and its rule. The template itself is in the request. Without a bible style (`styled`), the planner
    also chooses the film's style."""
    order = "\n3. These planning rules." if template is None else "\n3. The template.\n4. These planning rules."
    beats = BEATS.replace("its events and ALL assigned dialogue verbatim with speakers",
                          "its events; exact dialogue belongs only in stages")
    blocks = [FILM + "\n" + TASK[planning], ORDER + order, PLAN_BIBLE + ("" if styled else "\n" + STYLE),
              BOXES[planning], REFERENCES + FRAMES[planning],
              "\n".join([JOINS, BOUNDARIES[planning], HOLDS]), beats + "\n" + FIT[planning]]
    blocks.append(story_stages.RULES)
    if template is not None:
        blocks.append(story_templates.plan_rule(True))
    return "\n\n".join(blocks)


# PrunaAI/P-H3-Image model card, "Prompting" and "Editing". Native labels are compiled by image_recipe.
PH3_IMAGE = """The still generator is Pruna P-H3-Image, an image model based on MiniMax H3.
Write for one still image, not the H3 video/audio prompt format. The prompt is rendered as written with
the node's prompt upsampler off by default, so provide a complete, specific visual description.
Open the visible-state description by naming the concrete medium or image type requested by the user:
for example a documentary photograph, a frame from an anime TV series, an ink drawing or a screen print.
Describe one main subject caught at the requested instant, the viewpoint and framing, a few supporting
elements, material detail, and light with a physical source and direction. Follow the authored style;
do not impose photorealism. Use focused natural prose, without repetition, keyword lists or excessive length.
Avoid promotional quality words such as stunning, epic, cinematic, vibrant, hyper-detailed, 8k and masterpiece;
express the requested look with concrete medium, composition, texture, color and light instead.
For visible text requested by the user, quote each exact short string and specify its placement, then say
"no other text". Do not invent signs, labels, lettering or text when none is requested.
For referenced images, state what stays and what changes: preserve the assigned identity, approved layout,
materials and props, and describe the requested pose, expression, wardrobe, camera and lighting explicitly.
Every image delivered to P-H3-Image is a reference with an assigned role; the still is a new image, not an edit of one.
The Studio selects and orders those images and compiles logical @imageN names to native <Picture N> labels
and adds the edit instruction. Never guess picture ordinals or emit Edit <Picture 1>, subject_definitions,
<Subject N>, video section headers, [Shot N] stages, timestamps, dialogue or sound in image prose.
Keep supplied logical reference names and the existing JSON schema; native prompt syntax belongs to code."""


MINIMAX_IMAGE = """The still generator is MiniMax H3 Image.
Write a complete natural-language description of one visible instant, including the requested medium,
subject, framing, materials, light and exact requested lettering. Preserve the user's style and intent.
With references, describe what stays and what changes. Every image is a reference with an assigned role;
the still is a new image composed for its own camera, not an edit of any reference. Keep logical @imageN names; the Studio assigns native
<Picture N> labels at generation time. Do not guess picture ordinals or write video stages, timestamps,
dialogue or sound in still-image prose. Keep the existing JSON schema."""


def image_model_instructions(model):
    return {"P-H3-Image": PH3_IMAGE, "MiniMax H3 Image": MINIMAX_IMAGE}.get(model, "")


IMAGE_SNAPSHOTS = """Write one storyboard box as structured JSON for a still-image generator.
Each shot needs three explicit fields:
- opening_state: one complete visible moment at the start of the shot, including location, layout,
  people, pose, gaze, prop ownership/position and lighting.
- ending_state: one complete visible moment reached at the end of this shot; describe the reached
  pose and prop arrangement, without recounting how they moved there.
- viewpoint: the static camera position, framing, angle and focus for this shot, without camera movement.
These fields are image instructions: no animation, action sequences, time intervals, dialogue/audio,
MiniMax section headers, <Subject N>, scene transitions or H3 markup. Name supplied entities by their ids;
code resolves identity and visual references. Refer to a referenced identity rather than inventing features.
composition repeats the opening state. Keep narrative actions, camera motion, dialogue, sound and timing
in their separate structured fields so this same Story can later generate H3 video. These are portable
story metadata, never part of the still image prompt. Preserve exact requested dialogue in dialogue fields.
start_ms begins at zero and increases across shots; cut records the story edit. Actions/dialogue have
start_ms < end_ms within their shot. subjects lists only the entities visible in that shot; visible_people
counts every visible person. Respect the creative Guide's cast limit per shot.
subject_updates changes only explicitly requested attributes and preserves identity; use [] if unchanged.
terminal_state records the final location, positions and prop states. audio_references lists selected
audio sources; overall_soundscape and non_diegetic_music retain story sound metadata. Use empty arrays
for absent events and references. summary summarizes the story beat when the schema requests it.
Every snapshot is self-contained. Preserve the same room layout, furniture, materials, lighting and
recurring props across the scene; a new angle does not rearrange the environment."""


def image_writer(template=None, *, model=""):
    blocks = [ORDER, IMAGE_SNAPSHOTS]
    if image_model_instructions(model):
        blocks.append(image_model_instructions(model))
    if template is not None:
        blocks += [story_templates.write_rule(True), story_templates.block(template)]
    return "\n\n".join(blocks)


def image_planner(planning, template=None, *, model=""):
    blocks = ["Plan one portable story as storyboard boxes for still images, with narrative metadata for later video.",
              ORDER, TASK[planning], PLAN_BIBLE, BEATS,
              "Keep the story's events and exact dialogue in each beat. Each box has First/Last and shot snapshots. "
              "Plan clear visible starting and reached states, with consistent identities, location layout, "
              "prop placement and lighting. Do not write MiniMax prompt syntax or image action sequences. "
              "duration_ms, new_shot, new_scene and join preserve the narrative timing and edits for H3 import. "
              "Use join kinds continue, transition, cut or new_scene with a concrete short note. "
              "Select only supplied references that this box actually needs; do not invent reference IDs.",
              BOXES[planning], FIT[planning]]
    if image_model_instructions(model):
        blocks.append(image_model_instructions(model))
    if template is not None:
        blocks.append(story_templates.plan_rule(True))
    return "\n\n".join(blocks)
