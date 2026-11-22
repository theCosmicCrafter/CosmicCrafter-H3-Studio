# MCP adapter implementation

**Status:** MCP implementation complete
**Current Phase:** Phase 15: durable renders and stories

## Phase Ledgers

- [MCP tools and skills](phases/2026-11-08-mcp-tools-skills.md)

## Recovery State

```json
{
  "version": 1,
  "revision": 135,
  "phase": "Phase 15: durable renders and stories",
  "active_features": [
    "MCP2"
  ],
  "focus_feature": "MCP2",
  "goal": "Create and merge the MCP PR, publish v0.20.0 and fast-forward development and installed ComfyUI H3 Continuity checkouts while preserving local work.",
  "done_when": "PR merged; release/tag verified at merged main; development and installed ComfyUI checkout HEADs fast-forwarded with local changes preserved.",
  "last_completed": "Recovered clean ce4cf5a implementation and user authorization for PR/merge/release/update. origin/main now includes v0.19.6/0.19.7 fixes.",
  "in_progress": "Merge origin/main in progress; sole CHANGELOG conflict resolved by retaining MCP release and both intervening releases. Preparing local-edit backups and fresh release gates.",
  "next": {
    "action": "Verify merged tree, commit/push release preparation and create/link PR.",
    "reason": "User authorized full integration and release; latest main must be retained."
  },
  "files": [
    {
      "path": "docs/roadmap-discipline/phases/2026-11-08-mcp-tools-skills.md",
      "state": "MCP0 and MCP1 passing; review fixes and client limits recorded"
    },
    {
      "path": "docs/superpowers/plans/2026-11-08-mcp-tools-skills.md",
      "state": "All eight tasks and final review/fix gate checked"
    },
    {
      "path": "docs/superpowers/specs/2026-11-08-mcp-tools-skills-design.md",
      "state": "Approved implemented design"
    },
    {
      "path": "docs/MCP.md",
      "state": "Complete tool/action and client compatibility reference"
    },
    {
      "path": "guide/automation/mcp.md",
      "state": "Published installation and troubleshooting instructions"
    }
  ],
  "repository": {
    "branch": "feat/mcp-adapter",
    "head": "ce4cf5a7f46e",
    "dirty": [
      "CHANGELOG.md",
      "h3_continuity/generations.py",
      "h3_continuity/timeline.py",
      "tests/README.md",
      "tests/browser/saved_story_attachment.py",
      "tests/js/continuity_keys.test.mjs",
      "tests/js/durable_stories.test.mjs",
      "tests/js/emit_shot_split.mjs",
      "tests/js/history.test.mjs",
      "tests/js/saved_story_project.test.mjs",
      "tests/js/saved_story_recovery.test.mjs",
      "tests/js/shot_split.test.mjs",
      "tests/js/story_library_groups.test.mjs",
      "tests/js/take_marks.test.mjs",
      "tests/test_preview_targets.py",
      "tests/test_story_checkpoints.py",
      "web/h3c_audio_lanes.mjs",
      "web/h3c_bridges.mjs",
      "web/h3c_cast.mjs",
      "web/h3c_dialogue.mjs",
      "web/h3c_frame_images.mjs",
      "web/h3c_generation_archive.mjs",
      "web/h3c_history.mjs",
      "web/h3c_mentions.mjs",
      "web/h3c_pictures.mjs",
      "web/h3c_project.mjs",
      "web/h3c_reference_preparation.mjs",
      "web/h3c_reference_replacements.mjs",
      "web/h3c_reference_sources.mjs",
      "web/h3c_shot_preview.mjs",
      "web/h3c_shot_split.mjs",
      "web/h3c_story.js",
      "web/h3c_story_library.mjs",
      "web/h3c_story_model.mjs",
      "web/h3c_studio.mjs",
      "web/h3c_takes.mjs",
      "web/h3c_timed_text.mjs",
      "web/h3c_timeline.js",
      "web/h3c_timeline_editor.mjs",
      "web/h3c_timeline_face.mjs",
      "web/h3c_timeline_images.mjs",
      "web/h3c_timeline_model.mjs",
      "web/h3c_voices.mjs"
    ],
    "dirty_hash": "ec77df0332ee74dacb32fa1c9b933a510abb6661bb201a33c16d6d39680f9cb0"
  },
  "verification": {
    "required": "Fresh host/adapter/docs checks; merged GitHub PR; v0.20.0 tag/release at merged main; development and ComfyUI checkout ancestry/status and local-edit preservation",
    "last_run": "Task4 red5 missing-server failures; red1 invalid catalog regression; green20 adapter tests using SDK in-memory and real stdio transport.",
    "status": "not_run",
    "detail": "New release scope; implementation prior67 adapter/229JS/393Python evidence remains, merged tree gates pending."
  },
  "blockers": [],
  "reload": [
    "docs/roadmap-discipline/features.md",
    "docs/roadmap-discipline/phases/2026-11-08-mcp-tools-skills.md",
    "docs/superpowers/specs/2026-11-08-mcp-tools-skills-design.md",
    "docs/superpowers/plans/2026-11-08-mcp-tools-skills.md",
    "docs/research/2026-11-08-mcp-capability-audit.md"
  ]
}
```
