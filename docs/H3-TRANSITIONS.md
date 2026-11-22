# Story transitions

Story planning and Fast writing receive the shared `TRANSITION_GUIDANCE` in `h3_continuity/story_prompts.py`. The LLM chooses seamless continuation, a scene-driven H3 transition or a hard cut according to the story, rhythm and user's Guide. Automatic planning can choose boundaries around the movement; writing into an existing Timeline respects its supplied boundaries and Cut flags.

A transition should grow out of action, light, environment, camera movement or appropriate animation language. Its mechanism is the LLM's choice. A fighter's back approaching and covering the lens, or light behind the action blooming as the camera turns toward it, are illustrations rather than presets. Animation may support expressive transitions; cinema may call for restraint. Context decides whether a transition helps at all.

Generate the cause, cover and reveal inside H3. Preserve momentum through the handoff, continuing from the actual ending and revealed state. Avoid a waiting pose before the effect, an exposed framing jump, or replaying the effect in newly generated frames. Native continuation supplies and trims its own context. No FFmpeg transition, added overlay or manual transition box is required. A separate short bridge is optional; keep a moving beat together when splitting it would create a bump. Deliberate quiet holds remain valid when the story calls for them. To turn a hard cut between two boxes that are already rendered into a generated move without rendering either again, add a bridge on the join; see [Bridges](TIMELINE-BRIDGES.md).

## Accepted feasibility example

On 2026-10-02 the user accepted the physical back cover in `output/h3_transition_fight_motivated_20261002/review.mp4`. The fight, camera approach, cover and reveal were generated jointly in a 107-frame box, followed by 68 new continuation frames at 24 fps. Native continuation carried and trimmed 39 context frames. The clip demonstrates smooth physical cover; changing the destination and refining the fight choreography were explicitly outside acceptance.

Earlier experiments exposed two separate problems: a held pose before the transition, and an isolated white burst that felt like an editing effect despite being generated inside H3. A separately generated physical bridge also jumped closer before concealment. These findings motivate planning the trigger within the outgoing movement and choosing box boundaries around it.

The shared instruction is covered by request-construction tests for automatic and fixed planning and for the Fast box writer. Fast retains its compact compiler-owned prompt contract; its bounded transition supplement is under 1,200 characters. These checks verify instruction routing, not a guarantee that every generated video will satisfy the direction. The accepted render and its detailed verification remain local; scratch media and workflows are ignored under `.tmp/`.
