import {decorateIcon,icon,setIconLabel} from './h3c_icons.mjs';
import {TrackEditor} from './h3c_track_editor.mjs';
import {Pins, SwitchSection} from './h3c_switch_section.mjs?v=c253500f4908';
import * as tracks from './h3c_tracks.mjs';
// The H3 Timeline editor: a track of boxes, the selected box and the shared prompt.
// Plain DOM without ComfyUI imports; the host object connects it to the node.
import { MentionCard, MentionLayer } from './h3c_mentions.mjs?v=7d543c4a1ce8';
import { promptSections, promptShots, writePromptSections } from './h3c_prompt_sections.mjs?v=1f35473e5668';
import {PromptFormPanel} from './h3c_prompt_form.mjs?v=f43a53953089';
import * as model from './h3c_timeline_model.mjs?v=1dfc1612e462';
import * as videoLayers from './h3c_layers.mjs?v=1dfc1612e462';
import {audioSourceLocked} from './h3c_audio_windows.mjs?v=cdefbd77b246';
import { AudioLanes } from './h3c_audio_lanes.mjs?v=2c8422417f0a';
import { shotFrames, frameTargets, syncTargets, acceptedGuideFrames, endpointGuide, endpointReference, adoptEndpointGuides } from './h3c_shot_preview.mjs?v=1dfc1612e462';
import {FrameImages, targetLabel, imageDrop} from './h3c_frame_images.mjs?v=8328028de648';
import { splitBox, splitTiming } from './h3c_shot_split.mjs?v=d147aa313f65';
import { fillReferenceSwitches } from './h3c_reference_switches.mjs?v=e94b5b02e02b';
import { ReferenceReplacements } from './h3c_reference_replacements.mjs?v=00c628e63671';
import { fillPicturePicker, mentionedReferences, referenceChip } from './h3c_reference_pictures.mjs?v=8198307be3fa';
import { CastPage } from './h3c_cast.mjs?v=40c38aec04f0';
import { PicturesPanel, highestSlot } from './h3c_pictures.mjs?v=220c235a7923';
import { CheckPanel } from './h3c_check.mjs?v=0ba848400498';
import { BridgePanel, bridgeLine } from './h3c_bridges.mjs?v=a8d5483a8299';
import { DialoguePanel } from './h3c_dialogue.mjs?v=0c9058202c42';
import { ChainSettings } from './h3c_chain_settings.mjs?v=9f2d4061a6d6';
import { exportedVideo } from './h3c_partial_video.mjs?v=201bf0f48645';
import { MAX_TAKES, TakesPanel, followNote, renderLabel } from './h3c_takes.mjs?v=15deab5acdd6';
import { drawsSame, replaceChanged, setText, showImages } from './h3c_dom.mjs?v=584a9bf55653';

const STYLE_ID = 'h3ct-style';
const PANEL_HEIGHT = 470;
const JOIN_LABELS = {continue: 'Continue', transition: 'Transition', cut: 'Cut', new_scene: 'New scene'};
// Untargeted guides need unique shot numbers; numbers from here on are free frame guides, never prompt shots.
const FREE_GUIDE = 1000;
// How long typing pauses before the whole Timeline redraws; drawing a long Timeline on every key lags the keyboard.
export const TYPING_PAUSE = 200;
const CSS = `
.h3ct-root { display: flex; flex-direction: column; gap: 6px; width: 100%; height: ${PANEL_HEIGHT}px; overflow-y: auto; box-sizing: border-box; padding: 4px 2px;
  color: var(--input-text, #ddd); font: 14px/1.45 system-ui, sans-serif; }
.h3ct-root * { box-sizing: border-box; }
.h3ct-head, .h3ct-panelhead, .h3ct-row, .h3ct-chips { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.h3ct-grow { flex: 1 1 auto; }
.h3ct-summary { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.h3ct-button { padding: 2px 8px; font: inherit; color: inherit; white-space: nowrap; cursor: pointer;
  background: var(--comfy-input-bg, #222); border: 1px solid var(--border-color, #444); border-radius: 4px; }
.h3ct-button:hover:not(:disabled) { filter: brightness(1.3); }
.h3ct-button:disabled { opacity: .45; cursor: default; }
.h3ct-primary { border-color: #5b8fe8; }
.h3ct-link { color: #8fbcff; white-space: nowrap; }
.h3ct-link[hidden] { display: none; }
.h3ct-lane { overflow-x: auto; flex-shrink: 0; background: #101218; border: 1px solid var(--border-color, #333); border-radius: 6px; }
.h3ct-lane > .h3ct-stills, .h3ct-lane > .h3ct-ruler, .h3ct-lane > .h3ct-track, .h3ct-lane > .h3ct-stack, .h3ct-lane > .h3ct-audio { width: calc(100% * var(--h3ct-zoom, 1)); }
.h3ct-stack { position: relative; padding: 6px 0; border-top: 1px solid #262a33; }
.h3ct-stack[hidden] { display: none; }
.h3ct-stack-title { position: absolute; left: 6px; top: 6px; font-size: 10px; letter-spacing: .04em; text-transform: uppercase;
  color: #aab1bd; pointer-events: none; }
.h3ct-stack-rows { display: flex; flex-direction: column; gap: 6px; min-width: 150px; }
.h3ct-stack-row { position: relative; border: 1px solid #465066; border-radius: 4px; background: #1a1f29; font-size: 11px; }
.h3ct-stack-row.main { min-height: 16px; padding: 1px 6px 3px; border-style: dashed; color: #aab1bd; white-space: nowrap; overflow: hidden; }
.h3ct-stack-row.main b { color: #e6e6e6; }
.h3ct-stack-row.layer { height: 50px; }
.h3ct-edge { top: 2px; width: 54px; height: 38px; }
.h3ct-edge.first { left: 2px; } .h3ct-edge.last { right: 2px; }
.h3ct-edge img, .h3ct-edge .h3ct-still-empty { height: 22px; }
.h3ct-stack-heading { position: absolute; left: 62px; top: 4px; white-space: nowrap; }
.h3ct-onscreen { position: absolute; bottom: 0; height: 4px; pointer-events: none; }
.h3ct-shot-tick { position: absolute; bottom: 0; width: 2px; height: 10px; margin-left: -1px; background: #66bc90; pointer-events: none; }
.h3ct-swap { position: absolute; top: 0; bottom: -6px; width: 12px; margin-left: -6px; cursor: ew-resize; touch-action: none; z-index: 2; }
.h3ct-swap::before { content: ''; position: absolute; left: 5px; top: 0; bottom: 6px; width: 2px; background: #e6e6e6aa; }
.h3ct-swap::after { content: ''; position: absolute; left: 1px; bottom: 0; width: 9px; height: 9px; transform: rotate(45deg);
  background: #e6e6e6; border: 1px solid #101218; }
.h3ct-swap-chip { position: absolute; left: 10px; top: 22px; padding: 0 4px; border: 1px solid #6b7488; border-radius: 3px;
  background: #101218; font-size: 10px; white-space: nowrap; }
.h3ct-stack-add { display: flex; align-items: center; gap: 8px; font-size: 11px; color: #aab1bd; white-space: nowrap; }
.h3ct-stack-row { cursor: pointer; }
.h3ct-stack-row.picked { border-color: #8fbcff; box-shadow: 0 0 0 1px #8fbcff; }
.h3ct-video-picker { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 6px 0; }
.h3ct-video-picker[hidden] { display: none; }
.h3ct-video-pick { border-left-width: 4px; }
.h3ct-video-pick[aria-pressed="true"] { background: #2a3550; color: #fff; }
.h3ct-video-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 4px 8px; margin: 4px 0;
  border: 1px solid #343a46; border-left-width: 4px; border-radius: 4px; }
.h3ct-video-label { min-width: 54px; font-weight: 600; }
.h3ct-video-settings > [hidden] { display: none; }
.h3ct-switch .h3ct-field { flex-wrap: wrap; }
.h3ct-stills { position: relative; height: 74px; }
.h3ct-still { position: absolute; padding: 0; text-align: left; overflow: hidden; white-space: normal; }
.h3ct-still img, .h3ct-still-empty { width: 100%; height: 42px; object-fit: contain; display: block; background: #181c25; }
.h3ct-still .h3ct-still-empty { display: grid; place-items: center; font-size: 20px; color: #aab1bd; }
.h3ct-still-caption { display: flex; justify-content: space-between; gap: 3px; font-size: 11px; padding: 1px 4px; white-space: nowrap; }
.h3ct-still-caption > * { overflow: hidden; text-overflow: ellipsis; font-weight: normal; }
.h3ct-still-caption small { color: #aab1bd; font-size: inherit; }
.h3ct-still.interior img, .h3ct-still.interior .h3ct-still-empty { height: 32px; }
.h3ct-still.interior .h3ct-still-caption, .h3ct-targets.interior .h3ct-still-caption { display: grid; gap: 0; }
.h3ct-still.accepted { border-color: #66bc90; }
.h3ct-still.selected { outline: 2px solid #7aa2f7; outline-offset: -2px; }
.h3ct-still:hover, .h3ct-still:focus-visible { z-index: 2; }
.h3ct-guide-mark { position: absolute; bottom: 0; height: 10px; border-left: 2px solid #66bc90; }
.h3ct-plates { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr)); gap: 6px; }
.h3ct-plates > .h3ct-row { grid-column: 1 / -1; }
.h3ct-plate { border: 1px solid #465066; padding: 6px; min-width: 0; border-radius: 4px; }
.h3ct-plate-images { display: flex; gap: 6px; }
.h3ct-plate-images figure { margin: 0; flex: 1; min-width: 0; }
.h3ct-plate img { width: 100%; height: 112px; object-fit: contain; background: #171a21; }
.h3ct-advanced { padding: 6px; border: 1px solid #465066; border-radius: 4px; }
.h3ct-advanced .h3ct-row { margin-top: 6px; }
.h3ct-advanced .h3ct-field { min-width: 0; max-width: 100%; }
.h3ct-advanced .h3ct-select { min-width: 0; flex: 1; }
.h3ct-ruler { position: relative; height: 16px; overflow: hidden; background: #171a21; border-bottom: 1px solid #262a33; cursor: col-resize; touch-action: none; }
.h3ct-playhead { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: #ff6b6b; box-shadow: 0 0 3px #000a;
  pointer-events: none; z-index: 5; }
.h3ct-playhead[hidden] { display: none; }
.h3ct-tick { position: absolute; top: 0; height: 16px; padding-left: 3px; border-left: 1px solid #3a414d;
  font-size: 11px; line-height: 16px; color: #aab1bd; pointer-events: none; }
.h3ct-track { position: relative; height: 54px; cursor: crosshair; touch-action: none; user-select: none; }
.h3ct-audio { display: flex; flex-direction: column; gap: 4px; }
.h3ct-audio-lanes { position: relative; }
.h3ct-audio-lane { position: relative; height: 40px; overflow: hidden; background: #171e21; border-bottom: 1px solid #344548; }
.h3ct-audio-video { position: absolute; inset: 0 auto 0 0; border-right: 1px dashed #aaa; background: #283339; }
.h3ct-audio-clip { position: absolute; height: 36px; top: 2px; min-width: 4px; border: 1px solid #72b8ad;
  background: #205d54; border-radius: 3px; cursor: grab; touch-action: none; user-select: none; overflow: hidden; }
.h3ct-audio-clip.disabled { opacity: .4; }
.h3ct-audio-clip.box-bound { cursor:pointer; touch-action:pan-x pan-y; }
.h3ct-audio-gap { position:absolute; top:3px; height:34px; min-width:0; padding:2px 6px; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; color:#c2d4d1; background:transparent; border:1px dashed #526563; border-radius:4px; cursor:pointer; }
.h3ct-audio-gap:focus-visible { outline:2px solid #b7d2ff; outline-offset:-2px; }
.h3ct-audio-clip svg, .h3ct-audio-clip canvas { position: absolute; inset: 0; width: 100%; height: 100%; fill: #80d3c2; opacity: .65; pointer-events: none; }
.h3ct-audio-label { position: absolute; inset: 2px 9px auto; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
  font-size: 11px; text-shadow: 0 1px 3px #000; pointer-events: none; }
.h3ct-audio-handle { position: absolute; top: 0; bottom: 0; width: 8px; background: #72b8ad55; cursor: ew-resize; }
.h3ct-audio-handle.left { left: 0; } .h3ct-audio-handle.right { right: 0; }
.h3ct-audio-settings { padding: 3px; } .h3ct-audio-settings > * { margin-bottom: 4px; }
.h3ct-audio-settings audio { width: min(100%, 340px); height: 30px; }
.h3ct-box { position: absolute; top: 6px; bottom: 6px; overflow: hidden; cursor: pointer;
  background: #34405a; border: 1px solid #4a5877; border-radius: 4px; }
.h3ct-box:focus-visible { outline: 2px solid #7aa2f7; outline-offset: 2px; }
.h3ct-box.done { background: #25473a; border-color: #3f7a5d; }
.h3ct-box.next { background: #574820; border-color: #c49a3a; }
.h3ct-box.pending { background: #2c3342; border-color: #465066; }
.h3ct-box.outdated { background: #3a3a2a; border-color: #8a7a3a; border-style: dashed; }
.h3ct-box.cut { border-left: 3px solid #e6e6e6; }
.h3ct-box.new-scene { border-left: 3px double #f0c674; }
.h3ct-box.problem { border-color: #e0605a; box-shadow: inset 0 0 0 1px #e0605a; }
.h3ct-box.selected { z-index: 2; outline: 2px solid #7aa2f7; outline-offset: 1px; }
.h3ct-box img { position: absolute; top: 0; right: 0; height: 100%; max-width: 50%; object-fit: cover; opacity: .7;
  pointer-events: none; }
.h3ct-boxlabel { position: relative; display: block; padding: 3px 10px 0 6px; overflow: hidden; font-size: 11px;
  white-space: nowrap; text-overflow: ellipsis; text-shadow: 0 1px 2px #000; pointer-events: none; }
.h3ct-handle { position: absolute; top: 0; right: 0; bottom: 0; width: 8px; cursor: ew-resize; background: rgba(255,255,255,.1); }
.h3ct-stack-badge { display: inline-block; margin-left: 5px; padding: 0 4px; border: 1px solid #8fbcff; border-radius: 3px;
  background: #0009; font-size: 10px; line-height: 13px; }
.h3ct-stripes { position: absolute; left: 0; right: 0; bottom: 1px; z-index: 1; pointer-events: none; }
.h3ct-stripe { position: relative; height: 5px; margin-top: 1px; }
.h3ct-stripe > .on { position: absolute; top: 0; bottom: 0; }
.h3ct-still-caption small.under { color: #f0b45a; }
.h3ct-handle:hover { background: rgba(255,255,255,.3); }
.h3ct-bridge-mark { position: absolute; top: calc(50% - 7px); z-index: 3; width: 14px; height: 14px; margin-left: -7px; padding: 0;
  transform: rotate(45deg); cursor: pointer; background: #7aa2f7; border: 1px solid #c9d6f5; border-radius: 2px; }
.h3ct-bridge-mark.done { background: #66bc90; border-color: #b9e5cc; }
.h3ct-bridge-mark.next { background: #c49a3a; border-color: #f0d79a; }
.h3ct-bridge-mark.pending, .h3ct-bridge-mark.waiting { background: #2c3342; border: 1px dashed #aab1bd; }
.h3ct-bridge-mark.problem { background: #e0605a; border: 1px solid #ffb3ad; }
.h3ct-bridge-mark.review { background: #2c3342; border: 1px dashed #f0d79a; }
.h3ct-replace-region { position: absolute; top: 4px; bottom: 4px; z-index: 2; pointer-events: none; border-radius: 3px;
  border: 1px dashed rgba(122,162,247,.7);
  background: repeating-linear-gradient(135deg, rgba(122,162,247,.22) 0 4px, transparent 4px 8px); }
.h3ct-replace-region.plays { border: 1px solid #66bc90; background: rgba(102,188,144,.22); }
.h3ct-bridge-mark:focus-visible { outline: 2px solid #8fbcff; outline-offset: 2px; }
.h3ct-draft { position: absolute; top: 6px; bottom: 6px; padding: 3px 6px; font-size: 11px; pointer-events: none;
  background: rgba(122,162,247,.14); border: 1px dashed #7aa2f7; border-radius: 4px; }
.h3ct-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: #aab1bd; pointer-events: none; }
.h3ct-hint { margin: 0; font-size: 12px; color: #aab1bd; }
.h3ct-hint.problem, .h3ct-mode.problem { color: #ff8a80; }
.h3ct-panel { display: flex; flex-direction: column; gap: 6px; padding: 6px; background: rgba(0,0,0,.18);
  border: 1px solid var(--border-color, #333); border-radius: 6px; }
.h3ct-panel[hidden], .h3ct-field[hidden] { display: none; }
.h3ct-clip-actions > summary, .h3ct-settings-section > summary, .h3ct-source > summary { cursor: pointer; overflow-wrap: anywhere; }
.h3ct-clip-actions > summary:focus-visible, .h3ct-settings-section > summary:focus-visible,
.h3ct-source > summary:focus-visible { outline: 2px solid #8fbcff; outline-offset: 2px; }
.h3ct-panel-tabs { display: flex; gap: 4px; border-bottom: 1px solid #343a46; }
.h3ct-panel-tabs [aria-selected="true"] { background: #293e60; border-color: #729cdd; }
.h3ct-tabpanel { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.h3ct-tabpanel[hidden] { display: none; }
.h3ct-title { font-weight: 600; }
.h3ct-text { width: 100%; padding: 4px 6px; font: inherit; color: inherit; resize: vertical;
  background: var(--comfy-input-bg, #14161a); border: 1px solid var(--border-color, #333); border-radius: 4px; }
.h3ct-select, .h3ct-number, .h3ct-note { padding: 1px 4px; font: inherit; color: inherit;
  background: var(--comfy-input-bg, #14161a); border: 1px solid var(--border-color, #333); border-radius: 4px; max-width: 100%; }
.h3ct-number { width: 120px; }
.h3ct-note { width: 180px; }
.h3ct-field { display: flex; align-items: center; gap: 4px; }
.h3ct-wide { flex: 1 1 100%; flex-wrap: wrap; }
.h3ct-label { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #aab1bd; }
.h3ct-chip { padding: 0 7px; font-size: 11px; border-radius: 10px; }
.h3ct-mode { font-size: 12px; }
.h3ct-shared { display: flex; flex-direction: column; gap: 3px; }
.h3ct-prompt-tabs { display: flex; align-items: center; gap: 4px; }
.h3ct-prompt-tabs .h3ct-label { margin-right: auto; }
.h3ct-prompt-tabs [aria-pressed="true"] { background: #293e60; border-color: #729cdd; }
.h3ct-structure { display: flex; flex-direction: column; gap: 6px; }
.h3ct-structure[hidden], .h3ct-panel .h3cm-wrap[hidden] { display: none; }
.h3ct-structure > .h3sw-section { border-top: 0; }
.h3ct-structure > .h3sw-section > .h3sw-head { min-height: 30px; padding: 2px 0; font-size: 12px; color: #aab1bd; }
.h3ct-structure > .h3sw-section > .h3sw-body { padding-left: 0; }
.h3ct-section-tabs { display: flex; flex-wrap: wrap; gap: 4px; }
.h3ct-section-tab.empty > span:first-child { opacity: .6; }
.h3ct-tab-count { min-width: 16px; padding: 0 4px; border-radius: 8px; background: #ffffff14; font-size: 11px; line-height: 16px; text-align: center; }
.h3ct-tab-count:empty { display: none; }
.h3ct-count { margin-left: 8px; font-size: 11px; font-weight: 400; color: #aab1bd; }
.h3ct-section-fields { display: grid; gap: 8px; }
.h3ct-section.subject_definitions .h3ct-section-fields { grid-template-columns: repeat(auto-fit, minmax(min(230px, 100%), 1fr)); }
.h3ct-prompt-field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.h3ct-entry-label { font-size: 11px; font-weight: 600; color: #a9bcdb; }
.h3ct-entry-label.numbered { font-family: ui-monospace, monospace; }
.h3ct-prompt-field .h3ct-text { padding: 7px 8px; line-height: 1.55; }
.h3ct-prompt-field .h3cm-wrap { min-width: 0; }
.h3ct-button:focus-visible, .h3ct-section > summary:focus-visible { outline: 2px solid #8fbcff; outline-offset: 2px; }
.h3ct-previews { display: grid; gap: 8px; }
.h3ct-targets { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 6px; }
.h3ct-target { padding: 0; text-align: left; overflow: hidden; white-space: normal; }
.h3ct-target img, .h3ct-target .h3ct-still-empty { display: block; width: 100%; height: 54px; object-fit: contain; background: #181c25; }
.h3ct-target .h3ct-still-empty { display: grid; place-items: center; color: #aab1bd; font-size: 20px; }
.h3ct-target[aria-pressed="true"] { border-color: #7aa2f7; outline: 1px solid #7aa2f7; }
.h3ct-target.accepted { border-bottom: 3px solid #66bc90; }
.h3ct-targets.h3ct-filmstrip { display: flex; gap: 6px; overflow-x: auto; padding: 2px 2px 4px; scrollbar-width: thin; }
.h3ct-filmstrip .h3ct-target { flex: 0 0 96px; border-radius: 5px; }
.h3ct-filmstrip .h3ct-target img, .h3ct-filmstrip .h3ct-target .h3ct-still-empty { height: 54px; }
.h3ct-filmstrip .h3ct-target .h3ct-still-caption { padding: 2px 6px; }
.h3ct-filmstrip .h3ct-target.accepted { border-bottom-width: 1px; box-shadow: inset 0 -2px 0 #66bc90; }
.h3cx-studio .h3ct-target, .h3cx-studio .h3ct-image-thumbnail, .h3cx-studio .h3ct-still { padding: 0; }
.h3ct-frame-images { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; min-width: 0; }
.h3ct-image-hero { grid-template-columns: minmax(0, 1fr); }
.h3ct-frame-images .h3ct-label { text-transform: none; letter-spacing: normal; font-size: 12px; }
.h3ct-frame-images .h3ct-note { width: 100%; }
.h3ct-image-thumbnail { display: block; padding: 0; line-height: 0; overflow: hidden; }
.h3ct-image-thumbnail img { display: block; width: 96px; height: 54px; object-fit: contain; background: #101218; }
.h3ct-image-hero { display: grid; gap: 6px; }
.h3ct-image-hero .h3ct-image-thumbnail, .h3ct-candidate .h3ct-image-thumbnail { width: 100%; }
.h3ct-image-hero .h3ct-image-thumbnail { border-radius: 6px; }
.h3ct-image-hero .h3ct-image-thumbnail img { width: 100%; height: auto; aspect-ratio: 16 / 9; max-height: 240px; }
.h3ct-image-head { justify-content: space-between; }
.h3ct-image-head > strong { font-size: 13px; font-weight: 600; }
.h3ct-image-hero .h3ct-row { justify-content: space-between; }
.h3ct-guide-status { color: #66bc90; font-size: 12px; }
.h3ct-image-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; aspect-ratio: 16 / 9; max-height: 240px; margin: 0; padding: 16px;
  background: #14171d; color: #c9d1dd; border: 1px dashed #3a414d; border-radius: 6px; text-align: center; font-size: 13px; }
.h3ct-image-empty small { color: #8b93a1; font-size: 12px; max-width: 28ch; }
.h3ct-image-empty-icon { color: #6b7381; line-height: 0; }
.h3ct-image-empty-icon svg { width: 28px; height: 28px; }
.h3ct-drop-over.h3ct-image-hero .h3ct-image-empty, .h3ct-guide-add.h3ct-drop-over { border-color: #8fbcff; background: #8fbcff14; }
.h3ct-image-actions { gap: 6px; }
.h3ct-image-actions { flex-wrap: nowrap; }
.h3ct-image-actions > .h3ci-button:has(> .h3ci-sr) { flex: none; }
.h3ct-image-actions > .h3ci-button:has(> .h3ci-sr):not([hidden]) { margin-left: auto; }
.h3ct-image-actions > .h3ci-button:has(> .h3ci-sr):not([hidden]) ~ .h3ci-button { margin-left: 0; }
.h3cx-inspector .h3ct-saved-controls .h3ct-number { width: 80px; flex: 0 0 80px; }
.h3ct-prompt-summary { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border-radius: 6px; background: #ffffff06; border: 1px solid #2c313c; }
.h3ct-prompt-excerpt[hidden] { display: none; }
.h3ct-candidate-title { font-size: 12px; font-weight: 600; }
.h3ct-empty-state { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 24px 12px; margin-bottom: 8px; color: #8b93a1; font-size: 12px; text-align: center; }
.h3ct-empty-state[hidden] { display: none; }
.h3ct-empty-state svg { width: 28px; height: 28px; color: #6b7381; }
.h3ct-empty-state strong { color: #c9d1dd; font-size: 13px; font-weight: 600; }
.h3ct-empty-state span { max-width: 32ch; }
.h3ct-prompt-excerpt { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; margin: 0; color: #c6ccd7; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.h3ct-image-details { min-width: 0; border-top: 1px solid #343a46; }
.h3ct-image-details > summary { cursor: pointer; padding: 7px 0; font-size: 12px; }
.h3ct-image-details > summary:focus-visible { outline: 2px solid #8fbcff; }
.h3ct-image-details > .h3ct-field, .h3ct-image-details > .h3ct-row { margin: 6px 0; }
.h3ct-image-details p { white-space: pre-wrap; overflow-wrap: anywhere; }
/* Candidates sit directly under the image, so keep the image modest while there are some to choose from. */
.h3ct-has-candidates .h3ct-image-hero .h3ct-image-thumbnail img { max-height: 170px; }
.h3ct-candidate-picker { display: flex; flex-direction: column; gap: 6px; }
.h3ct-candidate-picker[hidden] { display: none; }
.h3ct-candidates { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }
.h3ct-candidate { display: flex; flex-direction: column; gap: 6px; min-width: 0; padding: 6px; border: 1px solid #465066; border-radius: 4px; }
.h3ct-candidate > strong { font-size: 12px; }
.h3ct-candidate .h3ct-image-thumbnail img { width: 100%; height: 84px; }
.h3ct-candidate > .h3ct-hint { overflow-wrap: anywhere; }
.h3ct-candidate > .h3ct-button { white-space: normal; }
.h3ct-candidate > details { margin-top: auto; }
@media(max-width:600px) { .h3ct-image-hero .h3ct-image-thumbnail img { max-height: 160px; } }
.h3ct-saved-guides { display: flex; flex-direction: column; gap: 6px; }
.h3ct-saved-still { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 8px; align-items: center; padding: 4px;
  border: 1px solid #2c313c; border-radius: 5px; }
.h3ct-saved-thumb { width: 64px; height: 64px; overflow: hidden; border-radius: 3px; background: #171a21; }
.h3ct-saved-thumb img { display: block; width: 100%; height: 100%; object-fit: cover; border-radius: 3px; }
.h3ct-saved-body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.h3ct-saved-body > strong { font-size: 12px; font-weight: 600; overflow-wrap: anywhere; }
.h3ct-saved-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.h3ct-saved-controls .h3ct-number { width: 72px; }
.h3ct-saved-still .h3ct-saved-controls > .h3ct-button:last-child { margin-left: auto; }
.h3ct-guide-add { display: flex; flex-direction: column; gap: 6px; padding: 10px; border: 1px dashed #3a414d; border-radius: 6px; }
.h3ct-guide-add .h3ct-saved-controls > .h3ct-hint { margin: 0; }
.h3ct-guide-add > strong { font-size: 12px; font-weight: 600; }
.h3ct-subject-grid, .h3ct-linked-images { display: grid; grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); gap: 6px; }
.h3ct-subject-card, .h3ct-linked-card { min-width: 0; padding: 5px; border: 1px solid #465066; border-radius: 5px; background: rgba(0,0,0,.12); }
.h3ct-subject-card img, .h3ct-linked-card img { display: block; width: 100%; height: 72px; object-fit: contain; background: #171a21; border-radius: 3px; }
.h3ct-subject-card strong, .h3ct-linked-card strong { display: block; margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.h3ct-subject-card p, .h3ct-linked-card span { display: block; margin: 2px 0 0; font-size: 11px; color: #aab1bd; overflow-wrap: anywhere; }
.h3ct-subject-card p { max-height: 4.2em; overflow: auto; line-height: 1.4; }
.h3ct-subject-card { display: grid; grid-template-columns: 78px minmax(0, 1fr); gap: 6px; align-items: start; }
.h3ct-subject-thumbs { display: grid; gap: 3px; }
.h3ct-subject-thumbs img { height: 44px; }
.h3ct-subject-card:has(.h3ct-subject-thumbs:empty) { grid-template-columns: minmax(0, 1fr); }
.h3ct-subject-thumbs:empty { display: none; }
.h3ct-refmod { margin-top: 6px; padding: 6px; border: 1px solid #465066; border-radius: 4px; }
.h3ct-refmod img { max-width: 120px; max-height: 90px; object-fit: contain; }
.h3ct-refmod-controls { display: grid; grid-template-columns: minmax(140px,1fr); gap: 6px; margin: 6px 0; }
.h3ct-refmod-controls > select { width: 100%; }
.h3ct-refmod-controls .h3ct-field { justify-content: space-between; }
.h3ct-drop-over { outline: 2px dashed #729cdd; outline-offset: -2px; }
.h3ct-section-heading { margin: 2px 0 0; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #aab1bd; }
`;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function button(label, title, onClick, className = '') {
  const node = el('button', `h3ct-button ${className}`.trim(), label);
  node.type = 'button';
  node.title = title;
  node.addEventListener('click', (event) => {
    event.preventDefault();
    onClick();
  });
  return node;
}

function option(value, label) {
  const node = el('option', null, label);
  node.value = value;
  return node;
}

function field(label, ...controls) {
  const node = el('label', 'h3ct-field');
  node.append(el('span', 'h3ct-label', label), ...controls);
  return node;
}

// Pickers are not wrapped in a <label>: a click on its text would press the first choice.
function group(label, ...controls) {
  const node = el('div', 'h3ct-field h3ct-wide');
  node.append(el('span', 'h3ct-label', label), ...controls);
  return node;
}

// A box Render skips: it has a saved take, current or outdated.
function hasTake(status) {
  return status?.status === 'done' || status?.status === 'outdated';
}

// The other videos of `box` without a take, by the status item of its clip (all of them before a status).
function videosToRender(box, status) {
  return (box.layers ?? []).filter((layer) => !hasTake(status?.videos?.find((video) => video.id === layer.id)));
}

const VIDEO_COLORS = ['143,188,255', '240,180,90', '199,146,234', '127,209,199'];

function percent(fraction) {
  return `${(fraction * 100).toFixed(3)}%`;
}

function injectStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = el('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.append(style);
}

export class TimelineEditor {
  // host: read() -> JSON text, write(text), context() -> carried frames, connected() -> {images, audios}
  // lists of {name, title, file, preview}, queue(count, box?, bridge?), viewUrl(file) -> URL, changed() after every edit.
  constructor(host) {
    injectStyle();
    this.host = host;
    this.card = new MentionCard();
    this.state = model.parseState(host.read());
    this.replacements = new ReferenceReplacements(this);
    this.selected = 0;
    this.selectedShot = 1;
    this.picked = null;
    this.instanceId = Math.random().toString(36).slice(2, 8);
    this.status = null;
    this.statusById = new Map();
    this.bridgeById = new Map();
    this.stale = true;
    this.queuing = false;
    this.followNote = '';
    this.span = null;
    this.draft = null;
    this.sectionMarks = [];
    this.rawPrompt = false;
    this.activeTab = 'prompt';
    this.root = el('div', 'h3ct-root');
    this.root.addEventListener('pointerdown', (event) => event.stopPropagation());
    this.root.addEventListener('keydown', (event) => {
      if (!event.ctrlKey && !event.metaKey && !event.altKey) event.stopPropagation();
    });
    this.frameImages = new FrameImages(this);
    this.build();
    this.render();
  }

  build() {
    const head = el('div', 'h3ct-head');
    this.summaryEl = el('span', 'h3ct-summary');
    this.fullLink = el('a', 'h3ct-link', 'Open in new tab');
    this.fullLink.title = 'Open the full video in a new tab';
    this.fullLink.target = '_blank';
    this.fullLink.rel = 'noopener';
    this.fullDownloadLink = el('a', 'h3ct-link', 'Download');
    this.fullDownloadLink.title = 'Download the full video';
    this.addButton = button('+ Clip', 'Add a clip at the end', () => this.addBox());
    this.renderNextButton = button('Render next', '', () => this.queueNext());
    this.renderButton = button('▶ Render', '', () => this.queue(), 'h3ct-primary');
    head.append(this.summaryEl, el('span', 'h3ct-grow'), this.fullLink, this.fullDownloadLink, this.addButton,
      this.renderNextButton, this.renderButton);
    this.pins = new Pins();
    // What a switch turned off cleared, by pin key, so turning it back on brings it back.
    this.stash = new Map();
    this.feedbackSection = new SwitchSection('Story feedback', {onToggle: (on) => {
      this.pins.set('feedback', on);
      if (!on) this.feedbackInput.value = '';
      this.renderFeedback();
      if (on) this.feedbackInput.focus();
    }});
    this.feedbackEl = this.feedbackSection.root;
    this.feedbackInput = el('textarea', 'h3ct-text');
    this.feedbackInput.rows = 2;
    this.feedbackInput.placeholder = 'Make subject 1 kneel after stubbing his toe…';
    this.feedbackInput.setAttribute('aria-label', 'Story feedback');
    this.feedbackInput.addEventListener('input', () => this.renderFeedback());
    this.editMessage = el('div', 'h3ct-hint');
    this.feedbackButton = button('Apply feedback', 'Keep the existing story while incorporating this suggestion',
      () => this.editStory({kind: 'feedback', text: this.feedbackInput.value, box: this.box()?.id}));
    this.feedbackSection.body.append(this.feedbackInput, this.feedbackButton, this.editMessage);

    const lane = this.laneEl = el('div', 'h3ct-lane');
    this.rulerEl = el('div', 'h3ct-ruler');
    this.rulerEl.title = 'Click or drag to move the playhead: the video so far, or the full video, plays from there';
    this.rulerEl.addEventListener('pointerdown', (event) => this.scrubStart(event));
    this.trackEl = el('div', 'h3ct-track');
    // The playhead: where the playing video is on the Timeline, drawn over the ruler, the clips and the audio lanes.
    this.playheadFrame = null;
    this.playheads = [0, 1, 2].map(() => {
      const line = el('div', 'h3ct-playhead');
      line.hidden = true;
      line.setAttribute('aria-hidden', 'true');
      return line;
    });
    this.trackEl.addEventListener('pointerdown', (event) => this.drawStart(event));
    this.stillsEl = el('div', 'h3ct-stills');
    // The selected clip's videos, one row each, when it has several.
    this.stackEl = el('div', 'h3ct-stack');
    this.stackEl.hidden = true;
    this.audioLanes = new AudioLanes(this);
    this.trackEditor = new TrackEditor(this);
    this.dialogue = new DialoguePanel(this);
    this.chain = new ChainSettings(this);
    lane.append(this.stillsEl, this.rulerEl, this.trackEl, this.trackEditor.root, this.stackEl, this.audioLanes.root, this.audioLanes.settings,
      this.dialogue.root);
    this.hintEl = el('p', 'h3ct-hint');
    this.readOnlyEl = el('p', 'h3ct-hint problem');
    this.readOnlyEl.hidden = true;
    this.touchPan = false;

    this.panelEl = el('div', 'h3ct-panel');
    const panelHead = el('div', 'h3ct-panelhead');
    this.titleEl = el('span', 'h3ct-title');
    this.leftButton = button('◀', 'Move the clip earlier', () => this.move(-1));
    this.rightButton = button('▶', 'Move the clip later', () => this.move(1));
    this.duplicateButton = button('Duplicate', 'Copy the clip after itself, with a new seed', () => this.duplicate());
    this.deleteButton = button('Delete', 'Delete the clip', () => this.remove());
    this.countInput = el('input', 'h3ct-number h3ctk-count');
    this.countInput.type = 'number';
    this.countInput.min = '1';
    this.countInput.max = String(MAX_TAKES);
    this.countInput.step = '1';
    this.countInput.value = '1';
    this.countInput.setAttribute('aria-label', 'Takes to render');
    this.countInput.title = 'How many takes to render using the clip’s seed mode';
    this.countInput.addEventListener('input', () => {
      setIconLabel(this.boxRenderButton,this.generateLabel());
    });
    this.boxRenderButton = button('Generate clip', '', async () => {
      const outcome = await this.queueBox(1);
      if (outcome.queued === outcome.requested) this.countInput.value = '1';
      else if (outcome.queued > 0 && outcome.retryable) this.countInput.value = String(outcome.remaining);
      this.renderPanelInfo();
    }, 'h3ct-primary');
    const render = el('span', 'h3ctk-render');
    render.append(this.boxRenderButton);
    this.clipActions = el('div', 'h3ct-clip-actions');
    const actions = el('div', 'h3ct-row');
    actions.append(this.leftButton, this.rightButton, this.duplicateButton, this.deleteButton);
    this.clipActions.append(actions);
    panelHead.append(this.titleEl, el('span', 'h3ct-grow'), this.clipActions, render);
    this.panelTabsEl = el('div', 'h3ct-panel-tabs');
    this.panelTabsEl.setAttribute('role', 'tablist');
    this.tabButtons = {};
    this.tabPanels = {};
    for (const [key, label] of [['prompt', 'Prompt'], ['still', 'Shots'], ['takes', 'Takes'], ['box', 'Settings']]) {
      const tab = button(label, `${label} settings`, () => {
        this.setTab(key);
        this.renderPrompt();
        this.renderReferenceOverview();
      });
      tab.setAttribute('role', 'tab');
      tab.id = `h3ct-tab-${key}-${this.instanceId}`;
      this.tabButtons[key] = tab;
      decorateIcon(tab,{prompt:'prompt',still:'shots',takes:'takes',box:'settings'}[key],label,{text:true});
      tab.addEventListener('keydown',event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
        event.preventDefault();const keys=['prompt','still','takes','box'],at=keys.indexOf(key);
        const next=event.key==='Home'?0:event.key==='End'?keys.length-1:(at+(event.key==='ArrowRight'?1:-1)+keys.length)%keys.length;
        this.tabButtons[keys[next]].click();this.tabButtons[keys[next]].focus();
      });
      this.panelTabsEl.append(tab);
      const panel = el('div', 'h3ct-tabpanel');
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', tab.id);
      panel.id = `h3ct-panel-${key}-${this.instanceId}`;
      tab.setAttribute('aria-controls', panel.id);
      this.tabPanels[key] = panel;
    }
    // Keep legacy reference DOM IDs and a programmatic button for old navigation.
    this.tabPanels.references = el('div', 'h3ct-tabpanel');
    this.tabPanels.references.id = `h3ct-panel-references-${this.instanceId}`;
    this.tabButtons.references = button('References', 'References used by this clip', () => this.setTab('references'));
    this.tabButtons.references.id = `h3ct-tab-references-${this.instanceId}`;
    this.tabButtons.references.hidden = true;
    this.tabPanels.references.setAttribute('aria-labelledby', this.tabButtons.references.id);
    this.promptEl = el('textarea', 'h3ct-text');
    this.promptEl.rows = 4;
    this.promptEl.setAttribute('aria-label', 'Clip prompt (raw text)');
    this.promptEl.placeholder = 'What happens in this clip. Mention references as @image1 or @audio1.';
    this.promptEl.addEventListener('input', () => {
      this.video().prompt = this.promptEl.value;
      this.sectionsButton.disabled = false;
      this.typed();
    });
    this.promptEl.addEventListener('focus', () => { this.activePromptEl = this.promptEl; });
    const promptTabs = el('div', 'h3ct-prompt-tabs');
    this.sectionsButton = button('Sections', 'Edit subjects, shots and sound separately', () => {
      if(this.promptDraftsReady?.()===false)return;
      this.rawPrompt = false;
      this.renderPrompt();
    });
    this.rawButton = button('Raw text', 'Edit the complete H3 prompt', () => {
      if(this.promptDraftsReady?.()===false)return;
      this.rawPrompt = true;
      this.renderPrompt();
    });
    promptTabs.append(el('span', 'h3ct-label', 'Clip prompt'), this.sectionsButton, this.rawButton);
    this.promptRefsEl = el('div', 'h3cp-strip');
    this.promptRefsEl.setAttribute('aria-label', 'References in this prompt');
    this.structureEl = el('div', 'h3ct-structure');
    this.previewsEl = el('div', 'h3ct-previews');
    this.platesEl = el('div', 'h3ct-plates');
    this.referenceOverviewEl = el('div');
    this.platesDetails = el('details');
    this.platesDetails.append(el('summary', null, 'Appearance plates (accepted)'), this.platesEl);
    this.structureEl.addEventListener('scroll', () => this.card.hide());
    this.chipsEl = el('div', 'h3ct-chips');
    this.modeEl = el('div', 'h3ct-mode');
    this.convertButton = button('Convert to FLF2VA', '', () => {
      this.host.undoStep?.();
      this.box().flf_refmods = true;
      adoptEndpointGuides(this.state, this.selected, this.host.context());
      this.commit();
      this.host.undoStep?.();
    });
    this.convertHint = el('p', 'h3ct-hint');
    this.convertRow = el('div', 'h3ct-row');
    this.convertRow.append(this.convertButton, this.convertHint);
    this.promptProblemEl = el('p', 'h3ct-hint problem');
    this.dialogueSelect = el('select', 'h3ct-select');
    this.dialogueSelect.append(option('cues', 'From the cues'), option('manual', 'Typed in the prompt'));
    this.dialogueSelect.addEventListener('change', () => {
      const layer = this.pickedLayer();
      if (layer) layer.dialogue = this.dialogueSelect.value === 'manual' ? 'manual' : 'cues';
      else model.setBoxDialogue(this.state, this.selected, this.dialogueSelect.value);
      this.commit();
    });
    this.dialogueField = field('Dialogue', this.dialogueSelect);
    this.dialogueField.title = "From the cues: the recording's cues in this clip's window become its <d> lines, at their "
      + 'own times. Typed in the prompt: the clip keeps your own <d> lines and leaves the cues out';
    this.firstPicker = el('div', 'h3cp-picker');
    this.lastPicker = el('div', 'h3cp-picker');
    this.cutInput = el('input');
    this.cutInput.type = 'checkbox';
    this.cutInput.addEventListener('change', () => {
      model.setCut(this.state, this.selected, this.cutInput.checked, this.host.context());
      this.commit();
    });
    this.sceneInput = el('input');
    this.sceneInput.type = 'checkbox';
    this.sceneInput.addEventListener('change', () => {
      if (this.sceneInput.checked) this.box().new_scene = true;
      else delete this.box().new_scene;
      this.commit();
    });
    this.refmodFramesInput = el('input');
    this.refmodFramesInput.type = 'checkbox';
    this.refmodFramesInput.setAttribute('aria-label', 'FLF2VA + cached RefMods');
    this.refmodFramesInput.addEventListener('change', () => {
      if (this.refmodFramesInput.checked) this.box().flf_refmods = true;
      else delete this.box().flf_refmods;
      this.commit();
    });
    this.refmodFramesField = field('FLF2VA + cached RefMods', this.refmodFramesInput);
    this.refmodFramesField.title = 'Experimental. Fresh clips use native First/Last endpoints. Continuous clips keep the full carried video/audio overlap without creating a still. Additional image references use cached RefMods, and audio references are passed on as audio references. Use FLF2VA video model weights. Stills also reuse compressed image references and accepted guides, with less reference detail. Raw video references retain REF2VA.';
    this.exactInput = el('input');
    this.exactInput.type = 'checkbox';
    this.exactInput.addEventListener('change', () => {
      model.setExact(this.state, this.selected, this.exactInput.checked, this.host.context());
      this.commit();
    });
    this.framesInput = el('input', 'h3ct-number');
    this.framesInput.type = 'number';
    this.framesInput.min = '1';
    this.framesInput.step = '1';
    this.framesInput.addEventListener('change', () => {
      model.setFrames(this.state, this.selected, this.framesInput.value, this.host.context());
      this.commit();
    });
    this.seedInput = el('input', 'h3ct-number');
    this.seedInput.type = 'text';
    this.seedInput.inputMode = 'numeric';
    this.seedInput.setAttribute('aria-label', 'Clip seed');
    this.seedInput.placeholder = 'auto';
    this.seedInput.addEventListener('change', () => {
      const parsed = model.parseState(`{"boxes":[{"seed":${JSON.stringify(this.seedInput.value)}}]}`).boxes[0].seed;
      if (this.seedInput.value && parsed === undefined) {
        this.seedInput.setCustomValidity('Use an unsigned 64-bit integer.');
        this.renderPanelInfo();
        this.renderHead();
        if (this.seedInput.isConnected) this.seedInput.reportValidity();
        return;
      }
      this.seedInput.setCustomValidity('');
      this.video().seed = parsed;
      this.commit();
    });
    this.seedMode = el('select', 'h3ct-select');
    this.seedMode.setAttribute('aria-label', 'Clip seed mode');
    this.seedMode.append(option('fixed', 'Fixed'), option('randomize', 'Randomize'));
    this.seedMode.addEventListener('change', () => {
      if (this.seedMode.value === 'randomize') this.box().seed_mode = 'randomize';
      else delete this.box().seed_mode;
      this.commit();
    });
    const roll = this.rollSeedButton = decorateIcon(button('', '', () => {
      this.video().seed = model.newSeed();
      this.commit();
    }), 'shuffle', 'Choose a new seed for the next render');
    const upload = (end) => button('Upload…', `Upload a picture into the Timeline and make it this clip’s ${end} frame`,
      () => this.uploadFrame(end));
    this.uploadNote = el('p', 'h3ct-hint h3cq-note');
    this.uploadNote.setAttribute('role', 'status');
    this.uploadNote.hidden = true;
    this.firstNote = el('p', 'h3ct-hint'); this.lastNote = el('p', 'h3ct-hint');
    this.firstNote.hidden = this.lastNote.hidden = true;
    this.firstField = group('First frame', this.firstPicker, this.firstNote, upload('first'));
    this.cutField = field('Cut', this.cutInput);
    this.cutField.title = 'Start a new shot. Visual memory supplies the preceding video as context while the new shot starts immediately';
    this.sceneField = field('New scene', this.sceneInput);
    this.sceneField.title = 'This cut moves to another place or time. The preceding video supplies history; the new prompt defines the setting';
    this.joinSelect = el('select', 'h3ct-select');
    this.joinSelect.setAttribute('aria-label', 'How this clip joins the clip before');
    this.joinSelect.append(...model.JOINS.map((kind) => option(kind, JOIN_LABELS[kind])));
    // The Join switch is the Continue choice: on, the select offers only the joins that change something.
    this.joinSelect.options[0].hidden = true;
    this.joinNote = el('input', 'h3ct-note');
    this.joinNote.type = 'text';
    this.joinNote.placeholder = 'Note (optional)';
    this.joinNote.setAttribute('aria-label', 'Join note');
    const join = () => {
      model.setJoin(this.state, this.selected, this.joinSelect.value, this.joinNote.value, this.host.context());
      this.commit();
    };
    this.joinSelect.addEventListener('change', join);
    this.joinNote.addEventListener('change', join);
    this.joinField = el('div', 'h3ct-field');
    this.joinField.title = 'How this clip follows the one before: Continue and Transition carry its last frames, and a '
      + 'transition stages a move; Cut starts a new shot of the same scene; New scene moves to another place or time';
    this.joinField.append(el('span', 'h3ct-label', 'Join'), this.joinSelect, this.joinNote);
    this.exactField = field('Exact length', this.exactInput);
    this.exactField.title = 'Play exactly the frames you set. H3 generates the next length on its frame grid, '
      + 'and the frames after yours are dropped';
    this.framesField = field('Frames', this.framesInput);
    this.framesField.title = 'The frames this clip plays';
    this.bridges = new BridgePanel(this);
    this.takes = new TakesPanel(this);
    const disclosure = (title, ...roots) => {
      const details = el('details', 'h3ct-settings-section');
      details.append(el('summary', null, title), ...roots);
      return details;
    };
    const section = (title, onToggle, ...roots) => {
      const block = new SwitchSection(title, {onToggle: (on) => { if (!this.readOnly.length) onToggle(on); }});
      block.body.append(...roots);
      return block;
    };
    const frames = el('div', 'h3ct-row');
    const lastField = group('Last frame', this.lastPicker, this.lastNote, upload('last'));
    imageDrop(this.firstField, file => this.dropGuide(file, 'first'));
    imageDrop(lastField, file => this.dropGuide(file, 'last'));
    frames.append(this.firstField, lastField);
    const joins = el('div', 'h3ct-row'); joins.append(this.sceneField, this.joinField);
    this.frameSettings = section('First & last frame', (on) => this.toggleFrames(on), frames);
    this.joinSettings = section('Cut', (on) => {
      if (this.state.bible) model.setJoin(this.state, this.selected, on ? 'cut' : 'continue', '', this.host.context());
      else model.setCut(this.state, this.selected, on, this.host.context());
      this.commit();
    }, joins);
    this.lengthSettings = section('Exact length', (on) => {
      model.setExact(this.state, this.selected, on, this.host.context());
      this.commit();
    }, this.framesField);
    this.seedSettings = section('Fixed seed', (on) => {
      if (on) { delete this.box().seed_mode; this.video().seed = 42; }
      else this.box().seed_mode = 'randomize';
      this.commit();
    }, field('Seed', this.seedInput, roll));
    this.bridgeDetails = section('Bridge', (on) => this.toggleBridge(on), this.bridges.root);
    this.bridgeDetails.titleEl.title = 'New frames across the cut';
    this.videoPickerEl = el('div', 'h3ct-video-picker');
    this.videoPickerEl.setAttribute('role', 'group');
    this.videoPickerEl.setAttribute('aria-label', 'Video to edit');
    this.videoPickerEl.hidden = true;
    this.videosBody = el('div', 'h3ct-videos');
    this.switchBody = el('div', 'h3ct-switch');
    this.switchGroup = el('div');
    this.switchGroup.append(el('p', 'h3sw-subhead', 'Switch'), this.switchBody);
    this.videosGroup = section('Multiple videos', (on) => this.toggleVideos(on), this.videosBody, this.switchGroup);
    this.videoSettings = el('div', 'h3ct-video-settings');
    this.videoSettings.append(this.videosGroup.root);
    this.layerShotsNote = el('p', 'h3ct-hint');
    this.layerTakesNote = el('p', 'h3ct-hint');
    this.promptMarks = new MentionLayer(this.promptEl, this.mentionHooks());

    const shared = this.sharedRoot = el('div', 'h3ct-shared');
    this.sharedEl = el('textarea', 'h3ct-text');
    this.sharedEl.rows = 2;
    this.sharedEl.placeholder = 'Added before every clip’s prompt: style, place, who @image1 is…';
    this.sharedEl.setAttribute('aria-label', 'Shared prompt');
    this.sharedEl.addEventListener('input', () => {
      this.state.prompt = this.sharedEl.value;
      this.typed();
    });
    this.sharedMarks = new MentionLayer(this.sharedEl, this.mentionHooks());
    shared.append(el('span', 'h3ct-label', 'Shared prompt'), this.sharedMarks.root);

    this.clipShotsEl = el('div');
    this.clipShotsEl.append(this.previewsEl, this.platesDetails);
    this.tabPanels.still.append(this.layerShotsNote, this.clipShotsEl);
    this.tabPanels.prompt.append(promptTabs, this.promptRefsEl, this.structureEl, this.promptMarks.root, shared);
    this.effectivePromptEl = el('details');
    this.promptReferencesDetails = disclosure('References mentioned in this clip', this.tabPanels.references);
    this.tabPanels.references.append(this.referenceOverviewEl, this.chipsEl,
      button('Accepted appearance plates', 'Open Shots to inspect accepted plates', () => this.setTab('still')));
    this.tabPanels.prompt.append(this.promptReferencesDetails, this.effectivePromptEl);
    this.tabPanels.box.append(this.modeEl, this.convertRow, this.videoSettings, this.frameSettings.root, this.uploadNote,
      this.joinSettings.root, this.lengthSettings.root, this.seedSettings.root, this.bridgeDetails.root);
    this.memoryEl = el('div');
    this.memoryDetails = section('Visual memory', (on) => {
      this.video().memory = on ? (this.state.bible ? 'cast' : 'scene') : 'off';
      this.commit();
    }, this.memoryEl);
    this.refmodSection = section('FLF2VA + cached RefMods', (on) => {
      if (on) this.box().flf_refmods = true;
      else delete this.box().flf_refmods;
      this.commit();
    }, el('p', 'h3ct-hint', 'Experimental. Needs FLF2VA video model weights.'));
    this.refmodSection.titleEl.title = this.refmodFramesField.title;
    this.tabPanels.box.append(this.refmodSection.root, this.memoryDetails.root);
    this.castChipsEl = el('div', 'h3cc-chips');
    this.castChipsEl.setAttribute('aria-label', 'Characters, places and props in this clip');
    const cast = el('section');
    cast.append(el('div', 'h3ct-section-heading', 'In this clip'), this.castChipsEl);
    this.tabPanels.prompt.prepend(cast, this.promptProblemEl, this.dialogueField);
    this.checks = new CheckPanel(this);
    this.continuityDetails = new SwitchSection('Continuity check', {auto: true});
    this.continuityDetails.body.append(this.checks.root);
    this.checks.onRender = (available) => this.continuityDetails.set(available, {
      title: available ? 'Available: this clip has a rendered take' : 'Turns on when this clip has a rendered take',
      state: available ? '' : 'Render first'});
    this.clipTakesEl = el('div');
    this.takesEmpty = el('div', 'h3ct-empty-state');
    this.takesEmpty.append(icon('takes'), el('strong', null, 'No takes yet'),
      el('span', null, 'Generate this clip to make its first take. Every render is kept here so you can compare and switch.'));
    this.clipTakesEl.append(this.takesEmpty, this.takes.root, this.takes.bridgeRoot, this.continuityDetails.root);
    this.clipTakesEl.addEventListener('h3c-takes-listed', () => this.syncTakesEmpty());
    this.tabPanels.takes.append(this.layerTakesNote, this.clipTakesEl);
    for(const [control,name,label] of [[this.addButton,'plus','Add clip'],[this.renderNextButton,'next','Render next'],[this.renderButton,'all','Render remaining'],[this.boxRenderButton,'play','Generate clip'],[this.leftButton,'left','Move clip earlier'],[this.rightButton,'right','Move clip later'],[this.duplicateButton,'duplicate','Duplicate'],[this.deleteButton,'trash','Delete']])decorateIcon(control,name,label);
    this.panelEl.append(panelHead, this.videoPickerEl, this.panelTabsEl, this.tabButtons.references,
      ...['prompt', 'still', 'takes', 'box'].map(key => this.tabPanels[key]));
    this.setTab(this.activeTab);

    this.refmodsEl = el('details', 'h3ct-advanced');
    this.referencesEl = el('details', 'h3ct-advanced');
    this.pictures = new PicturesPanel(this);
    this.cast = new CastPage(this);
    this.castEl = this.cast.root;
    this.root.append(head, this.readOnlyEl, this.feedbackEl, this.referencesEl, this.pictures.root, this.refmodsEl, this.chain.root, this.castEl, this.frameImages.preparation.root, lane, this.trackEditor.footer, this.hintEl,
      this.panelEl);
    this.renderRefmods();
  }

  setTab(key) {
    if (key === 'references') { key = 'prompt'; this.promptReferencesDetails.open = true; }
    if (!this.tabButtons[key]) return;
    this.activeTab = key;
    for (const name of ['prompt', 'still', 'takes', 'box']) {
      const selected = name === key, tab = this.tabButtons[name];
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected?0:-1;
      this.tabPanels[name].hidden = !selected;
    }
    this.takes?.render();
    this.syncTakesEmpty();
  }

  syncTakesEmpty() {
    if (this.takesEmpty) this.takesEmpty.hidden = !this.takes || !this.takes.root.hidden || !this.takes.bridgeRoot.hidden;
  }

  focusClipPrompt() {
    if (!this.box()) return null;
    this.setTab('prompt');
    const usable = (area) => area?.isConnected && !area.closest('[hidden], .h3sw-section:not(.on)');
    const area = usable(this.activePromptEl) ? this.activePromptEl
      : this.structureEl.querySelector('.h3sw-section:not([hidden]) textarea') ?? this.structureEl.querySelector('textarea') ?? this.promptEl;
    const section = area.closest('.h3sw-section')?.h3swSection;
    if (section && !section.open) { this.pins.set(section.pin, true); section.set(true); }
    this.activePromptEl = area;
    area.focus();
    return area;
  }

  inspect(target) {
    // Track stays in the borrowed Timeline region; editor.root stays on the graph node.
    this.trackEl.dispatchEvent(new CustomEvent('h3c-inspect', {bubbles: true, detail: target}));
  }

  inspectClip() {
    this.inspect({kind: 'clip', box: this.box()?.id ?? null});
  }

  box() {
    return this.state.boxes[this.selected];
  }

  // The video of the selected clip the panel edits: the clip itself, or one of its other videos.
  video() {
    const box = this.box();
    return box?.layers?.find((layer) => layer.id === this.picked) ?? box;
  }

  pickedLayer() {
    const video = this.video();
    return video && video !== this.box() ? video : null;
  }

  pickedLabel() {
    const layer = this.pickedLayer();
    return layer ? videoLayers.videosOf(this.state, this.selected).find((video) => video.id === layer.id).label : '';
  }

  pick(id) {
    if(this.promptDraftsReady?.()===false)return;
    this.picked = id === this.box()?.id ? null : id;
    this.renderTrack();
    this.renderPanel();
    this.inspectClip();
  }

  // Clip `index` as describeBox sees it, with the problems of its other videos named by their labels.
  describe(index, connected = this.connectedSets(), context = this.host.context()) {
    const info = model.describeBox(this.state, index, connected, context);
    for (const video of videoLayers.videosOf(this.state, index).slice(1)) {
      const view = videoLayers.layerView(this.state, index, video.id);
      for (const problem of model.describeBox(view, index, connected, context).problems) {
        if (!info.problems.includes(problem)) info.problems.push(`${video.label}: ${problem}`);
      }
    }
    return info;
  }

  // The picked video as describeBox sees it: what it renders as and what stops Generate.
  pickedInfo(connected = this.connectedSets(), context = this.host.context()) {
    const layer = this.pickedLayer();
    if (!layer) return model.describeBox(this.state, this.selected, connected, context);
    const info = model.describeBox(videoLayers.layerView(this.state, this.selected, layer.id), this.selected, connected,
      context);
    if (!videoLayers.switchFits(this.state, this.selected)) info.problems.push(videoLayers.SWAPS_DONT_FIT);
    info.warnings = model.swapWarnings(this.state, this.selected);
    return info;
  }

  // The status of video `id` of `box`: the box's own, or one of its videos'.
  videoStatusOf(box, id) {
    const status = this.statusOf(box);
    return id === box.id ? status : status?.videos?.find((video) => video.id === id) ?? null;
  }

  destroy() {
    this.promptForm?.destroy();
    clearTimeout(this.typingTimer);
    this.frameImages.destroy();
    this.replacements.destroy();
    for (const marks of [...this.sectionMarks, this.promptMarks, this.sharedMarks]) marks.destroy();
    this.card.hide();
    this.cast.destroy();
  }

  connectedSets() {
    const connected = this.host.connected();
    return {
      images: new Set(connected.images.filter(ref=>!ref.problem).map((ref) => ref.name)),
      audios: new Set(connected.audios.filter(ref=>!ref.problem).map((ref) => ref.name)),
      videos: new Set((connected.videos ?? []).filter(ref=>!ref.problem).map(ref => ref.name)),
      video_audios: new Set((connected.video_audios ?? []).filter(ref=>!ref.problem).map(ref => ref.name)),
      problems:new Map(Object.values(connected).flat().filter(ref=>ref.problem).map(ref=>[ref.name,ref.problem])),
      conflicts: new Set([...connected.images, ...connected.audios].filter(ref => ref.conflict).map(ref => ref.name)),
    };
  }

  mentionHooks() {
    return {
      live: () => {
        const connected = this.connectedSets();
        return new Set([...connected.images, ...connected.audios, ...connected.videos, ...connected.video_audios]);
      },
      onHover: (part, rect) => this.card.show(this.mentionInfo(part.name), rect),
      onLeave: () => this.card.hide(),
    };
  }

  // The shared prompt goes before every box, so its mentions get the selected box's tags too.
  mentionInfo(name) {
    const box = this.box();
    const tags = box ? model.describeBox(this.state, this.selected, this.connectedSets(), this.host.context()).tags : [];
    return model.describeMention(name, this.host.connected(), tags, box ? this.selected + 1 : null);
  }

  statusOf(box) {
    return this.statusById.get(box.id);
  }

  bridgeStatusOf(id) {
    return this.bridgeById.get(id);
  }

  defaultSpan() {
    const audioEnd = Math.max(0, ...model.resolvedAudio(this.state).map(window => (window.start + window.duration) * model.FPS));
    return Math.max(20 * model.FPS, Math.ceil(Math.max(model.totalFrames(this.state), audioEnd) * 1.25));
  }

  height() {
    return PANEL_HEIGHT;
  }

  // The runs Render all queues: every box that isn't done and every other video of a clip without a take, then every
  // bridge that isn't done and has no problem, and a candidate for every replacement whose confirmed region has none
  // yet.
  remaining() {
    const count = this.state.boxes.length;
    const bridges = model.keptBridges(this.state);
    const indexOf = (bridge) => this.state.boxes.findIndex((box) => box.id === bridge.before);
    if (this.stale || !this.status?.ok) {
      return count + videoLayers.layerIds(this.state).length + bridges.filter((bridge) => (!model.isReplacement(bridge) || bridge.review)
        && !model.bridgeProblem(this.state, indexOf(bridge))).length;
    }
    const queued = (bridge) => {
      const status = this.bridgeStatusOf(bridge.before)?.status;
      return model.isReplacement(bridge) ? ['pending', 'next'].includes(status) : !['done', 'problem'].includes(status);
    };
    const videos = this.state.boxes.reduce((sum, box) => sum + videosToRender(box, this.statusOf(box)).length, 0);
    return this.state.boxes.filter((box) => !hasTake(this.statusOf(box))).length + videos + bridges.filter(queued).length;
  }

  // The clip the next run renders: the other videos of the clips before the next box without a take come first.
  nextBox() {
    if (!this.state.boxes.length) return null;
    if (this.stale || !this.status?.ok) return 1;
    const boxes = this.state.boxes;
    const index = boxes.findIndex((box) => !hasTake(this.statusOf(box)));
    const layer = boxes.slice(0, index < 0 ? boxes.length : index)
      .findIndex((box) => videosToRender(box, this.statusOf(box)).length);
    if (layer >= 0) return layer + 1;
    return index < 0 ? null : index + 1;
  }

  // The parts the Studio places in its own layout.
  regions() {
    return {summary: this.summaryEl, add: this.addButton, next: this.renderNextButton, all: this.renderButton,
      open: this.fullLink, download: this.fullDownloadLink, feedback: this.feedbackEl, references: this.referencesEl,
      pictures: this.pictures.root, refmods: this.refmodsEl, lane: this.laneEl, laneFooter:this.trackEditor.footer, hint: this.hintEl, readOnly: this.readOnlyEl, panel: this.panelEl,
      cast: this.castEl, sharedPrompt: this.sharedRoot, clipTakes: this.takes.root, videoPicker: this.videoPickerEl,
      bridgeTakes: this.takes.bridgeRoot, continuity: this.checks.root, bridgeSettings: this.bridges.root,
      overlapSettings:this.trackEditor.overlap.root, audioSettings: this.audioLanes.settings, dialogueSettings: this.dialogue.root, timedTextSettings: this.audioLanes.textSettings,
      audioHeader: this.audioLanes.header, timedTextHeader: this.audioLanes.textHeader,
      stillPrompts: this.frameImages.preparation.root, stillInstructions:this.frameImages.preparation.instructionsRoot, chainSettings: this.chain.root};
  }

  // Upload… beside a frame picker: the new picture becomes the `end` frame of the box chosen when it was pressed.
  uploadFrame(end) {
    const box = this.box();
    if (!box) return;
    this.frameImages.open(box.id, {kind:end});
    this.frameImages.chooseUpload();
  }

  // A dropped image becomes the selected clip's guide for `target` (a First, Last or Shot marker), like Upload guide….
  dropGuide(file, target) {
    const box = this.box();
    if (!box) return;
    target = typeof target === 'string' ? {kind: target} : target;
    this.frameImages.open(box.id, target);
    this.frameImages.upload(file, box.id, target).catch(error => this.frameImages.note(error.message));
  }

  // Host calls

  load() {
    this.editRevision=(this.editRevision??0)+1;
    if(this.promptForm?.hasDrafts())this.promptForm.discardDrafts('Unsaved fields were discarded because the project or history changed.');
    this.replacements.close();
    this.state = model.parseState(this.host.read());
    syncTargets(this.state,this.host.context());
    if (!this.readOnly.length && this.adoptEndpoints()) this.save(model.serialize(this.state));
    this.selected = Math.min(this.selected, Math.max(0, this.state.boxes.length - 1));
    this.stale = true;
    this.render();
    this.cast.changed();
    this.host.loaded?.();
  }

  startIfEmpty() {
    if (this.state.boxes.length || this.readOnly.length) return;
    if(tracks.enabled(this.state)){this.trackEditor.addClip();return;}
    model.addBox(this.state, this.host.context());
    this.save(model.serialize(this.state));
    this.render();
  }

  contextChanged() {
    if (this.readOnly.length) return this.render();
    const before = model.serialize(this.state);
    model.normalize(this.state, this.host.context());
    syncTargets(this.state,this.host.context());
    const after = model.serialize(this.state);
    if (after !== before) this.save(after);
    this.render();
  }

  // The features of a newer Studio this Timeline needs; with any, it is read-only.
  get readOnly() {
    return model.unknownFeatures(this.state);
  }

  // Every write of the Timeline text. One from a newer Studio is never written, since parseState drops what this
  // editor doesn't know: the edit is undone from the node's text instead. Whether the text was written.
  save(text, typing = false) {
    if (!this.readOnly.length) {
      this.editRevision=(this.editRevision??0)+1;
      this.host.write(text, typing);
      return true;
    }
    this.state = model.parseState(this.host.read());
    syncTargets(this.state, this.host.context());
    this.selected = Math.min(this.selected, Math.max(0, this.state.boxes.length - 1));
    this.render();
    return false;
  }

  setStatus(status) {
    // A status request that fails or times out never hides saved takes: the clips the last good status showed are
    // still on disk, so they stay, with a note that status is unavailable.
    if (status && !status.ok && this.lastGoodStatus) {
      status = {...this.lastGoodStatus, unavailable: status.error};
    } else if (status?.ok) this.lastGoodStatus = status;
    this.status = status;
    this.statusById = new Map((status?.ok ? status.boxes : []).map((box) => [box.id, box]));
    this.bridgeById = new Map((status?.ok ? status.bridges ?? [] : []).map((item) => [item.box, item]));
    if (status?.followed?.length) this.followNote = followNote(this.state, status.followed);
    this.stale = false;
    this.renderTrack();
    this.renderHead();
    this.renderPanelInfo();
  }

  // The status no longer matches the Timeline. It stays drawn, marked stale, until the next one arrives: dropping it
  // would draw every clip without its take and then again with it.
  markStale() {
    if (this.stale) return;
    this.stale = true;
    this.renderHead();
    this.renderPanelInfo();
  }

  // Edits

  // Converted clips keep one image per endpoint: free guides on their first/last frame become First/Last stills.
  adoptEndpoints() {
    let changed = false;
    this.state.boxes.forEach((box, index) => {
      if (box.flf_refmods && adoptEndpointGuides(this.state, index, this.host.context())) changed = true;
    });
    return changed;
  }

  commit(renderPanel = true) {
    clearTimeout(this.typingTimer);
    this.typingTimer = null;
    if (!this.writeState()) return;
    this.stale = true;
    this.followNote = '';
    this.renderTrack();
    this.renderHead();
    if (renderPanel) this.renderPanel();
    else { this.renderReferenceOverview(); this.renderPanelInfo(); }
    this.host.changed();
    this.cast.changed();
  }

  applyPrompt(source,next,{structural=false}={}) {
    if(this.readOnly.length||this.video()?.prompt!==source)return false;
    if(next===source)return true;
    this.video().prompt=next;
    if(this.promptEl)this.promptEl.value=next;
    if(structural){this.host.undoStep?.();this.commit();this.host.undoStep?.();}else this.typed();
    return true;
  }

  // A key typed into a text field: the Timeline text follows every key, and the rest of commit(), with the edit's
  // place in the undo history, waits for a pause.
  typed() {
    if (!this.writeState(true)) return;
    clearTimeout(this.typingTimer);
    this.typingTimer = setTimeout(() => this.commit(false), TYPING_PAUSE);
  }

  // Undo and Redo first take typing that hasn't paused yet, or they would step past it.
  flushTyping() {
    if (this.typingTimer != null) this.commit(false);
  }

  writeState(typing = false) {
    this.adoptEndpoints();
    model.normalize(this.state, this.host.context());
    syncTargets(this.state,this.host.context());
    return this.save(model.serialize(this.state), typing);
  }

  select(index) {
    if(index!==this.selected&&this.promptDraftsReady?.()===false)return;
    if (this.selected !== index) {
      this.selectedShot = 1;
      this.picked = null;
    }
    this.selected = index;
    this.renderTrack();
    this.renderPanel();
    this.renderHead();
    this.cast.render();
    this.inspectClip();
  }

  addBox() {
    if(this.promptDraftsReady?.()===false)return;
    if(tracks.enabled(this.state))return this.trackEditor.addClip();
    this.selected = model.addBox(this.state, this.host.context());
    this.commit();
    this.inspectClip();
  }

  // Moves the selected clip. A Continue clip that lands after a clip with several videos must become a Cut, so that
  // is asked first.
  move(delta) {
    if(this.promptDraftsReady?.()===false)return;
    if(tracks.enabled(this.state))return this.trackEditor.move(delta);
    const context = this.host.context(), trial = model.parseState(model.serialize(this.state));
    model.moveBox(trial, this.selected, delta, context);
    const stacked = trial.boxes.findIndex((box, index) => videoLayers.continueAfterStack(trial, index));
    if (stacked >= 0 && !globalThis.confirm?.(videoLayers.continueAfterStack(trial, stacked))) return;
    this.selected = model.moveBox(this.state, this.selected, delta, context);
    if (stacked >= 0) this.state.boxes[stacked + 1].cut = true;
    this.commit();
    this.inspectClip();
  }

  duplicate() {
    if(this.promptDraftsReady?.()===false)return;
    if(tracks.enabled(this.state))return this.trackEditor.duplicate();
    this.selected = model.duplicateBox(this.state, this.selected, this.host.context());
    this.commit();
    this.inspectClip();
  }

  remove() {
    if(this.promptDraftsReady?.()===false)return;
    const videos = 1 + (this.box()?.layers?.length ?? 0);
    if (videos > 1 && !globalThis.confirm?.(`Delete clip ${this.selected + 1} and its ${videos} videos?`)) return;
    if(tracks.enabled(this.state))return this.trackEditor.removeClip();
    this.picked = null;
    this.selected = Math.max(0, model.removeBox(this.state, this.selected, this.host.context()));
    this.commit();
    this.inspectClip();
  }

  async queue() {
    if(this.promptDraftsReady?.()===false)return;
    await this.host.refresh?.();
    const remaining = this.remaining();
    if (remaining > 0) await this.submit(remaining);
  }

  async queueNext() {
    if(this.promptDraftsReady?.()===false)return;
    await this.host.refresh?.();
    if (this.remaining() > 0) await this.submit(1);
  }

  // Queues takes using the selected clip's seed mode; stop if its identity or position changes.
  async queueBox(count = 1) {
    const outcome = {requested:count, queued:0, remaining:count, retryable:false};
    if(this.promptDraftsReady?.()===false)return outcome;
    if (!this.box() || this.readOnly.length || this.queuing || this.queueBatch || this.seedInput?.validity?.valid === false) return outcome;
    const index = this.selected, id = this.box().id, layer = this.pickedLayer()?.id ?? null;
    const same = () => this.state.boxes[index]?.id === id && this.box()?.id === id
      && (this.pickedLayer()?.id ?? null) === layer;
    this.queueBatch = true;
    try {
      const approval = await this.host.preflight?.(index + 1, count);
      if (approval?.cancelled) return outcome;
      for (let run = 0; run < count; run += 1) {
        if (!same()) {
          this.setStatus({ok:false,error:`Queued ${outcome.queued} of ${count} takes. The selected clip changed; ${outcome.remaining} takes were not queued.`});
          return outcome;
        }
        if (!await this.submit(1, layer ? null : index + 1, null, approval?.receipt, layer)) {
          outcome.retryable = same();
          const detail = this.status?.error ?? 'Could not queue this take.';
          if (outcome.queued > 0) this.setStatus({ok:false,error:`Queued ${outcome.queued} of ${count} takes. ${outcome.retryable
            ? `${outcome.remaining} takes remain; Generate retries the remaining takes.`
            : `The selected clip changed; ${outcome.remaining} takes were not queued.`} ${detail}`});
          return outcome;
        }
        outcome.queued += 1;
        outcome.remaining -= 1;
      }
      return outcome;
    } catch (error) {
      this.setStatus({ok:false,error:error?.message??String(error)});
      return outcome;
    } finally { this.queueBatch = false; this.renderHead(); }
  }

  generateLabel() {
    const count = this.takeCount(), label = this.pickedLabel();
    if (!label) return renderLabel(this.selected + 1, count);
    return count > 1 ? `Generate ${count} takes of ${label}` : `Generate video ${label}`;
  }

  // The takes Render box queues: the count beside it, from 1 to MAX_TAKES.
  takeCount() {
    const count = Math.round(Number(this.countInput.value));
    return Number.isFinite(count) ? Math.min(MAX_TAKES, Math.max(1, count)) : 1;
  }

  async queueBridge() {
    const bridge = model.bridgeOf(this.state, this.selected);
    if (!bridge || this.queuing) return;
    await this.submit(1, null, bridge.before);
  }

  // Whether the run was queued: false while another is being queued, or when queueing failed.
  // `layer` asks for one of a clip's other videos instead of a box or bridge; it keeps its own seed.
  async submit(count, box, bridge, receipt, layer = null) {
    if(this.promptDraftsReady?.()===false)return false;
    if (this.readOnly.length || this.queuing || (bridge == null && this.seedInput?.validity?.valid === false)) return false;
    this.queuing = true;
    this.renderHead();
    this.renderPanelInfo();
    try {
      const targets = bridge != null || layer != null ? [] : box != null ? [this.state.boxes[box - 1]]
        : this.state.boxes.filter(item => !hasTake(this.statusOf(item))).slice(0, count);
      let changed = false;
      for (const target of targets) {
        if (target.seed_mode !== 'randomize' && target.seed != null) continue;
        const previous = target.seed;
        do { target.seed = model.newSeed(); } while (target.seed === previous);
        changed = true;
      }
      if (changed) this.commit();
      await this.host.queue(count, box, bridge, receipt, ...(layer != null ? [layer] : []));
      return true;
    } catch (error) {
      this.setStatus({ ok: false, error: `Could not queue: ${error?.message ?? error}` });
      return false;
    } finally {
      this.queuing = false;
      this.renderHead();
      this.renderPanelInfo();
    }
  }

  promptDraftsReady() {return this.promptForm?.canLeave()??true;}

  insert(text) {
    const area = this.activePromptEl ?? this.promptEl;
    const start = area.selectionStart ?? area.value.length;
    const end = area.selectionEnd ?? start;
    const before = area.value.slice(0, start);
    const after = area.value.slice(end);
    const lead = before && !/\s$/.test(before) ? ' ' : '';
    const tail = /^\s/.test(after) ? '' : ' ';
    area.focus();
    area.setSelectionRange(start, end);
    // Native text insertion keeps reference chips in the textarea's Undo/Redo history.
    if (!document.execCommand('insertText', false, `${lead}${text}${tail}`)) {
      area.setRangeText(`${lead}${text}${tail}`, start, end, 'end');
      area.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  // Dragging

  capture(event, onMove, onEnd, track = this.trackEl) {
    const id = event.pointerId;
    try {
      track.setPointerCapture(id);
    } catch {
      // synthetic events have no active pointer to capture
    }
    const move = (e) => {
      if (e.pointerId === id) onMove(e);
    };
    const end = (e) => {
      if (e.pointerId !== id) return;
      track.removeEventListener('pointermove', move);
      track.removeEventListener('pointerup', end);
      track.removeEventListener('pointercancel', end);
      onEnd(e);
    };
    track.addEventListener('pointermove', move);
    track.addEventListener('pointerup', end);
    track.addEventListener('pointercancel', end);
  }

  resizeStart(event, index) {
    if(this.promptDraftsReady?.()===false)return;
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    this.selected = index;
    this.renderPanel();
    this.inspectClip();
    const box = this.state.boxes[index];
    const fresh = model.isFresh(this.state, index);
    const context = this.host.context();
    const startX = event.clientX;
    const startFrames = box.frames;
    this.span = this.defaultSpan();
    const perPixel = this.span / (this.trackEl.getBoundingClientRect().width || 1);
    this.renderTrack();
    const fit = box.exact ? model.fitExact : model.snapFrames;
    const start = this.state.boxes.slice(0, index).reduce((sum, item) => sum + item.frames, 0);
    this.capture(event, (move) => {
      let wanted = startFrames + (move.clientX - startX) * perPixel;
      // Snap to beats: the edge lands on the nearest detected beat within 12 pixels (Shift drags freely).
      const beat = this.audioLanes.snapping && !move.shiftKey ? this.nearestBeat(start + wanted, 12 * perPixel) : null;
      if (beat != null) wanted = beat - start;
      const frames = fit(wanted, fresh, context, model.maxFrames(this.state));
      if (frames === box.frames) return;
      box.frames = frames;
      this.renderTrack();
      this.renderPanelInfo();
      this.renderHead();
    }, () => {
      this.span = null;
      this.commit();
    });
  }

  // Moves the playhead to the pointer: the Studio seeks its video there (`h3c-seek`, a Timeline frame).
  scrubStart(event) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const ruler = this.rulerEl;
    const seek = (e) => {
      const rect = ruler.getBoundingClientRect();
      const frame = Math.max(0, Math.round((e.clientX - rect.left) / (rect.width || 1) * (this.span ?? this.defaultSpan())));
      ruler.dispatchEvent(new CustomEvent('h3c-seek', {bubbles: true, detail: {frame}}));
    };
    seek(event);
    const id = event.pointerId;
    try { ruler.setPointerCapture(id); } catch { /* synthetic events have no active pointer */ }
    const move = (e) => { if (e.pointerId === id) seek(e); };
    const end = (e) => {
      if (e.pointerId !== id) return;
      ruler.removeEventListener('pointermove', move);
      ruler.removeEventListener('pointerup', end);
      ruler.removeEventListener('pointercancel', end);
    };
    ruler.addEventListener('pointermove', move);
    ruler.addEventListener('pointerup', end);
    ruler.addEventListener('pointercancel', end);
  }

  // Shows the playhead at Timeline `frame` (24 fps), or hides it for null.
  setPlayhead(frame) {
    this.playheadFrame = Number.isFinite(frame) ? frame : null;
    this.placePlayhead();
  }

  placePlayhead(span = this.span ?? this.defaultSpan()) {
    const frame = this.playheadFrame;
    for (const line of this.playheads) {
      line.hidden = frame == null;
      if (frame != null) line.style.left = percent(Math.min(frame, span) / span);
    }
  }

  // The Timeline frame nearest `frame` on a detected beat of an audio clip, within `reach` frames, or null.
  nearestBeat(frame, reach) {
    let best = null;
    for (const at of this.audioLanes.beatFrames()) {
      if (Math.abs(at - frame) <= reach && (best == null || Math.abs(at - frame) < Math.abs(best - frame))) best = at;
    }
    return best;
  }

  drawStart(event) {
    if (event.button !== 0 || (event.pointerType === 'touch' && getComputedStyle(this.trackEl).touchAction.includes('pan-x'))) return;
    const rect = this.trackEl.getBoundingClientRect();
    const span = this.defaultSpan();
    const perPixel = span / (rect.width || 1);
    const end = model.totalFrames(this.state);
    if ((event.clientX - rect.left) * perPixel < end) return;
    event.preventDefault();
    const fresh = this.state.boxes.length === 0;
    const context = this.host.context();
    const startX = event.clientX;
    this.span = span;
    this.capture(event, (move) => {
      if (this.draft == null && Math.abs(move.clientX - startX) < 4) return;
      this.draft = model.snapFrames((move.clientX - rect.left) * perPixel - end, fresh, context);
      this.renderTrack();
    }, () => {
      const frames = this.draft;
      this.draft = null;
      this.span = null;
      if (frames == null) {
        this.renderTrack();
        return;
      }
      this.selected = model.addBox(this.state, context, frames);
      this.commit();
      this.inspectClip();
    });
  }

  // Rendering

  render() {
    this.renderRefmods();
    this.renderTrack();
    this.renderPanel();
    this.renderHead();
  }

  thumbnail(container, url, label) {
    if (!url) return;
    const link = el('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener';
    const image = el('img'); image.alt = label;
    image.addEventListener('load', () => { link.append(image); container.prepend(link); }, {once: true});
    image.src = url;
  }

  renderRefmods() {
    this.pictures?.render();
    const root = this.refmodsEl;
    if (!root) return;
    const opened = root.open;
    const refs = this.state.refmods ?? [];
    const choices = this.host.refmodChoices?.() ?? [];
    root.replaceChildren(el('summary', null, `RefMods${refs.length ? ` (${refs.length})` : ''}`));
    root.open = opened;
    const connected = this.host.connected();
    fillReferenceSwitches(this.referencesEl, this.referenceOptions(), this.state.disabled_refs ?? [],
      (names, enabled) => this.setReferencesEnabled(names, enabled), {
        replace:ref=>this.replacements.open(ref.name),restore:ref=>this.replacements.restore(ref.name),preview:ref=>this.replacements.preview(ref),
        replacementProblem:ref=>audioSourceLocked(this.state,ref.name)?'Unlock audio from boxes before replacing its source.':'',
        clearDescriptions:this.host.describeImage?()=>this.replacements.clearAll():undefined,
      });
    const occupied = new Set([...connected.images, ...connected.audios].filter(ref => !ref.refmod).map(ref => ref.name));
    const images = Math.max(99, highestSlot(this.state) + 1);
    const availableSlots = kind => Array.from({length: kind === 'audio' ? 3 : images}, (_, i) => `${kind === 'audio' ? 'audio' : 'image'}${i + 1}`);
    const freeSlot = kind => availableSlots(kind).find(slot => !occupied.has(slot) && !refs.some(ref => ref.slot === slot));
    const changed = () => { this.commit(); this.renderRefmods(); };
    const actions = el('div', 'h3ct-row');
    const add = button('+ RefMod', 'Assign a saved RefMod to an unused reference slot', () => {
      const choice = choices.find(item => freeSlot(item.kind));
      if (!choice) return;
      this.state.refmods ??= [];
      this.state.refmods.push({slot: freeSlot(choice.kind), name: choice.name, member: choice.member,
        kind: choice.kind, strength: 1});
      changed();
    });
    add.disabled = !choices.some(item => freeSlot(item.kind));
    decorateIcon(add, 'plus', 'Add RefMod', {text: true}).title = 'Assign a saved RefMod to an unused reference slot';
    const refresh = decorateIcon(button('', '', async () => {
      try { await this.host.refreshRefmods?.(); }
      catch (error) { this.refmodMessage.textContent = error.message; }
    }), 'history', 'Refresh library', {text: true});
    refresh.title = 'Read saved RefMods and descriptions';
    actions.append(add, refresh);
    this.refmodMessage = el('p', 'h3ct-hint', 'Assign RefMods to unconnected slots. Story reads their saved descriptions automatically.');
    root.append(actions, this.refmodMessage);
    for (const ref of refs) {
      const card = el('div', 'h3ct-refmod');
      const row = el('div', 'h3ct-refmod-controls');
      const slot = el('select', 'h3ct-select'); slot.setAttribute('aria-label', 'RefMod slot');
      for (const name of availableSlots(ref.kind)) {
        const item = option(name, `@${name}`);
        item.disabled = name !== ref.slot && (occupied.has(name) || refs.some(other => other.slot === name));
        slot.append(item);
      }
      slot.value = ref.slot;
      slot.addEventListener('change', () => { ref.slot = slot.value; changed(); });
      const select = el('select', 'h3ct-select'); select.setAttribute('aria-label', `RefMod for @${ref.slot}`);
      const key = item => JSON.stringify([item.name, item.member ?? -1]);
      let choice = choices.find(item => key(item) === key(ref));
      for (const item of choices) select.append(option(key(item), `${item.name}${item.member >= 0 ? ` · ${item.title}` : ''} (${item.kind})`));
      if (!choice) select.append(option(key(ref), `${ref.name} (not in library)`));
      select.value = key(ref);
      select.addEventListener('change', () => {
        const item = choices.find(item => key(item) === select.value);
        const nextSlot = (item.kind === 'audio') === ref.slot.startsWith('audio') ? ref.slot : freeSlot(item.kind);
        if (!nextSlot) { select.value = key(ref); this.refmodMessage.textContent = 'No matching reference slot is free.'; return; }
        Object.assign(ref, {name: item.name, member: item.member, kind: item.kind, slot: nextSlot});
        delete ref.description;
        changed();
      });
      const strength = el('input', 'h3ct-number');
      strength.type = 'number'; strength.min = '0'; strength.max = '1'; strength.step = '0.05'; strength.value = ref.strength ?? 1;
      strength.setAttribute('aria-label', `Strength for @${ref.slot}`);
      strength.addEventListener('change', () => {
        if (!strength.checkValidity() || strength.value === '') return;
        ref.strength = Number(strength.value); changed();
      });
      row.append(slot, select, field('Strength', strength), button('Remove', `Remove RefMod @${ref.slot}`, () => {
        this.state.refmods = refs.filter(item => item !== ref); changed();
      }));
      const description = el('textarea', 'h3ct-text'); description.rows = 2;
      description.setAttribute('aria-label', `Story description for @${ref.slot}`);
      description.placeholder = choice?.description || 'Optional description for Story';
      description.value = ref.description ?? '';
      description.addEventListener('change', () => { ref.description = description.value; this.commit(false); });
      card.append(row, description);
      const source = [...connected.images, ...connected.audios].find(item => item.name === ref.slot && item.refmod);
      this.thumbnail(card, source?.preview, `RefMod @${ref.slot}`);
      if (occupied.has(ref.slot)) card.append(el('p', 'h3ct-hint problem', `@${ref.slot} also has an input. Disconnect it or choose another slot.`));
      root.append(card);
    }
  }

  renderHead() {
    this.frameImages.preparation.render();
    this.feedbackEl.hidden = !this.host.story?.() || !this.state.boxes.some(box => box.prompt.trim());
    this.feedbackButton.disabled = !!this.host.story?.()?.job || !this.box();
    const count = this.state.boxes.length;
    const ok = this.status?.ok === true;
    const remaining = this.remaining();
    const bridges = model.keptBridges(this.state);
    const what = bridges.length ? 'clip or bridge' : 'clip';
    const onScreen = model.seconds(model.totalFrames(this.state));
    let summary = `${count} ${count === 1 ? 'clip' : 'clips'} · ` + (videoLayers.hasLayers(this.state)
      ? `on screen ${onScreen} s · renders ${model.seconds(videoLayers.renderFrames(this.state))} s` : `${onScreen} s`);
    const replaced = bridges.filter(model.isReplacement).length, inserted = bridges.length - replaced;
    if (inserted) {
      summary += ` · ${inserted} ${inserted === 1 ? 'bridge' : 'bridges'}, +${model.seconds(model.insertedFrames(this.state))} s`;
    }
    if (replaced) summary += ` · ${replaced} ${replaced === 1 ? 'replacement' : 'replacements'}`;
    if (ok && !this.stale) summary += ` · ${this.status.message}`;
    if (ok && !this.stale && this.status.full_video_building) summary += ' · Building the full video in the background…';
    else if (ok && !this.stale && this.status.preview_video_building) summary += ' · Building the video so far…';
    else if (ok && !this.stale && this.status.preview_error && !this.status.preview_video) summary += ` · ${this.status.preview_error}`;
    setText(this.summaryEl, summary);
    setIconLabel(this.renderButton,count&&!remaining?'All rendered':`Render ${remaining} remaining`);
    this.renderButton.disabled = this.host.hasVideo?.()===false || !remaining || this.queuing || this.host.feeding?.()
      || !this.seedInput.validity.valid || this.readOnly.length > 0;
    this.addButton.disabled = this.readOnly.length > 0;
    this.renderButton.title = remaining
      ? `Queue ${remaining} run${remaining === 1 ? '' : 's'}, one per ${what} that has no take yet (outdated takes are kept; regenerate those one by one)`
      : `Every ${what} is rendered`;
    this.renderNextButton.disabled = this.renderButton.disabled;
    this.renderNextButton.title = remaining ? `Queue one run, for the next ${what} that is not rendered yet` : `Every ${what} is rendered`;
    // A stale status keeps its video too, or every pause in typing would take the full video off the player and back.
    const shown = ok && !this.queuing ? exportedVideo(this.status) : null;
    const full = shown?.file ?? null;
    this.partialVideo = shown?.partial ?? null;
    this.previewVideo = shown?.preview ?? null;
    this.videoClock = shown?.clock ?? null;
    const fullUrl = full ? this.host.viewUrl(full) : null;
    const which = this.partialVideo ? 'partial video' : this.previewVideo ? 'video so far' : 'full video';
    this.fullLink.title = `Open the ${which} in a new tab`;
    this.fullDownloadLink.title = `Download the ${which}`;
    for (const link of [this.fullLink, this.fullDownloadLink]) {
      link.hidden = !full;
      if (full) link.href = fullUrl;
      else {
        link.removeAttribute('href');
        link.removeAttribute('download');
      }
    }
    if (full) this.fullDownloadLink.download = full.filename;
    this.renderHint();
    this.checks.render();
    this.host.rendered?.();
  }

  renderHint() {
    const note = this.readOnly.length ? model.readOnlyNote(this.readOnly) : '';
    setText(this.readOnlyEl, note);
    if (this.readOnlyEl.hidden !== !note) this.readOnlyEl.hidden = !note;
    const conflicts = this.status?.ok && !this.stale ? this.status.timing_conflicts ?? [] : [];
    const unavailable = this.status?.unavailable
      ? `Status is unavailable right now (${this.status.unavailable.replace(/^Status unavailable: /, '')}); the clips shown are the last known ones and are still saved.` : '';
    const error = this.status && !this.status.ok ? this.status.error
      : [unavailable, this.status?.export_error, ...conflicts].filter(Boolean).join(' ');
    // Set by the Studio, whose mobile layout lets touches pan the track: reading styles after an edit restyles the
    // whole ComfyUI page, and so does replacing text that hasn't changed.
    const text = error || this.followNote || (this.touchPan
      ? 'Swipe to pan · drag edges to trim · tap a clip to edit · use + Clip to add'
      : 'Drag a clip’s right edge to resize it · drag after the last clip to draw one · click a clip to edit it');
    if (this.hintEl.textContent !== text) this.hintEl.textContent = text;
    this.hintEl.classList.toggle('problem', !!error);
  }

  referenceOptions() {
    const refs = this.host.connected();
    const connected = [...refs.images, ...refs.audios, ...(refs.videos ?? []), ...(refs.video_audios ?? [])];
    return [...connected, ...(this.state.refmods ?? []).filter(ref => !connected.some(source => source.name === ref.slot))
      .map(ref => ({name: ref.slot, title: ref.name, refmod: true}))];
  }

  setReferencesEnabled(names, enabled) {
    const disabled = new Set(this.state.disabled_refs ?? []);
    for (const name of names) { if (enabled) disabled.delete(name); else disabled.add(name); }
    this.state.disabled_refs = [...disabled];
    this.commit();
    this.renderRefmods();
  }

  renderTrack() {
    const context = this.host.context();
    const connected = this.connectedSets();
    const span = this.span ?? this.defaultSpan();
    // Measured before drawing: a size read after the track is redrawn restyles the whole ComfyUI page once more.
    const stillsWidth = this.stillsWidth(), laneWidth = this.audioLanes.width();
    const nodes = [];
    let start = 0;
    const starts = [];
    this.state.boxes.forEach((box, index) => {
      start=tracks.startFrame(this.state,box.id);
      starts.push(start);
      const info = this.describe(index, connected, context);
      const status = this.statusOf(box);
      const item = el('div', 'h3ct-box');
      item.tabIndex = 0;
      item.setAttribute('role', 'button');
      item.setAttribute('aria-label', `Clip ${index + 1}`);
      if (status) item.classList.add(status.status);
      item.classList.toggle('selected', index === this.selected);
      item.classList.toggle('problem', info.problems.length > 0);
      item.classList.toggle('cut', index > 0 && !!box.cut);
      item.classList.toggle('new-scene', index > 0 && !!box.cut && !!box.new_scene);
      item.style.left = percent(start / span);
      item.style.width = percent(box.frames / span);
      if (status?.thumb) {
        const image = el('img');
        image.dataset.src = this.host.viewUrl(status.thumb);
        image.alt = '';
        image.draggable = false;
        item.append(image);
      }
      const mark = { done: ' ✓', next: ' ●', outdated: ' ⟳' }[status?.status] ?? '';
      const label = el('span', 'h3ct-boxlabel',
        `${index > 0 && box.cut ? '✂ ' : ''}#${index + 1} · ${model.seconds(box.frames)} s${mark}`);
      item.append(label);
      if (box.layers?.length) this.drawStack(item, label, index);
      item.title = [`Clip ${index + 1}: ${model.lengthLabel(this.state, index, context)}`, info.mode,
        status?.status === 'outdated' ? `Outdated take, still playing: ${status.reason ?? 'the box changed since it was rendered'} Regenerate it to update it.` : status?.reason,
        box.prompt.trim().slice(0, 160), ...info.problems, ...info.warnings].filter(Boolean).join('\n');
      const handle = el('div', 'h3ct-handle');
      handle.title = 'Drag to change the length';
      handle.addEventListener('pointerdown', (event) => this.resizeStart(event, index));
      item.append(handle);
      item.addEventListener('pointerdown', (event) => {
        if (event.button !== 0) return;
        event.stopPropagation();
      });
      item.addEventListener('click', (event) => {
        if (event.button !== 0) return;
        event.stopPropagation();
        this.select(index);
      });
      item.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        event.stopPropagation();
        this.select(index);
      });
      nodes.push(item);
      start += box.frames;
    });
    for (const bridge of model.keptBridges(this.state)) {
      const index = this.state.boxes.findIndex((box) => box.id === bridge.before);
      const status = this.bridgeStatusOf(bridge.before);
      const replacing = model.isReplacement(bridge);
      const line = bridgeLine(status, model.bridgeProblem(this.state, index));
      if (replacing) {
        const region = el('div', 'h3ct-replace-region');
        region.classList.toggle('plays', !!status?.plays);
        region.style.left = percent(Math.max(0, starts[index] - bridge.left) / span);
        region.style.width = percent((bridge.left + bridge.right) / span);
        nodes.push(region);
      }
      const mark = el('button', 'h3ct-bridge-mark');
      mark.type = 'button';
      if (status) mark.classList.add(status.status);
      mark.classList.toggle('problem', line.problem);
      mark.setAttribute('aria-label', `Bridge before clip ${index + 1}`);
      const what = replacing
        ? `replaces ${bridge.left + bridge.right} frames across the cut, keeping the Timeline's time`
        : `${bridge.frames} frames, outside the Timeline's time`;
      mark.title = `Bridge before clip ${index + 1}: ${what}\n${line.text}`;
      mark.style.left = percent(starts[index] / span);
      mark.addEventListener('pointerdown', (event) => event.stopPropagation());
      mark.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this.setTab('box');
        this.bridgeDetails.open = true;
        // From the track, which stays in the page when select() draws new marks.
        this.trackEl.dispatchEvent(new CustomEvent('h3c-show-page', {bubbles: true, detail: {page: 'box'}}));
        this.select(index);
      });
      nodes.push(mark);
    }
    if (this.draft != null) {
      const ghost = el('div', 'h3ct-draft', `${model.seconds(this.draft)} s`);
      ghost.style.left = percent(start / span);
      ghost.style.width = percent(this.draft / span);
      nodes.push(ghost);
    } else if (!this.state.boxes.length) {
      nodes.push(el('span', 'h3ct-empty', 'Start with + Clip or drag here. Use Story in Studio to write prompts.'));
    }
    // Clips' and bridges' listeners use only their place, which their label names.
    replaceChanged(this.trackEl, [...nodes, this.playheads[1]], (node) => node.getAttribute('aria-label'));
    this.renderStack(span);
    this.renderRuler(span);
    this.renderStills(span, stillsWidth);
    // AudioLanes guards typing by state/clip identity, including after its settings root is borrowed.
    this.audioLanes.render(span, laneWidth);
    this.trackEditor.render(span);
    this.trackEditor.decorateAudio();
    if (this.audioLanes.lanes.lastChild !== this.playheads[2]) this.audioLanes.lanes.append(this.playheads[2]);
    this.placePlayhead(span);
    this.dialogue.render();
    this.chain.render();
  }

  // A clip with several videos: a badge with their count and one stripe per video, lit where it is on screen.
  drawStack(item, label, index) {
    const box = this.state.boxes[index], videos = videoLayers.videosOf(this.state, index);
    const badge = el('span', 'h3ct-stack-badge', `▤ ${videos.length}`);
    badge.title = `Clip ${index + 1} holds ${videos.length} videos`;
    label.append(badge);
    const bars = videoLayers.onScreenBars(box, this.played(index));
    const stripes = el('div', 'h3ct-stripes');
    videos.forEach((video, number) => {
      const stripe = el('div', 'h3ct-stripe');
      stripe.title = `${video.label}${bars.some((bar) => bar.id === video.id) ? '' : ' (not on screen)'}`;
      for (const bar of bars.filter((bar) => bar.id === video.id)) {
        const on = el('span', 'on');
        on.style.left = percent(bar.start / box.frames);
        on.style.width = percent((bar.end - bar.start) / box.frames);
        on.style.background = `rgb(${VIDEO_COLORS[number]})`;
        stripe.append(on);
      }
      stripes.append(stripe);
    });
    item.append(stripes);
  }

  played(index) {
    const box = this.state.boxes[index];
    return model.playedFrames(box.frames, box.exact, model.isFresh(this.state, index));
  }

  // The selected clip's videos, one row each inside the clip's own time: the main video's on-screen bars, then each
  // other video's First and Last tiles, heading, bars, Shot guides and the swaps into it. Hidden for one video.
  renderStack(span) {
    const index = this.selected, box = this.state.boxes[index];
    const show = !!box?.layers?.length;
    if (this.stackEl.hidden !== !show) this.stackEl.hidden = !show;
    if (!show) {
      if (this.stackEl.firstChild) this.stackEl.replaceChildren();
      return;
    }
    const start = this.state.boxes.slice(0, index).reduce((sum, item) => sum + item.frames, 0);
    const bars = videoLayers.onScreenBars(box, this.played(index)), status = this.statusOf(box);
    const rows = el('div', 'h3ct-stack-rows');
    rows.style.marginLeft = percent(start / span);
    rows.style.width = percent(box.frames / span);
    videoLayers.videosOf(this.state, index).forEach((video, number) => {
      const row = el('div', `h3ct-stack-row ${video.main ? 'main' : 'layer'}`);
      row.dataset.video = video.id;
      row.setAttribute('aria-label', video.main ? `Clip ${index + 1}, main video` : `Clip ${index + 1}, video ${video.label}`);
      row.classList.toggle('picked', video.id === this.video().id);
      row.addEventListener('click', () => this.pick(video.id));
      if (video.main) row.append(el('b', null, video.label), ' First and Last: marker row ↑');
      else {
        const layer = box.layers[number - 1];
        const take = status?.videos?.find((item) => item.id === video.id);
        row.append(this.edgeTile(layer, video, 'first'), this.edgeTile(layer, video, 'last'), el('span',
          'h3ct-stack-heading', hasTake(take) ? `${video.label} ✓ seed ${layer.seed}` : `${video.label} not rendered`));
        for (const preview of layer.previews ?? []) {
          if (preview.target?.kind !== 'shot' || !preview.guide || !Number.isFinite(preview.frame)) continue;
          const tick = el('span', 'h3ct-shot-tick');
          tick.style.left = percent(preview.frame / box.frames);
          tick.title = `${video.label} Shot ${preview.target.shot} guide at frame ${preview.frame}`;
          row.append(tick);
        }
      }
      for (const bar of bars.filter((item) => item.id === video.id)) {
        const on = el('span', 'h3ct-onscreen');
        on.style.left = percent(bar.start / box.frames);
        on.style.width = percent((bar.end - bar.start) / box.frames);
        on.style.background = `rgb(${VIDEO_COLORS[number]})`;
        row.append(on);
      }
      box.switch.cuts.forEach((cut, n) => { if (cut.to === video.id) row.append(this.swapHandle(box, cut, n)); });
      rows.append(row);
    });
    const blocked = this.addVideoBlocked(index);
    const add = button('+ Video', blocked || `Add a video to clip ${index + 1}`, () => this.addVideo(), 'h3ct-add-video');
    add.disabled = !!blocked || this.readOnly.length > 0;
    const foot = el('div', 'h3ct-stack-add');
    foot.append(add, el('small', null, `copies clip ${index + 1}'s prompt and seed`));
    rows.append(foot);
    replaceChanged(this.stackEl, [el('div', 'h3ct-stack-title', `Clip ${index + 1} videos`), rows],
      (node) => node.className);
    this.stackRows = this.stackEl.lastChild;
  }

  edgeTile(layer, video, kind) {
    const name = kind === 'first' ? 'First' : 'Last';
    const tile = button('', `${video.label} ${name}`, () => {}, `h3ct-still h3ct-edge ${kind}`);
    this.fillStill(tile, layer, {kind}, `${video.label} · ${name}`, this.host.connected().images);
    return tile;
  }

  swapHandle(box, cut, number) {
    const handle = el('div', 'h3ct-swap');
    handle.dataset.cut = String(number);
    handle.style.left = percent(cut.at / box.frames);
    handle.title = 'Drag to move the swap; it snaps to beats like clip edges (Shift drags freely)';
    handle.append(el('span', 'h3ct-swap-chip', `${cut.at} · fade ${box.switch.fade}`));
    handle.addEventListener('pointerdown', (event) => this.swapStart(event, number));
    return handle;
  }

  // Drags swap `cut` of the selected clip; it snaps to a beat within the reach clip edges use.
  swapStart(event, cut) {
    if (event.button !== 0 || this.readOnly.length) return;
    event.preventDefault();
    event.stopPropagation();
    const index = this.selected, box = this.state.boxes[index];
    const rect = this.stackRows.getBoundingClientRect();
    const perPixel = box.frames / (rect.width || 1);
    const start = this.state.boxes.slice(0, index).reduce((sum, item) => sum + item.frames, 0);
    this.capture(event, (move) => {
      let frame = (move.clientX - rect.left) * perPixel;
      const beat = this.audioLanes.snapping && !move.shiftKey ? this.nearestBeat(start + frame, 12 * perPixel) : null;
      if (beat != null) frame = beat - start;
      const before = box.switch.cuts[cut].at;
      videoLayers.setSwap(this.state, index, cut, frame);
      if (box.switch.cuts[cut].at !== before) this.renderTrack();
    }, () => this.commit(), this.stackEl);
  }

  // Why clip `index` can't take another video, or ''.
  addVideoBlocked(index) {
    const box = this.state.boxes[index];
    if (!box) return 'Select a clip first.';
    if ((box.layers?.length ?? 0) >= videoLayers.MAX_VIDEOS - 1) return `A clip holds at most ${videoLayers.MAX_VIDEOS} videos.`;
    const trial = model.parseState(model.serialize(this.state));
    videoLayers.addVideo(trial, index);
    return videoLayers.clampSwitch(trial, index) ? '' : 'This clip is too short for another swap with this fade.';
  }

  // Adds a video to the selected clip. A Continue clip after it must become a Cut first, so that is asked.
  addVideo() {
    const index = this.selected;
    if (this.addVideoBlocked(index) || this.readOnly.length) return;
    const question = videoLayers.continueAfterStack(this.state, index, true);
    if (question) {
      if (!globalThis.confirm?.(question)) return;
      this.state.boxes[index + 1].cut = true;
    }
    this.picked = videoLayers.addVideo(this.state, index);
    this.commit();
  }

  // Off keeps only the main video; the removed videos' prompts come back with Undo.
  toggleVideos(on) {
    if (on) return this.addVideo();
    const box = this.box(), others = box?.layers ?? [];
    if (!others.length) return;
    if (!globalThis.confirm?.(`Remove ${others.length === 1 ? 'the other video' : `the other ${others.length} videos`} of clip ${this.selected + 1} and its switch?`)) return;
    for (const layer of [...others]) videoLayers.removeVideo(this.state, this.selected, layer.id);
    this.picked = null;
    this.commit();
  }

  // Off clears both frames, kept until the switch comes back on; on with nothing kept shows the empty pickers.
  toggleFrames(on) {
    const video = this.video(), key = `frames:${video.id}`;
    this.pins.set(key, on);
    if (on) {
      const kept = this.stash.get(key);
      this.stash.delete(key);
      if (!kept) return this.renderPanel();
      Object.assign(video, kept);
    } else {
      if (video.first || video.last) this.stash.set(key, {first: video.first ?? '', last: video.last ?? ''});
      video.first = '';
      video.last = '';
    }
    this.commit();
  }

  // On inserts time when it can, else a replacement around the cut; off takes the bridge out.
  toggleBridge(on) {
    if (!on) model.removeBridge(this.state, this.selected);
    else {
      const mode = !this.bridges.blocked('insert') ? 'insert'
        : !this.bridges.unavailable() && !this.bridges.blocked('replace') ? 'replace' : null;
      if (!mode) return;
      model.insertBridge(this.state, this.selected, mode);
    }
    this.commit();
  }

  renderBridgeSwitch() {
    const box = this.box(), index = this.selected, fresh = index > 0 && !!box?.cut;
    this.bridgeDetails.hidden = !fresh;
    if (!fresh) return;
    const bridge = model.bridgeOf(this.state, index);
    const insert = this.bridges.blocked('insert');
    const replace = this.bridges.unavailable() || this.bridges.blocked('replace');
    const why = bridge ? '' : insert && replace ? insert : '';
    this.bridgeDetails.set(!!bridge, {disabled: this.readOnly.length > 0 || !!why, title: why,
      state: bridge ? (model.isReplacement(bridge) ? 'Replacing around the cut' : `${bridge.frames} frames inserted`) : why});
  }

  renderFeedback() {
    const text = this.feedbackInput.value.trim();
    this.feedbackSection.set(!!text || this.pins.has('feedback'));
  }

  // The Studio sets how wide the lane draws (zoom, 1 = fit the panel).
  setLaneView({zoom = 1} = {}) {
    if (zoom === this.zoom) return;
    this.zoom = zoom;
    this.laneEl.style.setProperty('--h3ct-zoom', String(zoom));
    this.renderTrack();
  }

  renderRuler(span) {
    const ticks = [];
    const total = span / model.FPS;
    const step = [1, 2, 5, 10, 15, 30, 60, 120].find((s) => total / (this.zoom ?? 1) / s <= 10) ?? 300;
    for (let t = 0; t < total; t += step) {
      const tick = el('span', 'h3ct-tick', `${t}s`);
      tick.style.left = percent((t * model.FPS) / span);
      ticks.push(tick);
    }
    replaceChanged(this.rulerEl, [...ticks, this.playheads[0]], () => 'tick');
  }

  renderPanel() {
    const box = this.box();
    this.card.hide();
    this.panelEl.hidden = !box;
    this.frameImages.renderRecovery();
    this.setTab(this.activeTab);
    if (this.sharedEl.value !== this.state.prompt) this.sharedEl.value = this.state.prompt;
    this.sharedMarks.render();
    this.renderVideoPicker();
    if (!box) return;
    const video = this.video(), layer = this.pickedLayer();
    this.renderCastChips();
    const connected = this.host.connected();
    this.renderPrompt();
    this.renderPlates();
    this.renderReferenceOverview();
    this.renderMemory();
    const frames = connected.images.filter(ref => !ref.refmod);
    fillPicturePicker(this.firstPicker, {value: video.first, refs: frames, label: 'First frame'}, (value) => {
      this.video().first = value;
      this.commit();
    });
    fillPicturePicker(this.lastPicker, {value: video.last, refs: frames, label: 'Last frame'}, (value) => {
      this.video().last = value;
      this.commit();
    });
    this.firstField.hidden = !layer && !model.isFresh(this.state, this.selected);
    if (layer) this.firstNote.hidden = this.lastNote.hidden = true;
    else {
      this.fillEndpointNote(this.firstNote, this.selected, 'first');
      this.fillEndpointNote(this.lastNote, this.selected, 'last');
    }
    const bible = !!this.state.bible, locked = this.readOnly.length > 0, kind = model.joinKind(box);
    const framesKey = `frames:${video.id}`;
    this.frameSettings.set(!!(video.first || video.last) || this.pins.has(framesKey), {disabled: locked,
      state: [video.first && `@${video.first}`, video.last && `@${video.last}`].filter(Boolean).join(' → ')});
    this.cutField.hidden = true;
    this.cutInput.checked = !!box.cut;
    this.sceneField.hidden = !box.cut || bible;
    this.sceneInput.checked = !!box.new_scene;
    this.joinField.hidden = !bible;
    this.joinSelect.value = kind;
    this.joinNote.value = box.join?.note ?? '';
    this.joinSettings.hidden = this.selected === 0;
    this.joinSettings.titleEl.textContent = bible ? 'Transition or cut' : 'Cut';
    this.joinSettings.set(kind !== 'continue', {disabled: locked,
      state: kind === 'continue' ? `Continues clip ${this.selected}` : bible ? JOIN_LABELS[kind] : ''});
    this.refmodFramesInput.checked = !!box.flf_refmods;
    this.refmodSection.set(!!box.flf_refmods, {disabled: locked});
    this.exactInput.checked = !!box.exact;
    this.framesField.hidden = false;
    this.lengthSettings.set(!!box.exact, {disabled: locked,
      state: box.exact ? `${box.frames} frames` : `${model.seconds(box.frames)} s on H3’s frame grid`});
    this.framesInput.max = String(model.limits(model.isFresh(this.state, this.selected), this.host.context(),
      model.maxFrames(this.state)).max);
    this.framesInput.value = String(box.frames);
    this.seedInput.setCustomValidity('');
    this.seedInput.value = video.seed ?? '';
    this.seedMode.value = box.seed_mode ?? 'fixed';
    const randomSeed = box.seed_mode === 'randomize';
    this.seedSettings.set(!randomSeed, {disabled: locked, state: randomSeed ? 'Random each render' : String(video.seed ?? 'auto')});
    const memory = video.memory ?? 'off';
    this.memoryDetails.set(memory !== 'off', {disabled: locked,
      state: {off: 'Off', scene: 'Same scene', selected: 'Selected moments', cast: 'Cast'}[memory] ?? memory});
    this.renderBridgeSwitch();
    this.renderFeedback();
    this.leftButton.disabled = this.selected === 0;
    this.rightButton.disabled = this.selected >= this.state.boxes.length - 1;
    this.renderChips(connected);
    this.renderVideoSettings();
    this.renderPanelInfo();
  }

  // One button per video of the selected clip, and + Video; a clip with one video shows none.
  renderVideoPicker() {
    const box = this.box(), videos = box ? videoLayers.videosOf(this.state, this.selected) : [];
    this.videoPickerEl.hidden = videos.length < 2;
    if (this.videoPickerEl.hidden) {
      this.videoPickerEl.replaceChildren();
      return;
    }
    const current = this.video().id, blocked = this.addVideoBlocked(this.selected);
    const add = button('+ Video', blocked || 'Add another video of this clip’s time', () => this.addVideo(), 'h3ct-add-video');
    add.disabled = !!blocked || this.readOnly.length > 0;
    this.videoPickerEl.replaceChildren(...videos.map((video, index) => {
      const pick = button(video.label, video.main ? 'Edit the main video' : `Edit video ${video.label}`,
        () => this.pick(video.id), 'h3ct-video-pick');
      pick.setAttribute('aria-pressed', String(video.id === current));
      pick.style.borderColor = `rgb(${VIDEO_COLORS[index]})`;
      return pick;
    }), add);
  }

  // Settings for the clip's videos: each video with Remove, and the switch's swap frames, fade and sound.
  renderVideoSettings() {
    const box = this.box(), index = this.selected, videos = videoLayers.videosOf(this.state, index);
    const rows = videos.map((video, order) => {
      const item = video.main ? box : box.layers.find((layer) => layer.id === video.id);
      const state = this.videoStatusOf(box, video.id)?.status;
      const row = el('div', 'h3ct-video-row');
      row.style.borderLeftColor = `rgb(${VIDEO_COLORS[order]})`;
      row.append(el('span', 'h3ct-video-label', video.label),
        el('span', 'h3ct-hint', `First ${item.first ? `@${item.first}` : '—'}`),
        el('span', 'h3ct-hint', `seed ${item.seed ?? 'auto'}`),
        el('span', 'h3ct-hint', this.stale ? '' : {done: '✓ rendered', outdated: '⟳ outdated'}[state] ?? 'not rendered'));
      if (!video.main) row.append(button(`Remove ${video.label}`, 'Remove this video and its swap', () => {
        videoLayers.removeVideo(this.state, index, video.id);
        if (this.picked === video.id) this.picked = null;
        this.commit();
      }));
      return row;
    });
    const blocked = this.addVideoBlocked(index);
    const add = button('+ Video', blocked || 'Add another video of this clip’s time', () => this.addVideo(), 'h3ct-add-video');
    add.disabled = !!blocked || this.readOnly.length > 0;
    const several = videos.length > 1;
    this.videosGroup.set(several, {disabled: this.readOnly.length > 0 || (!several && !!blocked),
      title: several ? 'Turn off to keep only the main video' : blocked || 'Render other videos of this clip’s time and swap between them',
      state: several ? `${videos.length} videos` : ''});
    const notes = [];
    if (videos.length > 1) {
      notes.push('Each video renders the clip’s whole time from its own prompt and seed; the switch picks which one is '
        + 'on screen. Dialogue cues reach every video unless its Dialogue is typed in the prompt.');
      if (this.state.boxes[index + 1]) notes.push(`Clip ${index + 2} starts with a Cut: the clip after several videos `
        + 'can’t continue yet.');
    } else notes.push('Add another video of this clip’s time; the switch then swaps between them.');
    this.videosBody.replaceChildren(...rows, add, ...notes.map((note) => el('p', 'h3ct-hint', note)));
    this.switchGroup.hidden = videos.length < 2;
    if (this.switchGroup.hidden) {
      this.switchBody.replaceChildren();
      return;
    }
    const sw = box.switch, label = (id) => videos.find((video) => video.id === id)?.label ?? id;
    const number = (aria, value, min, max, onChange) => {
      const input = el('input', 'h3ct-number');
      Object.assign(input, {type: 'number', step: '1', min: String(min), max: String(max), value: String(value)});
      input.setAttribute('aria-label', aria);
      input.addEventListener('change', () => { onChange(input.value); this.commit(); });
      return input;
    };
    const played = model.playedFrames(box.frames, box.exact, model.isFresh(this.state, index));
    let screen = box.id;
    const swaps = sw.cuts.map((cut, order) => {
      const from = label(screen);
      screen = cut.to;
      return field(`${from} → ${label(cut.to)} at frame`, number(`Swap ${order + 1} frame`, cut.at, 1, played - 1,
        (value) => videoLayers.setSwap(this.state, index, order, value)),
      el('span', 'h3ct-hint', `${model.seconds(cut.at)} s · or drag its handle on the Timeline`));
    });
    const sound = el('select', 'h3ct-select');
    sound.setAttribute('aria-label', 'Sound');
    sound.append(option('screen', 'The video on screen'), ...videos.map((video) => option(video.id, video.label)));
    sound.value = sw.sound ?? 'screen';
    sound.addEventListener('change', () => { videoLayers.setSound(this.state, index, sound.value); this.commit(); });
    const problems = [...videoLayers.switchFits(this.state, index) ? [] : [videoLayers.SWAPS_DONT_FIT],
      ...model.swapWarnings(this.state, index)];
    this.switchBody.replaceChildren(...swaps,
      field('Fade', number('Fade frames', sw.fade, 0, videoLayers.MAX_FADE,
        (value) => videoLayers.setFade(this.state, index, value)),
      el('span', 'h3ct-hint', `${model.seconds(sw.fade)} s, centred on the swap; 0 is a hard cut`)),
      field('Sound', sound),
      ...problems.map((problem) => el('p', 'h3ct-hint problem h3ct-switch-warning', problem)));
  }

  renderMemory() {
    const root = this.memoryEl;
    root.replaceChildren();
    const box = this.video(), layer = this.pickedLayer();
    if (!box) return;
    const mode = el('select', 'h3ct-select');
    if (!box.memory || box.memory === 'off') return;
    const modes = [['scene', 'Same scene'], ['selected', 'Selected moments']];
    if (this.state.bible || box.memory === 'cast') modes.push(['cast', 'Cast']);
    for (const [value, title] of modes) mode.append(option(value, title));
    mode.value = box.memory;
    mode.addEventListener('change', () => { box.memory = mode.value; this.commit(); });
    mode.setAttribute('aria-label', 'Visual memory mode');
    root.append(field('Mode', mode), el('p', 'h3ct-hint', box.memory === 'cast'
      ? "Cuts also receive the full preceding video for layout and movement, even when character pictures are supplied. When someone speaks on either side of the cut, they remember the moment before it instead, because H3 would copy the earlier lip movement. Cast adds earlier character and place views. A new scene follows its new setting prompt; a clip without a schedule uses Same scene."
      : 'Cuts receive the full preceding video for layout, object appearance and movement. When someone speaks on either side of the cut, they remember the moment before it instead, because H3 would copy the earlier lip movement. Same scene also remembers its establishing view; a new scene follows its new setting prompt. Selected moments add chosen earlier views.'));
    const sources = model.memorySources(layer ? videoLayers.layerView(this.state, this.selected, layer.id) : this.state,
      this.selected);
    const listed = sources.map(source =>
      `Clip ${this.state.boxes.findIndex(item => item.id === source.box) + 1} · ${source.whole ? 'Full video' : model.seconds(source.frame) + ' s'} · ${source.label}`).join(' / ');
    if (box.memory === 'scene' || box.memory === 'cast') {
      root.append(el('p', 'h3ct-hint', listed || (box.memory === 'cast' ? 'Nothing to remember yet.'
        : 'The scene starts here. Its later clips can remember this view.')));
      return;
    }
    if (box.memory !== 'selected') return;
    if (sources.some(source => !(box.memories ?? []).includes(source))) root.append(el('p', 'h3ct-hint', listed));
    for (const [index, memory] of (box.memories ?? []).entries()) {
      const row = el('div', 'h3ct-row');
      const source = el('select', 'h3ct-select');
      source.append(option('', 'Choose earlier clip'));
      this.state.boxes.slice(0, this.selected).forEach((item, i) => source.append(option(item.id, `Clip ${i + 1}`)));
      source.value = memory.box;
      source.addEventListener('change', () => { memory.box = source.value; memory.frame = 0; this.commit(); });
      const seconds = el('input', 'h3ct-number');
      seconds.type = 'number'; seconds.min = '0'; seconds.step = String(1 / model.FPS);
      seconds.value = (memory.frame / model.FPS).toFixed(3);
      seconds.setAttribute('aria-label', 'Remembered time in source clip, seconds');
      seconds.addEventListener('change', () => {
        const frame = Math.round(Number(seconds.value) * model.FPS);
        if (Number.isFinite(frame)) { memory.frame = Math.max(0, frame); this.commit(); }
      });
      const label = el('input', 'h3ct-select');
      label.style.cssText = 'flex:1;min-width:180px';
      label.value = memory.label ?? ''; label.placeholder = 'What to remember, e.g. house exterior';
      label.setAttribute('aria-label', 'Details to remember');
      label.addEventListener('change', () => { memory.label = label.value; this.commit(); });
      row.append(source, field('Time (s)', seconds), label, button('Remove', 'Remove this remembered moment', () => {
        box.memories.splice(index, 1); this.commit();
      }));
      root.append(row);
      const status = this.statusById.get(memory.box);
      if (status?.video) {
        const preview = el('details');
        preview.append(el('summary', '', 'View source moment'));
        const video = el('video');
        video.controls = true; video.muted = true; video.preload = 'none';
        video.style.cssText = 'width:100%;max-height:180px';
        video.src = `${this.host.viewUrl(status.video.file)}#t=${memory.frame / model.FPS}`;
        preview.append(video); root.append(preview);
      }
    }
    const add = button('Remember a moment', 'Add a 5-frame view from an earlier rendered box (maximum 3)', () => {
      box.memories ??= [];
      box.memories.push({box: this.state.boxes[this.selected - 1].id, frame: 0, label: ''});
      this.commit();
    });
    add.disabled = this.selected === 0 || (box.memories?.length ?? 0) >= 3;
    root.append(add, el('p', 'h3ct-hint', 'H3 snaps each moment to a 17-frame boundary and reads 5 frames. Render source clips first.'));
  }

  renderPromptReferences() {
    const box = this.box();
    const names = box ? [box.prompt, this.state.prompt].flatMap(text => model.mentions(text ?? '').map(ref => ref.name)) : [];
    const refs = mentionedReferences(names, this.referenceOptions());
    replaceChanged(this.promptRefsEl, refs.map(ref => referenceChip(ref)));
    this.promptRefsEl.hidden = !refs.length;
  }

  renderReferenceOverview() {
    this.renderPromptReferences();
    const root = this.referenceOverviewEl;
    const box = this.box();
    if (!box) {
      this.overviewKey = null;
      root.replaceChildren();
      return;
    }
    const used = new Set([box.prompt,this.state.prompt].flatMap(text=>model.mentions(text??'').map(ref=>ref.name)));
    const connected = this.host.connected().images.filter(ref=>used.has(ref.name));
    const byName = new Map(connected.map(ref => [ref.name, ref]));
    const sections = promptSections(box.prompt) ?? [];
    const definitions = sections.find(section => section.key === 'subject_definitions')?.fields ?? [];
    const shot = shotFrames(this.state, this.selected, this.host.context()).find(item => item.shot === this.selectedShot);
    let plates = {};
    if (shot) {
      try { plates = model.effectivePlates(this.state, this.selected, box.previews?.find(p => p.shot === shot.shot)?.target_frame ?? shot.frame ?? 0); }
      catch { /* show connected originals if an accepted plate is missing */ }
    }
    const previewFor = name => plates[name]?.image ? this.host.viewUrl(plates[name].image) : byName.get(name)?.preview;
    const thumbnail = (container, name, url) => {
      this.thumbnail(container, url, `@${name}`);
    };

    const subjects = definitions.filter(part => part.label.startsWith('<Subject ') || model.mentions(part.value).some(ref => ref.kind === 'image'));
    // Thumbnails join their cards once they load, so a redrawn overview never equals the one shown: draw it again
    // only when what it shows changes.
    const key = JSON.stringify([subjects.map(part => [part.label, part.value,
      model.mentions(part.value).filter(ref => ref.kind === 'image').map(ref => previewFor(ref.name))]),
      connected.map(ref => [ref.name, ref.title, previewFor(ref.name), !!plates[ref.name]])]);
    if (key === this.overviewKey) return;
    this.overviewKey = key;
    root.replaceChildren();
    if (subjects.length) {
      root.append(el('div', 'h3ct-section-heading', 'Subjects and their images'));
      const grid = el('div', 'h3ct-subject-grid');
      for (const part of subjects) {
        const card = el('div', 'h3ct-subject-card');
        const thumbs = el('div', 'h3ct-subject-thumbs');
        const content = el('div');
        const names = model.mentions(part.value).filter(ref => ref.kind === 'image').map(ref => ref.name);
        if (names.length) for (const name of names) thumbnail(thumbs, name, previewFor(name));
        content.append(el('strong', null, part.label), el('p', null, part.value));
        card.append(thumbs, content);
        grid.append(card);
      }
      root.append(grid);
    }

    root.append(el('div', 'h3ct-section-heading', 'Images mentioned in this clip'));
    const grid = el('div', 'h3ct-linked-images');
    if (!connected.length) grid.append(el('span', 'h3ct-hint', 'No connected images are mentioned in this clip or the shared prompt.'));
    for (const ref of connected) {
      const card = el('div', 'h3ct-linked-card');
      thumbnail(card, ref.name, previewFor(ref.name));
      card.append(el('strong', null, `@${ref.name}`), el('span', null, plates[ref.name] ? `${ref.title || ref.name} · active plate` : ref.title || ref.name));
      grid.append(card);
    }
    root.append(grid);
  }

  renderPrompt() {
    this.card.hide();
    for (const marks of this.sectionMarks) marks.destroy();
    this.sectionMarks = [];
    if(!this.promptForm)this.structureEl.replaceChildren();
    // Keep still controls connected so a refresh cannot cancel a mouse click or blur an edit.
    for(const child of [...this.previewsEl.children]) if(child!==this.frameImages.root) child.remove();
    const shots = shotFrames(this.state, this.selected, this.host.context());
    const selected = shots.find(s => s.shot === this.selectedShot) ?? shots[0];
    this.selectedShot = selected.shot;
    this.frameImages.open(this.box().id, this.frameImages.boxId === this.box().id
      ? this.frameImages.target : {kind:'shot',shot:selected.shot});
    const strip=el('div','h3ct-targets h3ct-filmstrip');
    const images=this.host.connected().images;
    strip.setAttribute('aria-label','Frames in this clip');
    const order=({target,frame})=>target.kind==='first'?-1:target.kind==='last'?Infinity:frame;
    for(const {target,frame} of frameTargets(this.state,this.selected,this.host.context()).sort((a,b)=>order(a)-order(b))) {
      const pick=button('',`${targetLabel(target)}, frame ${frame}`,()=>{
        this.selectedShot=target.shot??1;this.frameImages.open(this.box().id,target);this.renderTrack();this.renderPanel();
      },'h3ct-target');
      pick.dataset.target=target.kind==='shot'?`shot:${target.shot}`:target.kind;
      pick.setAttribute('aria-label',`${targetLabel(target)} image`);
      pick.setAttribute('aria-pressed',String(this.frameImages.target.kind===target.kind&&this.frameImages.target.shot===target.shot));
      this.fillStill(pick,this.box(),target,targetLabel(target),images);
      showImages(pick);
      imageDrop(pick,file=>{pick.click();this.dropGuide(file,target);});
      strip.append(pick);
    }
    this.previewsEl.prepend(strip);
    if(this.frameImages.root.parentNode!==this.previewsEl) this.previewsEl.append(this.frameImages.root);
    this.previewsEl.append(this.shotSplit(selected),this.savedStills(shots));
    const box = this.video();
    const source = box.prompt;
    const sections = promptSections(source);
    const structured = !this.rawPrompt;
    this.sectionsButton.disabled = false;
    this.sectionsButton.title = 'Edit optional subjects, shots and sound fields';
    this.sectionsButton.setAttribute('aria-pressed', String(structured));
    this.rawButton.setAttribute('aria-pressed', String(!structured));
    this.structureEl.hidden = !structured;
    this.promptMarks.root.hidden = structured;
    if (this.promptEl.value !== source) this.promptEl.value = source;
    this.activePromptEl = this.promptEl;
    this.promptMarks.render();
    if (!structured) return;

    this.promptForm ??= new PromptFormPanel(this);
    if(this.promptForm.root.parentNode!==this.structureEl)this.structureEl.append(this.promptForm.root);
    this.promptForm.render();
  }

  async editStory(edit) {
    try {
      if (!this.host.editStory) throw new Error('Connect an H3 Story node.');
      this.editMessage.textContent = 'Starting revision…';
      await this.host.editStory(edit);
      this.editMessage.textContent = 'Revision is running. Progress and Undo are in H3 Story.';
      this.feedbackButton.disabled = true;
    } catch (error) {
      this.editMessage.textContent = error.message;
    }
  }

  renderCastChips() {
    const box = this.box();
    const focused = this.castChipsEl.contains(document.activeElement) ? document.activeElement.dataset.key : null;
    const chips = box ? this.cast.chips(box.id) : [];
    const source = chips.find(chip => chip.dataset.key === 'recompile');
    if (source) {
      const details = el('details', 'h3ct-source');
      details.append(el('summary', null, 'Compile source'), source);
      chips.splice(chips.indexOf(source), 1, details);
    }
    // The chips' listeners hold the clip and Cast view they were drawn from; while those are the same, equal markup keeps them.
    const from = [this.state, this.state.bible, this.cast.view, box];
    if (from.every((item, index) => item === this.castChipsFrom?.[index]) && drawsSame(this.castChipsEl, chips)) return;
    this.castChipsFrom = from;
    this.castChipsEl.replaceChildren(...chips);
    if (focused) this.castChipsEl.querySelector(`[data-key="${focused}"]`)?.focus();
  }

  // A clip converted to FLF2VA + cached RefMods uses its First and Last stills as the real start and end frames of the
  // video, not as guides, so they are named that way.
  runsFlf(index) {
    const box=this.state.boxes[index];
    return !!box?.flf_refmods&&model.describeBox(this.state,index,this.connectedSets(),this.host.context()).mode==='FLF2VA';
  }

  stillName(index,target) {
    return target.kind!=='shot'&&this.runsFlf(index)?`${targetLabel(target)} frame`:targetLabel(target);
  }

  // Under FLF2VA the accepted First/Last still is the Settings frame; say so where the picker reads None.
  fillEndpointNote(note,index,kind) {
    const guide=this.runsFlf(index)?endpointGuide(this.state,index,this.host.context(),kind)?.guide:null;
    note.replaceChildren();
    note.hidden=!guide;
    if(!guide) return;
    const img=el('img');img.src=this.host.viewUrl(guide);img.alt='';img.draggable=false;
    img.style.cssText='height:32px;width:auto;vertical-align:middle;margin-right:6px;border-radius:3px';
    note.append(img,`The accepted ${kind} still is this clip's ${kind} frame. Change it in the Shots tab.`);
  }

  fillStill(mark,box,target,label,images) {
    const index=this.state.boxes.indexOf(box),endpoint=target.kind!=='shot'&&index>=0;
    const saved=box.previews?.find(p=>p.target
      ? (p.target.kind==='shot'&&p.target.shot===1?target.kind==='first':p.target.kind===target.kind&&p.target.shot===target.shot)
      : (p.shot===1?target.kind==='first':target.kind==='shot'&&p.shot===target.shot));
    const inherited=endpoint&&!saved?.guide?endpointGuide(this.state,index,this.host.context(),target.kind):null;
    const guide=saved?.guide??inherited?.guide;
    const reference=!guide&&endpoint?endpointReference(this.state,index,target.kind,images??this.host.connected().images):null;
    const frameMode=endpoint&&this.runsFlf(index);
    if(frameMode) label=label.replace(/(First|Last)$/,'$1 frame');
    const file=guide??reference?.mediaFile??saved?.images?.[0]?.file??saved?.image;
    const url=reference?.preview??(file?this.host.viewUrl(file):null);
    if(url) {
      const img=el('img');img.dataset.src=url;img.alt='';img.draggable=false;mark.append(img);
    } else mark.append(el('span','h3ct-still-empty','+'));
    const caption=el('span','h3ct-still-caption');
    caption.append(el('b',null,label),el('small',null,reference?'In use':guide?(frameMode?'In use':'Guide'):file?'Candidate':'Add'));
    mark.append(caption);mark.classList.toggle('accepted',!!(guide||reference));
    mark.title+=reference?` · frame @${reference.name}`:guide?(frameMode?' · accepted frame':' · accepted guide'):file?' · candidate':' · add image';
  }

  stillsWidth() {
    return this.stillsEl.clientWidth||this.trackEl.clientWidth||800;
  }

  renderStills(span = this.span ?? this.defaultSpan(), width = this.stillsWidth()) {
    const marks=[];
    const images=this.host.connected().images;
    let start=0;
    const clips=this.state.boxes.map((box,index)=>{
      const left=start/span*width+2,right=(start+box.frames)/span*width-2;
      const targets=frameTargets(this.state,index,this.host.context());
      const shots=targets.filter(item=>item.target.kind==='shot').sort((a,b)=>a.movieFrame-b.movieFrame);
      const clip={box,index,start,left,right,targets,shots};start+=box.frames;return clip;
    });
    const gap=Math.min(4,...clips.filter(clip=>clip.shots.length>1).map(clip=>(clip.right-clip.left)/(2*clip.shots.length-1)));
    let shotWidth=Infinity;
    for(const {left,right,shots} of clips) {
      if(!shots.length) continue;
      shotWidth=Math.min(shotWidth,(right-left-gap*(shots.length-1))/shots.length);
      for(let i=1;i<shots.length;i++) {
        const spacing=(shots[i].movieFrame-shots[i-1].movieFrame)/span*width;
        if(spacing>gap) shotWidth=Math.min(shotWidth,spacing-gap);
      }
    }
    shotWidth=Math.max(0,shotWidth);
    for(const {box,index,start,left,right,targets,shots} of clips) {
      const positions=new Map(),widths=new Map();let next=left;
      // Natural layout: each shot spans from its own start to the next shot (or clip end).
      const natural=new Map(),minNatural=24;
      shots.forEach((shot,i)=>{
        const from=Math.max(left,shot.movieFrame/span*width);
        const to=i+1<shots.length?shots[i+1].movieFrame/span*width-gap:right;
        natural.set(shot.target.shot,{left:from,width:to-from});
      });
      const useNatural=shots.length>0&&[...natural.values()].every(n=>n.width>=minNatural);
      if(useNatural) for(const [k,n] of natural) {positions.set(k,n.left);widths.set(k,n.width);}
      else shots.forEach((shot,i)=>{
        const latest=right-shotWidth-(shots.length-i-1)*(shotWidth+gap);
        const position=Math.min(latest,Math.max(next,shot.movieFrame/span*width));
        positions.set(shot.target.shot,position);widths.set(shot.target.shot,shotWidth);next=position+shotWidth+gap;
      });
      for (const {target, movieFrame} of targets) {
        const label = targetLabel(target), name = target.kind === 'shot' ? `shot:${target.shot}` : target.kind;
        const mark = button('', `Clip ${index+1}, ${label}, movie frame ${movieFrame}`, () => {
          if(this.promptDraftsReady?.()===false)return;
          this.selected=index;this.selectedShot=target.shot??1;
          this.frameImages.open(box.id,target);this.setTab('still');this.renderTrack();this.renderPanel();
          this.trackEl.dispatchEvent(new CustomEvent('h3c-show-page',{bubbles:true,detail:{page:'box'}}));
          this.inspect({kind:'clip',box:box.id});
        }, 'h3ct-still');
        mark.dataset.box=box.id;mark.dataset.target=name;mark.dataset.frame=String(movieFrame);
        mark.setAttribute('aria-label',`Clip ${index+1}, ${label} image`);
        if(target.kind==='shot') {
          // Keep timing gaps where possible; late or coincident shots fit inside their clip.
          mark.classList.add('interior');mark.style.left=percent(positions.get(target.shot)/width);
          mark.style.top='76px';mark.style.width=`${widths.get(target.shot)}px`;mark.style.height='66px';
        } else {
          mark.style.left=`calc(${percent((start+(target.kind==='last'?box.frames/2:0))/span)} + 2px)`;
          mark.style.top='4px';mark.style.width=`calc(${percent(box.frames/2/span)} - 4px)`;mark.style.height='66px';
        }
        mark.addEventListener('pointerdown',event=>event.stopPropagation());
        mark.addEventListener('click',event=>event.stopPropagation());
        mark.addEventListener('keydown',event=>{
          if(event.key==='Enter'||event.key===' ') {event.preventDefault();event.stopPropagation();mark.click();}
        });
        mark.classList.toggle('selected',this.frameImages.boxId===box.id
          && this.frameImages.target.kind===target.kind && this.frameImages.target.shot===target.shot);
        this.fillStill(mark,box,target,`${index+1} · ${targetLabel(target)}`,images);
        if(target.kind==='last'&&box.layers?.length) this.markClosing(mark,index);
        imageDrop(mark,file=>{mark.click();this.dropGuide(file,target);});
        marks.push(mark);
      }
    }
    replaceChanged(this.stillsEl,marks,mark=>[mark.getAttribute('aria-label'),mark.dataset.box,mark.dataset.target].join('|'));
    this.stillsEl.style.height=`${clips.some(clip=>clip.shots.length)?146:74}px`;
    this.stillsEl.hidden=!this.state.boxes.length;
  }

  // The main video's Last still guides its generation, but another video can be on screen when the clip ends.
  markClosing(mark, index) {
    const closing = videoLayers.closingVideo(this.state.boxes[index], this.played(index));
    const video = videoLayers.videosOf(this.state, index).find((item) => item.id === closing);
    if (!video || video.main) return;
    const small = mark.lastChild.lastChild; // fillStill ends the mark with its caption, and that with its status
    setText(small, `under ${video.label}`);
    small.classList.add('under');
    mark.title += ` · ${video.label} is on screen at the end of the clip`;
  }

  renderPlates() {
    this.platesEl.replaceChildren();
    const box = this.box();
    for (const change of box.plate_changes ?? []) {
      const row = el('div', 'h3ct-row', `@${change.slot} · from frame ${change.frame} · ${change.revision ? 'modified plate' : 'original'}`);
      row.append(button('Remove change', 'Remove this appearance boundary; use the preceding plate', () => {
        box.plate_changes = box.plate_changes.filter(c => c !== change); this.commit();
      }));
      this.platesEl.append(row);
    }
    const shot = shotFrames(this.state, this.selected, this.host.context()).find(s => s.shot === this.selectedShot);
    const frame = box.previews?.find(p => p.shot === shot?.shot)?.target_frame ?? shot?.frame;
    let active = {};
    try { if (Number.isInteger(frame)) active = model.effectivePlates(this.state, this.selected, frame); }
    catch (error) { this.platesEl.append(el('p', 'h3ct-hint problem', error.message)); }
    for (const ref of this.host.connected().images) {
      const used = active[ref.name];
      if (!used) continue;
      const card = el('div', 'h3ct-plate'), images = el('div', 'h3ct-plate-images');
      const figure = el('figure'), link = el('a'), img = el('img');
      link.href = img.src = this.host.viewUrl(used.image); link.target = '_blank'; link.rel = 'noopener';
      img.alt = `Plate in use for @${ref.name}`;
      link.append(img); figure.append(link, el('figcaption', null, `In use · ${used.id.slice(0, 12)}`)); images.append(figure);
      card.append(el('strong', null, `${ref.title || ref.name} · @${ref.name}`), images);
      this.platesEl.append(card);
    }
    this.platesDetails.hidden = !this.platesEl.children.length;
  }

  shotSplit(shot) {
    const row = el('div', 'h3ct-row');
    if (shot.shot === shotFrames(this.state, this.selected, this.host.context())[0].shot) return row;
    const split = button(`Split before Shot ${shot.shot}`, '', () => {
      if(this.promptDraftsReady?.()===false)return;
      try {
        const timing = splitBox(this.state, this.selected, shot.shot, this.host.context());
        for (const changed of this.state.boxes.slice(this.selected)) this.statusById.delete(changed.id);
        if (timing.left) this.selected++;
        this.commit();
        this.inspectClip();
      } catch (error) {
        row.append(el('span', 'h3ct-hint problem', error.message));
      }
    });
    try {
      const timing = splitTiming(this.state, this.selected, shot.shot, this.host.context());
      split.title = (timing.left
        ? `Make two clips adding ${(timing.left / model.FPS).toFixed(2)} s and ${(timing.right / model.FPS).toFixed(2)} s. `
        : `Start this clip at Shot ${shot.shot} as a fresh ${(timing.right / model.FPS).toFixed(2)} s clip. The replayed opening is already in the previous clip. `)
        + (timing.added ? `Adds ${(timing.added / model.FPS).toFixed(2)} s for H3 frame alignment, preserving performance time. ` : '')
        + 'Each keeps its required references.';
    } catch (error) {
      split.disabled = true;
      split.title = error.message;
    }
    row.append(split);
    return row;
  }

  savedStills(shots) {
    const box = this.box();
    const list = el('div', 'h3ct-saved-guides');
    for (const saved of box.previews ?? []) {
      const row = el('div', 'h3ct-saved-still'), thumb = el('div', 'h3ct-saved-thumb'), body = el('div', 'h3ct-saved-body');
      const controls = el('div', 'h3ct-saved-controls');
      const image = saved.guide ?? saved.image ?? saved.images?.[0]?.file;
      if (image) {
        const img = el('img');
        img.src = this.host.viewUrl(image);
        img.alt = `Saved still for clip ${this.selected + 1}, ${saved.target ? targetLabel(saved.target) : 'shot '+saved.shot}`;
        thumb.append(img);
      }
      row.append(thumb, body);
      const active = saved.target ? frameTargets(this.state,this.selected,this.host.context())
        .some(item=>item.target.kind===saved.target.kind&&item.target.shot===saved.target.shot) : shots.some(s=>s.shot===saved.shot);
      // An untargeted guide renders at its saved frame whether or not its shot still exists.
      const free = !saved.target && saved.guide && (saved.shot >= FREE_GUIDE || !active);
      const label = free ? 'Frame guide' : saved.target ? targetLabel(saved.target) : `Shot ${saved.shot}`;
      const where = active || free ? label : `Removed ${label}`;
      // A removed marker's guide is not rendered; an untargeted guide keeps its saved frame.
      body.append(el('strong', null, where));
      if (!saved.guide) body.append(el('span', 'h3ct-hint', 'Saved still, not a guide'));
      else if (saved.target && !active) body.append(el('span', 'h3ct-hint', 'Unused: its Shot marker was removed. Set a frame to use it again.'));
      body.append(controls);
      const managed = saved.target && active; // The marker panel has separate guide and candidate controls.
      if (managed && !(saved.guide && saved.target.kind === 'shot')) continue;
      if (saved.guide) {
        const frame = this.guideFrameInput(saved.frame, 'Move this guide to another frame of the clip');
        frame.addEventListener('change', async () => {
          if (!await this.placeGuide(body, Number(frame.value), {saved, managed})) frame.value = String(saved.frame);
        });
        controls.append(field('Frame', frame));
      }
      if (!managed) controls.append(button('Remove', saved.guide ? 'Stop guiding this frame and remove the saved still' : 'Remove this saved still', () => {
        this.host.undoStep?.();
        box.previews = box.previews.filter((p) => p !== saved);
        this.commit();
        this.host.undoStep?.();
      }));
      list.append(row);
    }
    const add = el('div', 'h3ct-guide-add'), controls = el('div', 'h3ct-saved-controls');
    const frame = this.guideFrameInput(Math.floor(this.lastGuideFrame() / 2), 'The clip frame the new guide steers');
    frame.setAttribute('aria-label', 'Frame to guide');
    const upload = (file) => this.placeGuide(add, Number(frame.value), {file});
    controls.append(el('span', 'h3ct-hint', 'Frame'), frame, decorateIcon(button('', '', () => {
        const input = el('input'); input.type = 'file'; input.accept = 'image/*';
        input.addEventListener('change', () => { if (input.files[0]) upload(input.files[0]); });
        input.click();
      }), 'upload', 'Upload guide…', {text: true}));
    controls.lastChild.title = 'Upload a picture that guides this frame without adding a shot';
    add.append(el('strong', null, 'Guide another frame'), controls,
      el('span', 'h3ct-hint', `Or drop an image here. Frames 0–${this.lastGuideFrame()}; the prompt doesn't change.`));
    imageDrop(add, upload);
    list.append(add);
    return list;
  }

  lastGuideFrame() {
    return this.box().frames - (model.isFresh(this.state, this.selected) ? 1 : 0);
  }

  guideFrameInput(value, title) {
    const input = el('input', 'h3ct-number');
    input.type = 'number'; input.min = '0'; input.max = String(this.lastGuideFrame()); input.step = '1';
    input.value = String(value); input.title = title;
    return input;
  }

  // Saves a guide at `frame` as an untargeted preview, which the renderer reads at its saved frame. `saved` moves an
  // existing guide (a marker's guide leaves the marker, which keeps its candidates); `file` uploads a new one.
  async placeGuide(row, frame, {saved, managed, file}) {
    const boxId = this.box().id;
    // Checked before an upload and again after it, since the Timeline can change while the file uploads.
    const check = () => {
      const index = this.state.boxes.findIndex(item => item.id === boxId);
      if (index < 0) throw new Error('The clip was removed.');
      const box = this.state.boxes[index], last = box.frames - (model.isFresh(this.state, index) ? 1 : 0);
      if (!Number.isInteger(frame) || frame < 0 || frame > last) throw new Error(`Choose a frame from 0 to ${last}.`);
      const others = structuredClone(this.state);
      others.boxes[index].previews = (box.previews ?? []).filter(item => item !== saved);
      if (acceptedGuideFrames(others, index, this.host.context()).includes(frame)) throw new Error(`Frame ${frame} already has a guide.`);
      return box;
    };
    try {
      check();
      const guide = file ? await this.host.importGuide(file) : saved.guide;
      const box = check();
      this.host.undoStep?.();
      const shot = Math.max(FREE_GUIDE - 1, ...(box.previews ?? []).filter(item => !item.target).map(item => item.shot)) + 1;
      box.previews ??= [];
      if (saved && !managed) { delete saved.target; Object.assign(saved, {shot, frame}); }
      else { if (saved) delete saved.guide; box.previews.push({shot, frame, guide}); }
      if (box.flf_refmods) adoptEndpointGuides(this.state, this.state.boxes.indexOf(box), this.host.context());
      this.commit();
      this.host.undoStep?.();
      return true;
    } catch (error) {
      row.append(el('span', 'h3ct-hint problem', error.message));
      return false;
    }
  }

  renderPanelInfo() {
    const box = this.box();
    if (!box) return;
    const context = this.host.context();
    setText(this.titleEl, `Clip ${this.selected + 1} · ${model.lengthLabel(this.state, this.selected, context)}`);
    this.clipActions.setAttribute('aria-label',`Clip ${this.selected+1} actions`);
    const layer = this.pickedLayer(), label = this.pickedLabel();
    const info = this.pickedInfo(this.connectedSets(), context);
    const spoken = this.stale || layer ? '' : this.statusOf(box)?.dialogue_problem;
    const blocking = [...info.problems, ...(spoken ? [`${spoken.charAt(0).toUpperCase()}${spoken.slice(1)}.`] : [])];
    setText(this.promptProblemEl, [...blocking, ...info.warnings].join(' '));
    this.promptProblemEl.hidden = !blocking.length && !info.warnings.length;
    this.dialogueField.hidden = !this.state.dialogue?.cues?.length;
    this.dialogueSelect.value = this.video().dialogue === 'manual' ? 'manual' : 'cues';
    setIconLabel(this.boxRenderButton,this.generateLabel());
    this.boxRenderButton.title = layer ? `Render only video ${label} of this clip, keeping the clip’s other videos`
      : 'Render only this clip using its seed mode, keeping its saved prompt and neighboring videos';
    setText(this.layerShotsNote, layer ? `Shot images for video ${label} come in a later version; its First and Last `
      + 'frames are in Settings.' : '');
    setText(this.layerTakesNote, layer ? `Takes of video ${label} aren’t listed yet: each Generate keeps the one before `
      + 'in the takes folder.' : '');
    this.layerShotsNote.hidden = this.layerTakesNote.hidden = !layer;
    this.clipShotsEl.hidden = this.clipTakesEl.hidden = !!layer;
    this.boxRenderButton.disabled = this.host.hasVideo?.()===false || this.queuing || blocking.length > 0
      || !this.seedInput.validity.valid || this.readOnly.length > 0;
    const tags = info.tags.map((item) => `${item.tag} = ${item.name}`).join(', ');
    const guides = info.guides.map((item) => ` · ${item.name} guides the ${item.frame} frame`).join('');
    const problems = info.problems.length ? ` · ${info.problems.join(' ')}` : '';
    const reason = this.stale ? null : this.videoStatusOf(box, this.video().id)?.reason;
    const mode = box.flf_refmods && info.mode === 'FLF2VA' ? 'FLF2VA + RefMods' : info.mode;
    const carry = !info.fresh ? ` · ${this.host.context()} carried frames` : '';
    setText(this.modeEl, `${layer ? `Video ${label} runs` : 'Runs'} as ${mode}${carry}${tags ? `: ${tags}` : ''}${guides}${problems}${reason ? ` · Renders again: ${reason}` : ''}`);
    this.modeEl.classList.toggle('problem', info.problems.length > 0);
    const conversion = !layer && info.mode === 'REF2VA' ? model.flfConversion(this.state, this.selected, this.connectedSets(), context) : null;
    this.convertRow.hidden = !conversion;
    if (conversion) {
      this.convertButton.disabled = !conversion.ok;
      this.convertButton.title = conversion.ok ? 'Turn on FLF2VA + cached RefMods: First/Last frames become start and end frames, '
        + 'mentioned images become cached RefMods, and audio stays an audio reference. Needs FLF2VA video model weights.' : conversion.reason;
      setText(this.convertHint, conversion.ok ? 'First/Last become start and end frames; images become cached RefMods; audio stays.' : conversion.reason);
      this.convertHint.classList.toggle('problem', !conversion.ok);
    }
    this.effectivePromptEl.hidden = !this.state.timed_text || !!layer;
    const status = this.stale ? null : this.statusOf(box);
    const pre = el('pre', 'h3ct-hint'); pre.style.whiteSpace = 'pre-wrap';
    pre.textContent = status?.effective_prompt != null
      ? `${status.effective_prompt}\n\nText window:\n${JSON.stringify(status.text_window, null, 2)}`
      : status?.text_note ?? 'Waiting for current render settings and status.';
    replaceChanged(this.effectivePromptEl, [el('summary', null, 'Effective H3 prompt and text window'), pre]);
    this.checks.render();
    this.bridges.render();
    this.renderBridgeSwitch();
    this.takes.render();
    this.syncTakesEmpty();
  }

  renderChips(connected) {
    this.chipsEl.textContent = '';
    const refs = [...connected.images, ...connected.audios, ...(connected.videos ?? []), ...(connected.video_audios ?? [])];
    if (!refs.length) {
      this.chipsEl.append(el('span', 'h3ct-hint', 'Connect images, videos, paired video audio or standalone audio. Mention @image1, @video1, @video_audio1 or @audio1.'));
      return;
    }
    this.chipsEl.append(el('span', 'h3ct-label', 'References'));
    for (const ref of refs) {
      this.chipsEl.append(referenceChip(ref, {onClick: () => this.insert(`@${ref.name}`),
        title: ref.title ? `${ref.title}: insert at the cursor` : 'Insert at the cursor'}));
    }
  }
}
