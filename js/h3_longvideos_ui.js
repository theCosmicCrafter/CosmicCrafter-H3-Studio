import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

/**
 * MiniMax-H3 LongVideos Professional Video Editing Studio Interface
 * - Exactly 4 Inputs: model, clip, vae, audio_vae (100% wire-clean exterior)
 * - Exactly 3 Outputs: images, audio, fps (the complete video delivery tri-pack)
 * - Automatic Workflow Sanitizer: Auto-prunes stale slots & repairs corrupted NaN values
 * - Direct Drag-and-Drop Image Wells on Timeline & Reference Tray (<Picture 1>..<Picture 4>)
 * - 1-Click File Browser Fallback on all Drop Wells
 * - Live Canvas Letterboxed Image Thumbnails with [X] Clear
 * - Interactive Shot Sequence Track with Drag Reordering & Quick Duration (+/- 0.5s)
 * - 1-Click [+ ADD BEAT] and per-shot [X] Delete
 * - Bi-directional Real-Time Script Synchronization
 * - 100% Pure ASCII Typography (Zero Emojis)
 */

const TARGET_NODES = new Set(["H3LongVideoStudio", "H3LongVideos", "H3_Promptor", "H3LongVideosFL2VA", "H3LongVideosV1", "H3LongVideosREF2VA"]);

const TABS = [
    { id: "presets", label: "PRESETS" },
    { id: "core", label: "CORE" },
    { id: "directing", label: "DIRECTING" },
    { id: "audio", label: "AUDIO" },
    { id: "guards", label: "GUARDS" },
    { id: "overlays", label: "OVERLAYS" },
    { id: "advanced", label: "ADVANCED" },
    { id: "all", label: "ALL" }
];

const PRESETS = [
    "Cinematic Master (25 Steps, 1.00MP Native)",
    "Quality Base H3 (20 Steps, 1.00MP)",
    "Ultra-Detailed 4K Master (25 Steps + Upscale)",
    "Action & Kinetic Dynamics (25 Steps)",
    "Turbo LoRA Studio (8 Steps, 0.83MP)",
    "Low VRAM / Fast Draft (15 Steps, 0.65MP, Tiled)",
    "Custom (Manual)"
];

const WIDGET_CATEGORIES = {
    prompt: "core",
    resolution: "core",
    megapixels: "core",
    steps: "core",
    cfg: "core",
    seed: "core",
    sampler_name: "core",
    scheduler: "core",

    shot_seconds: "directing",
    per_beat_length: "directing",
    beat_split: "directing",
    character_memory: "directing",
    anchor_override: "directing",
    ref_mode: "directing",
    ref_noise_aug: "directing",
    ref_image_size: "directing",
    handoff_offset: "directing",
    vary_seed_per_shot: "directing",

    auto_soundscape: "audio",
    global_soundscape: "audio",
    non_diegetic_music: "audio",
    auto_silence_nonspeech: "audio",
    allow_nonspeech_vocals: "audio",
    mute_nonspeech_audio: "audio",
    mute_fade_ms: "audio",

    subject_count_guard: "guards",
    anatomy_guard: "guards",
    motion_guard: "guards",
    contact_guard: "guards",
    solidity_guard: "guards",
    auto_wardrobe: "guards",
    auto_props: "guards",
    prevent_nudity: "guards",
    exposed_terms: "guards",
    lock_restraints: "guards",

    upscale: "overlays",
    upscale_model: "overlays",
    upscale_target_short_edge: "overlays",
    upscale_batch: "overlays",
    watermark_text: "overlays",
    watermark_position: "overlays",
    watermark_size: "overlays",
    watermark_opacity: "overlays",
    watermark_margin: "overlays",
    intro_text: "overlays",
    intro_position: "overlays",
    intro_seconds: "overlays",
    intro_fade: "overlays",
    intro_size: "overlays",
    overlay_font: "overlays",
    overlay_stroke: "overlays",

    plan_only: "advanced",
    fps: "advanced",
    apply_model_sampling: "advanced",
    shift_video: "advanced",
    shift_audio: "advanced",
    trim_seam: "advanced",
    allow_oversize_shots: "advanced",
    allow_res_backoff: "advanced",
    vram_headroom_gb: "advanced",
    cleanup_between_shots: "advanced",
    decode_tile_frames: "advanced",
    decode_tile_size: "advanced",
    config_preset: "presets",
    first_frame_path: "core",
    ref_paths: "core"
};

function safeSetDirty(node) {
    try { node?.setDirtyCanvas?.(true, true); } catch (_) {}
    try { node?.graph?.setDirtyCanvas?.(true, true); } catch (_) {}
    try { app?.graph?.setDirtyCanvas?.(true, true); } catch (_) {}
    try { app?.canvas?.setDirty?.(true, true); } catch (_) {}
}

/**
 * Prunes obsolete slots and repairs corrupted widget values loaded from old workflow files
 */
const VALID_RATIOS = ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "9:21"];

function repairAndEnforceWidgetTypes(node) {
    if (!node || !Array.isArray(node.widgets)) return;

    for (const w of node.widgets) {
        if (!w || !w.name) continue;

        if (w.name === "resolution") {
            w.type = "combo";
            w._h3_origType = "combo";
            if (!w.options) w.options = {};
            w.options.values = [...VALID_RATIOS];

            // Validate and repair value
            if (typeof w.value !== "string" || !VALID_RATIOS.includes(w.value)) {
                let resolved = null;
                if (typeof w.value === "string") {
                    resolved = VALID_RATIOS.find(r => w.value.startsWith(r) || r.startsWith(w.value));
                } else if (typeof w.value === "number") {
                    if (w.value < 0.7) resolved = "9:16";
                    else if (w.value < 0.95) resolved = "3:4";
                    else if (w.value < 1.15) resolved = "1:1";
                    else if (w.value < 1.5) resolved = "4:3";
                    else if (w.value < 2.0) resolved = "16:9";
                    else resolved = "21:9";
                }
                w.value = resolved || "16:9";
            }

            if (w.inputEl && w.inputEl.type === "number") {
                w.inputEl.type = "text";
                w.inputEl.value = w.value;
            }
        } else if (w.name === "sampler_name") {
            w.type = "combo";
            w._h3_origType = "combo";
            if (typeof w.value !== "string" || !w.value || w.value === "simple") {
                w.value = "res_multistep";
            }
        } else if (w.name === "scheduler") {
            w.type = "combo";
            w._h3_origType = "combo";
            if (typeof w.value !== "string" || !w.value || typeof w.value === "number") {
                w.value = "simple";
            }
        } else if (w.name === "cfg") {
            w.type = "number";
            w._h3_origType = "number";
            if (typeof w.value !== "number" || isNaN(w.value) || w.value < 0.0 || w.value > 30.0) {
                w.value = 1.0;
            }
        } else if (w.name === "megapixels") {
            w.type = "number";
            w._h3_origType = "number";
            if (typeof w.value !== "number" || isNaN(w.value) || w.value < 0.1 || w.value > 4.0) {
                w.value = 1.0;
            }
        } else if (w.name === "steps") {
            w.type = "number";
            w._h3_origType = "number";
            if (typeof w.value !== "number" || isNaN(w.value) || w.value < 1 || w.value > 200) {
                w.value = 25;
            }
        } else if (w.name === "seed") {
            w.type = "number";
            w._h3_origType = "number";
            if (typeof w.value !== "number" || isNaN(w.value)) {
                w.value = 0;
            }
        }
    }
}

function sanitizeNodeSlots(node) {
    if (!node) return;

    // Prune ONLY the explicitly obsolete exterior conditioning inputs
    const OBSOLETE_SLOTS = new Set([
        "first_frame", "ref_images",
        "ref_image_1", "ref_image_2", "ref_image_3", "ref_image_4",
        "exposed_terms"
    ]);

    if (Array.isArray(node.inputs)) {
        for (let i = node.inputs.length - 1; i >= 0; i--) {
            const inp = node.inputs[i];
            if (OBSOLETE_SLOTS.has(inp.name)) {
                node.removeInput(i);
            }
        }
    }

    // Prune obsolete output slots to exactly 3
    const expectedOutputs = ["images", "audio", "fps"];
    if (Array.isArray(node.outputs)) {
        for (let i = node.outputs.length - 1; i >= 0; i--) {
            const out = node.outputs[i];
            if (!expectedOutputs.includes(out.name) || i >= 3) {
                node.removeOutput(i);
            }
        }
        if (node.outputs[0]) { node.outputs[0].name = "images"; node.outputs[0].type = "IMAGE"; }
        if (node.outputs[1]) { node.outputs[1].name = "audio"; node.outputs[1].type = "AUDIO"; }
        if (node.outputs[2]) { node.outputs[2].name = "fps"; node.outputs[2].type = "FLOAT"; }
    }

    repairAndEnforceWidgetTypes(node);
}

const _IMAGE_CACHE = new Map();
function getCachedImage(filename) {
    if (!filename) return null;
    if (_IMAGE_CACHE.has(filename)) return _IMAGE_CACHE.get(filename);
    const img = new Image();
    img.src = api.apiURL(`/view?filename=${encodeURIComponent(filename)}&type=input`);
    _IMAGE_CACHE.set(filename, img);
    return img;
}

async function uploadImageFile(file) {
    try {
        const body = new FormData();
        body.append("image", file);
        body.append("overwrite", "true");
        const resp = await api.fetchApi("/upload/image", { method: "POST", body });
        if (resp.status === 200) {
            const data = await resp.json();
            return data.name;
        }
    } catch (e) {
        console.error("[MiniMax-H3] Upload failed:", e);
    }
    return null;
}

function promptForLocalImage(onLoaded) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/webp,image/jpg";
    input.onchange = async (e) => {
        const file = e.target.files?.[0];
        if (file) {
            const name = await uploadImageFile(file);
            if (name) onLoaded(name);
        }
    };
    input.click();
}

function drawLetterboxedThumbnail(ctx, img, x, y, w, h) {
    if (!img || !img.complete || img.naturalWidth === 0) {
        ctx.fillStyle = "#1e1e2c";
        ctx.fillRect(x, y, w, h);
        return;
    }
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;
    const scale = Math.min(w / iw, h / ih);
    const dw = iw * scale;
    const dh = ih * scale;
    const dx = x + (w - dw) / 2;
    const dy = y + (h - dh) / 2;
    ctx.drawImage(img, dx, dy, dw, dh);
}

function getHeaderMetrics(node) {
    // 4 inputs on left (y: 30, 50, 70, 90), 3 outputs on right (y: 30, 50, 70)
    // Connection bay completes cleanly at y = 104
    const slotAreaBottom = 104;
    const headerStartY = 112;

    const tabY = headerStartY;
    const tabH = 26;

    const modeY = tabY + tabH + 6;
    const modeH = 24;

    const presetY = modeY + modeH + 6;
    const presetH = 24;

    const refTrayY = presetY + presetH + 6;
    const refTrayH = 58;

    const ribbonY = refTrayY + refTrayH + 6;
    const ribbonH = 88;

    const totalHeaderBottom = node?._h3_show_timeline ? (ribbonY + ribbonH + 8) : (presetY + presetH + 8);

    return {
        slotAreaBottom,
        headerStartY,
        tabY, tabH,
        modeY, modeH,
        presetY, presetH,
        refTrayY, refTrayH,
        ribbonY, ribbonH,
        totalHeaderBottom
    };
}

function parsePromptBeats(promptText, defaultSeconds = 5.0) {
    if (!promptText || typeof promptText !== "string") return { paragraphs: [], shots: [] };
    const rawParas = promptText.split(/\n\s*\n/).map(p => p.trim()).filter(p => p.length > 0);
    const shots = [];

    for (let i = 0; i < rawParas.length; i++) {
        const p = rawParas[i];
        const mSec = p.match(/\b(?:seconds|duration)\s*:\s*([0-9.]+)/i);
        const sec = mSec ? parseFloat(mSec[1]) : defaultSeconds;
        const frames = Math.round(sec * 24);

        const hasDialogue = /"[^"]+"|\xab[^\xbb]+\xbb|<d>[^<]+<\/d>/i.test(p);
        const hasWardrobe = /\bwardrobe\s*:/i.test(p);
        const hasMotion = /\b(walks|runs|turns|moves|jumps|struggles|dances|fights|steps|opens|stops|glances|whispers)\b/i.test(p);
        const isAnchor = (i === 0);

        const cleanLines = p.split("\n").filter(l => !/^\s*(?:seconds|duration|wardrobe):/i.test(l));
        const snippet = cleanLines.join(" ").substring(0, 32);

        shots.push({
            index: i,
            isAnchor,
            seconds: sec,
            frames,
            hasDialogue,
            hasWardrobe,
            hasMotion,
            snippet,
            text: p
        });
    }

    return { paragraphs: rawParas, shots };
}

function updatePromptShotDuration(promptWidget, shotIndex, delta) {
    if (!promptWidget || !promptWidget.value) return;
    const { paragraphs, shots } = parsePromptBeats(promptWidget.value);
    if (!shots[shotIndex]) return;

    const oldSec = shots[shotIndex].seconds;
    const newSec = Math.max(1.0, parseFloat((oldSec + delta).toFixed(1)));
    let para = paragraphs[shotIndex];

    if (/\b(?:seconds|duration)\s*:\s*([0-9.]+)/i.test(para)) {
        para = para.replace(/\b((?:seconds|duration)\s*:\s*)([0-9.]+)/i, `$1${newSec.toFixed(1)}`);
    } else {
        para = para.trim() + `\nseconds: ${newSec.toFixed(1)}`;
    }

    paragraphs[shotIndex] = para;
    promptWidget.value = paragraphs.join("\n\n");
    if (promptWidget.inputEl) promptWidget.inputEl.value = promptWidget.value;
    if (promptWidget.callback) promptWidget.callback(promptWidget.value);
}

function reorderPromptBeats(promptWidget, fromIndex, toIndex) {
    if (!promptWidget || !promptWidget.value) return;
    const { paragraphs } = parsePromptBeats(promptWidget.value);
    if (fromIndex === 0 || toIndex === 0) return;
    if (fromIndex < 0 || fromIndex >= paragraphs.length || toIndex < 0 || toIndex >= paragraphs.length) return;

    const item = paragraphs.splice(fromIndex, 1)[0];
    paragraphs.splice(toIndex, 0, item);

    promptWidget.value = paragraphs.join("\n\n");
    if (promptWidget.inputEl) promptWidget.inputEl.value = promptWidget.value;
    if (promptWidget.callback) promptWidget.callback(promptWidget.value);
}

function addNewBeat(promptWidget) {
    if (!promptWidget) return;
    const current = (promptWidget.value || "").trim();
    const newBeatText = `Shot description of the new scene beat.\nseconds: 5.0`;
    promptWidget.value = current ? `${current}\n\n${newBeatText}` : newBeatText;
    if (promptWidget.inputEl) promptWidget.inputEl.value = promptWidget.value;
    if (promptWidget.callback) promptWidget.callback(promptWidget.value);
}

function deleteBeat(promptWidget, shotIndex) {
    if (!promptWidget || !promptWidget.value) return;
    const { paragraphs } = parsePromptBeats(promptWidget.value);
    if (shotIndex === 0) return;
    if (shotIndex < 0 || shotIndex >= paragraphs.length) return;
    paragraphs.splice(shotIndex, 1);
    promptWidget.value = paragraphs.join("\n\n");
    if (promptWidget.inputEl) promptWidget.inputEl.value = promptWidget.value;
    if (promptWidget.callback) promptWidget.callback(promptWidget.value);
}

function applyPreset(node, presetName) {
    const cpW = node.widgets?.find(w => w.name === "config_preset");
    if (cpW) cpW.value = presetName;

    const stepsW = node.widgets?.find(w => w.name === "steps");
    const mpW = node.widgets?.find(w => w.name === "megapixels");
    const cfgW = node.widgets?.find(w => w.name === "cfg");
    const samplerW = node.widgets?.find(w => w.name === "sampler_name");
    const schedW = node.widgets?.find(w => w.name === "scheduler");
    const shiftVW = node.widgets?.find(w => w.name === "shift_video");
    const shiftAW = node.widgets?.find(w => w.name === "shift_audio");
    const motionW = node.widgets?.find(w => w.name === "motion_guard");
    const contactW = node.widgets?.find(w => w.name === "contact_guard");
    const solidW = node.widgets?.find(w => w.name === "solidity_guard");
    const anatW = node.widgets?.find(w => w.name === "anatomy_guard");
    const subCountW = node.widgets?.find(w => w.name === "subject_count_guard");
    const tileF = node.widgets?.find(w => w.name === "decode_tile_frames");
    const tileS = node.widgets?.find(w => w.name === "decode_tile_size");
    const upscaleW = node.widgets?.find(w => w.name === "upscale");
    const upShortW = node.widgets?.find(w => w.name === "upscale_target_short_edge");

    if (presetName.includes("Cinematic Master")) {
        if (stepsW) stepsW.value = 25;
        if (mpW) mpW.value = 1.0;
        if (cfgW) cfgW.value = 1.0;
        if (samplerW) samplerW.value = "res_multistep";
        if (schedW) schedW.value = "simple";
        if (shiftVW) shiftVW.value = 12.0;
        if (shiftAW) shiftAW.value = 3.0;
        if (motionW) motionW.value = "auto";
        if (contactW) contactW.value = "auto";
        if (solidW) solidW.value = "auto";
        if (anatW) anatW.value = "auto";
        if (subCountW) subCountW.value = "auto";
        if (tileF) tileF.value = 0;
        if (tileS) tileS.value = 0;
        if (upscaleW) upscaleW.value = "off";
    } else if (presetName.includes("Quality Base H3")) {
        if (stepsW) stepsW.value = 20;
        if (mpW) mpW.value = 1.0;
        if (cfgW) cfgW.value = 1.0;
        if (samplerW) samplerW.value = "res_multistep";
        if (schedW) schedW.value = "simple";
        if (shiftVW) shiftVW.value = 12.0;
        if (shiftAW) shiftAW.value = 3.0;
    } else if (presetName.includes("Ultra-Detailed 4K Master")) {
        if (stepsW) stepsW.value = 25;
        if (mpW) mpW.value = 1.0;
        if (cfgW) cfgW.value = 1.0;
        if (samplerW) samplerW.value = "res_multistep";
        if (schedW) schedW.value = "simple";
        if (shiftVW) shiftVW.value = 12.0;
        if (shiftAW) shiftAW.value = 3.0;
        if (upscaleW) upscaleW.value = "model";
        if (upShortW) upShortW.value = 1440;
    } else if (presetName.includes("Action & Kinetic Dynamics")) {
        if (stepsW) stepsW.value = 25;
        if (mpW) mpW.value = 1.0;
        if (motionW) motionW.value = "on";
        if (contactW) contactW.value = "on";
        if (solidW) solidW.value = "on";
    } else if (presetName.includes("Turbo LoRA")) {
        if (stepsW) stepsW.value = 8;
        if (mpW) mpW.value = 0.83;
        if (shiftVW) shiftVW.value = 8.0;
        if (shiftAW) shiftAW.value = 2.0;
    } else if (presetName.includes("Low VRAM")) {
        if (stepsW) stepsW.value = 15;
        if (mpW) mpW.value = 0.65;
        if (tileF) tileF.value = 8;
        if (tileS) tileS.value = 256;
    }

    if (cpW && cpW.callback) cpW.callback(presetName);
    safeSetDirty(node);
}

function applyTabFilter(node, activeTab) {
    repairAndEnforceWidgetTypes(node);
    if (!node || !node.widgets) return;

    sanitizeNodeSlots(node);

    const showTimeline = (activeTab === "core" || activeTab === "directing" || activeTab === "all");
    node._h3_show_timeline = showTimeline;

    const metrics = getHeaderMetrics(node);
    node.widgets_start_y = metrics.totalHeaderBottom;

    for (const w of node.widgets) {
        if (w.name === "config_preset" || w.name === "first_frame_path" || w.name === "ref_paths") {
            w.type = "hidden";
            w.hidden = true;
            if (w.options) w.options.hidden = true;
            w.computeSize = () => [0, -4];
            continue;
        }

        if (!w._h3_origType || w._h3_origType === "hidden") {
            if (w.type && w.type !== "hidden") {
                w._h3_origType = w.type;
            } else if (Array.isArray(w.options?.values)) {
                w._h3_origType = "combo";
            } else if (typeof w.value === "boolean") {
                w._h3_origType = "toggle";
            } else if (typeof w.value === "number") {
                w._h3_origType = "number";
            } else {
                w._h3_origType = "customtext";
            }
        }

        if (!w._h3_origComputeSize && typeof w.computeSize === "function") {
            w._h3_origComputeSize = w.computeSize;
        }

        const category = WIDGET_CATEGORIES[w.name] || "core";
        let shouldShow = false;

        if (activeTab === "all") {
            shouldShow = true;
        } else if (activeTab === "presets") {
            shouldShow = ["steps", "megapixels", "resolution", "plan_only"].includes(w.name);
        } else {
            shouldShow = (category === activeTab);
        }

        if (shouldShow) {
            w.type = w._h3_origType;
            w.hidden = false;
            if (w.options) w.options.hidden = false;

            if (w._h3_origComputeSize && w._h3_origComputeSize !== w._h3_zeroComputeSize) {
                w.computeSize = w._h3_origComputeSize;
            } else {
                delete w.computeSize;
            }

            if (w.inputEl) {
                w.inputEl.style.display = "";
                w.inputEl.hidden = false;
            }
            if (w.element) {
                w.element.style.display = "";
                w.element.hidden = false;
            }
        } else {
            w.type = "hidden";
            w.hidden = true;
            if (w.options) w.options.hidden = true;

            w.computeSize = w._h3_zeroComputeSize || (w._h3_zeroComputeSize = () => [0, -4]);

            if (w.inputEl) {
                w.inputEl.style.display = "none";
                w.inputEl.hidden = true;
            }
            if (w.element) {
                w.element.style.display = "none";
                w.element.hidden = true;
            }
        }
    }

    const minWidth = 660;
    const computedSize = node.computeSize();
    const newWidth = Math.max(node.size[0] || minWidth, minWidth);
    const targetHeight = Math.min(Math.max(computedSize[1] || 480, metrics.totalHeaderBottom + 120), 850);
    node.setSize([newWidth, targetHeight]);

    if (typeof node.onResize === "function") {
        node.onResize(node.size);
    }

    safeSetDirty(node);
}

app.registerExtension({
    name: "MiniMaxH3.LongVideosUI",

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (!TARGET_NODES.has(nodeData.name)) return;

        const origNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origNodeCreated ? origNodeCreated.apply(this, arguments) : undefined;
            const node = this;

            node._h3_active_tab = "core";
            if (node.title === "H3 Long Videos (FL2VA + REF2VA)" || !node.title) node.title = "H3 LongVideo Studio";
            node._h3_show_timeline = true;
            node._shotBoxes = [];
            node._refBoxes = [];
            node._draggingIndex = null;
            node._dragStartX = 0;

            // Sanitize slots immediately
            setTimeout(() => {
                sanitizeNodeSlots(node);
                applyTabFilter(node, node._h3_active_tab || "core");
            }, 10);

            // Drag and drop listener
            if (!window._h3_drop_bound) {
                window._h3_drop_bound = true;
                window.addEventListener("dragover", (e) => {
                    e.preventDefault();
                });
                window.addEventListener("drop", async (e) => {
                    if (!e.dataTransfer?.files?.length) return;
                    const file = e.dataTransfer.files[0];
                    if (!file.type.startsWith("image/")) return;

                    const canvas = app.canvas;
                    if (!canvas) return;
                    const pos = canvas.convertEventToCanvasOffset(e);

                    const nodes = canvas.graph?._nodes || [];
                    for (let n of nodes) {
                        if (!TARGET_NODES.has(n.type)) continue;
                        const nx = n.pos[0];
                        const ny = n.pos[1];
                        const nw = n.size[0];
                        const nh = n.size[1];

                        if (pos[0] >= nx && pos[0] <= nx + nw && pos[1] >= ny && pos[1] <= ny + nh) {
                            const relX = pos[0] - nx;
                            const relY = pos[1] - ny;

                            const s1Box = (n._shotBoxes || [])[0];
                            if (s1Box && relX >= s1Box.x && relX <= s1Box.x + s1Box.w && relY >= s1Box.y && relY <= s1Box.y + s1Box.h) {
                                e.preventDefault();
                                const name = await uploadImageFile(file);
                                if (name) {
                                    const ffW = n.widgets?.find(w => w.name === "first_frame_path");
                                    if (ffW) ffW.value = name;
                                    safeSetDirty(n);
                                }
                                return;
                            }

                            for (let rb of (n._refBoxes || [])) {
                                if (relX >= rb.x && relX <= rb.x + rb.w && relY >= rb.y && relY <= rb.y + rb.h) {
                                    e.preventDefault();
                                    const name = await uploadImageFile(file);
                                    if (name) {
                                        const refW = n.widgets?.find(w => w.name === "ref_paths");
                                        if (refW) {
                                            let current = {};
                                            try { current = JSON.parse(refW.value || "{}"); } catch(_) {}
                                            current[rb.slot] = name;
                                            refW.value = JSON.stringify(current);
                                            safeSetDirty(n);
                                        }
                                    }
                                    return;
                                }
                            }
                        }
                    }
                });
            }

            // Audio shift coupling: 4:1 scale
            setTimeout(() => {
                const shiftVW = node.widgets?.find(w => w.name === "shift_video");
                const shiftAW = node.widgets?.find(w => w.name === "shift_audio");
                if (shiftVW) {
                    const origShiftVCb = shiftVW.callback;
                    shiftVW.callback = function(val) {
                        if (origShiftVCb) origShiftVCb.apply(this, arguments);
                        if (shiftAW && (shiftAW.value === 0 || shiftAW.value === 3.0 || shiftAW._auto_coupled)) {
                            shiftAW._auto_coupled = true;
                            shiftAW.value = parseFloat((val / 4.0).toFixed(2));
                        }
                        safeSetDirty(node);
                    };
                }

                sanitizeNodeSlots(node);
                applyTabFilter(node, node._h3_active_tab || "core");
            }, 30);

            // Inline plan preview hook
            const origOnExecuted = node.onExecuted;
            node.onExecuted = function(message) {
                if (origOnExecuted) origOnExecuted.apply(this, arguments);
                const infoText = (message && message.text && message.text[0]) ? message.text[0] : null;
                if (!infoText) return;

                let previewWidget = node.widgets?.find(w => w.name === "h3_plan_preview");
                if (!previewWidget) {
                    previewWidget = node.addWidget("text", "h3_plan_preview", "", () => {}, {
                        multiline: true,
                        readOnly: true
                    });
                    previewWidget._h3_origType = "text";
                    previewWidget._h3_origComputeSize = () => [node.size[0] - 24, 140];
                }

                previewWidget.value = "LAST EXECUTION / SHOT PLAN:\n" + infoText;
                safeSetDirty(node);
            };

            return r;
        };

        // Full-Width Vector Canvas Drawing (Studio Workspace)
        const origOnDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function(ctx, canvas) {
            const r = origOnDrawForeground ? origOnDrawForeground.apply(this, arguments) : undefined;
            const node = this;

            const nodeW = node.size[0];
            const margin = 12;
            const fullW = nodeW - margin * 2;
            if (fullW <= 100) return r;

            const m = getHeaderMetrics(node);

            ctx.save();

            // Subtle divider separating Connection Bay from Studio Controls
            ctx.strokeStyle = "#2e2e42";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(margin, m.slotAreaBottom - 2);
            ctx.lineTo(margin + fullW, m.slotAreaBottom - 2);
            ctx.stroke();

            // 1. Tab Navigation Bar
            const tabW = fullW / TABS.length;

            for (let i = 0; i < TABS.length; i++) {
                const tab = TABS[i];
                const tx = margin + i * tabW;
                const isActive = (node._h3_active_tab === tab.id);

                ctx.fillStyle = isActive ? "#3a3875" : "#1a1a24";
                ctx.beginPath();
                ctx.roundRect(tx + 1, m.tabY, tabW - 2, m.tabH, 3);
                ctx.fill();

                ctx.strokeStyle = isActive ? "#8b78ff" : "#333348";
                ctx.lineWidth = isActive ? 1.5 : 0.8;
                ctx.stroke();

                ctx.fillStyle = isActive ? "#ffffff" : "#94a3b8";
                ctx.font = isActive ? "bold 10px sans-serif" : "9px sans-serif";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(tab.label, tx + tabW / 2, m.tabY + m.tabH / 2);
            }

            // 2. Mode Action Button
            const planW = node.widgets?.find(w => w.name === "plan_only");
            const isPlanOnly = planW ? Boolean(planW.value) : false;

            ctx.fillStyle = isPlanOnly ? "#143020" : "#20202e";
            ctx.beginPath();
            ctx.roundRect(margin, m.modeY, fullW, m.modeH, 4);
            ctx.fill();

            ctx.strokeStyle = isPlanOnly ? "#34d399" : "#44445c";
            ctx.lineWidth = 1;
            ctx.stroke();

            ctx.fillStyle = isPlanOnly ? "#6ee7b7" : "#cbd5e1";
            ctx.font = "bold 10px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            const modeText = isPlanOnly
                ? "MODE: PLAN ONLY (FAST PREVIEW, 0s RENDER)"
                : "MODE: FULL RENDER (GENERATE VIDEO & AUDIO)";
            ctx.fillText(modeText, margin + fullW / 2, m.modeY + m.modeH / 2);

            // 3. Workflow Preset Selector
            const cpW = node.widgets?.find(w => w.name === "config_preset");
            const currentPreset = cpW ? (cpW.value || PRESETS[0]) : PRESETS[0];

            ctx.fillStyle = "#181822";
            ctx.beginPath();
            ctx.roundRect(margin, m.presetY, fullW, m.presetH, 4);
            ctx.fill();

            ctx.strokeStyle = "#38384e";
            ctx.lineWidth = 1;
            ctx.stroke();

            ctx.textAlign = "left";
            ctx.font = "bold 10px sans-serif";
            ctx.fillStyle = "#8b78ff";
            ctx.fillText("PRESET:", margin + 8, m.presetY + m.presetH / 2);

            ctx.font = "10px sans-serif";
            ctx.fillStyle = "#f1f5f9";
            ctx.fillText(currentPreset, margin + 65, m.presetY + m.presetH / 2);

            ctx.textAlign = "right";
            ctx.font = "bold 9px sans-serif";
            ctx.fillStyle = "#94a3b8";
            ctx.fillText("[ PREV | NEXT ]", margin + fullW - 8, m.presetY + m.presetH / 2);

            // 4. Style & Character Reference Tray
            if (node._h3_show_timeline) {
                node._refBoxes = [];
                const trayY = m.refTrayY;
                const trayH = m.refTrayH;

                ctx.fillStyle = "#111117";
                ctx.beginPath();
                ctx.roundRect(margin, trayY, fullW, trayH, 4);
                ctx.fill();
                ctx.strokeStyle = "#242436";
                ctx.lineWidth = 1;
                ctx.stroke();

                ctx.fillStyle = "#8b78ff";
                ctx.font = "bold 9px sans-serif";
                ctx.textAlign = "left";
                ctx.textBaseline = "top";
                ctx.fillText("STYLE & CHARACTER REFERENCES [ Drop image or click to load ]", margin + 8, trayY + 4);

                const refW_widget = node.widgets?.find(w => w.name === "ref_paths");
                let refData = {};
                try { refData = JSON.parse(refW_widget?.value || "{}"); } catch(_) {}

                const slotW = (fullW - 20) / 4;
                const slotH = 34;
                const slotY = trayY + 18;

                for (let s = 1; s <= 4; s++) {
                    const sx = margin + 4 + (s - 1) * slotW;
                    const sw = slotW - 4;
                    const fn = refData[String(s)] || "";

                    node._refBoxes.push({
                        slot: String(s),
                        x: sx,
                        y: slotY,
                        w: sw,
                        h: slotH,
                        filename: fn
                    });

                    ctx.fillStyle = fn ? "#192233" : "#171720";
                    ctx.beginPath();
                    ctx.roundRect(sx, slotY, sw, slotH, 3);
                    ctx.fill();
                    ctx.strokeStyle = fn ? "#60a5fa" : "#303044";
                    ctx.lineWidth = 1;
                    ctx.stroke();

                    if (fn) {
                        const img = getCachedImage(fn);
                        drawLetterboxedThumbnail(ctx, img, sx + 2, slotY + 2, 28, slotH - 4);

                        ctx.fillStyle = "#93c5fd";
                        ctx.font = "bold 8px sans-serif";
                        ctx.textAlign = "left";
                        ctx.textBaseline = "top";
                        ctx.fillText(`<Picture ${s}>`, sx + 34, slotY + 4);

                        ctx.fillStyle = "#94a3b8";
                        ctx.font = "8px sans-serif";
                        const shortName = fn.length > 10 ? fn.substring(0, 8) + ".." : fn;
                        ctx.fillText(shortName, sx + 34, slotY + 16);

                        // Clear [x]
                        ctx.fillStyle = "#ef4444";
                        ctx.font = "bold 9px sans-serif";
                        ctx.textAlign = "right";
                        ctx.fillText("x", sx + sw - 4, slotY + 4);
                    } else {
                        ctx.fillStyle = "#64748b";
                        ctx.font = "bold 8px sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText(`+ REF ${s} (Pic ${s})`, sx + sw / 2, slotY + slotH / 2);
                    }
                }

                // 5. Shot Sequence Timeline Ribbon
                const promptW = node.widgets?.find(w => w.name === "prompt");
                const promptText = promptW ? promptW.value : "";
                const shotSecW = node.widgets?.find(w => w.name === "shot_seconds");
                const defaultSec = shotSecW ? parseFloat(shotSecW.value || 5.0) : 5.0;
                const shiftVW = node.widgets?.find(w => w.name === "shift_video");
                const shiftV = shiftVW ? parseFloat(shiftVW.value || 12.0) : 12.0;

                const { shots } = parsePromptBeats(promptText, defaultSec);
                node._shotBoxes = [];

                const totalSec = shots.reduce((acc, s) => acc + s.seconds, 0);
                const totalFrames = Math.round(totalSec * 24);
                const totalAudioLatents = Math.round(totalSec * 40);

                ctx.fillStyle = "#121218";
                ctx.beginPath();
                ctx.roundRect(margin, m.ribbonY, fullW, m.ribbonH, 4);
                ctx.fill();
                ctx.strokeStyle = "#28283a";
                ctx.lineWidth = 1;
                ctx.stroke();

                ctx.fillStyle = "#94a3b8";
                ctx.font = "bold 9px sans-serif";
                ctx.textAlign = "left";
                ctx.textBaseline = "top";
                const titleText = shots.length > 0
                    ? `SHOT TIMELINE [ ${shots.length} Shots, ${totalSec.toFixed(1)}s / ${totalFrames}f ]`
                    : "SHOT TIMELINE [ Type beats in prompt or click + ADD BEAT ]";
                ctx.fillText(titleText, margin + 8, m.ribbonY + 6);

                ctx.fillStyle = "#22c55e";
                ctx.font = "bold 9px sans-serif";
                ctx.textAlign = "right";
                ctx.fillText("[ + ADD BEAT ]", margin + fullW - 8, m.ribbonY + 6);

                const trackY = m.ribbonY + 18;
                const trackH = 52;
                const trackW = fullW - 12;
                const trackX = margin + 6;

                const ffW = node.widgets?.find(w => w.name === "first_frame_path");
                const firstFrameFile = ffW?.value || "";

                if (shots.length === 0) {
                    ctx.fillStyle = "#333348";
                    ctx.font = "italic 10px sans-serif";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    ctx.fillText("No shots detected. Click [+ ADD BEAT] to scaffold your first scene shot.", trackX + trackW / 2, trackY + trackH / 2);
                } else {
                    const itemW = Math.max(90, trackW / shots.length);
                    for (let i = 0; i < shots.length; i++) {
                        const shot = shots[i];
                        const sx = trackX + i * itemW;
                        const sw = Math.min(itemW - 4, trackW - (i * itemW));
                        if (sw <= 10) break;

                        const isAnchor = shot.isAnchor;
                        const isBeingDragged = (node._draggingIndex === i);

                        node._shotBoxes.push({
                            index: i,
                            x: sx,
                            y: trackY,
                            w: sw,
                            h: trackH,
                            isAnchor
                        });

                        if (isAnchor) {
                            ctx.fillStyle = isBeingDragged ? "#483b75" : "#251f38";
                            ctx.strokeStyle = "#8b78ff";
                        } else if (shot.hasDialogue) {
                            ctx.fillStyle = isBeingDragged ? "#1a4d33" : "#132b1f";
                            ctx.strokeStyle = "#34d399";
                        } else if (shot.hasMotion) {
                            ctx.fillStyle = isBeingDragged ? "#4d3419" : "#2d1c10";
                            ctx.strokeStyle = "#fb923c";
                        } else {
                            ctx.fillStyle = isBeingDragged ? "#26354d" : "#14202e";
                            ctx.strokeStyle = "#60a5fa";
                        }

                        ctx.beginPath();
                        ctx.roundRect(sx, trackY, sw, trackH, 3);
                        ctx.fill();
                        ctx.lineWidth = isBeingDragged ? 1.8 : 0.9;
                        ctx.stroke();

                        if (isAnchor && firstFrameFile) {
                            const ffImg = getCachedImage(firstFrameFile);
                            drawLetterboxedThumbnail(ctx, ffImg, sx + 2, trackY + 2, 28, trackH - 4);

                            ctx.fillStyle = "#ef4444";
                            ctx.font = "bold 9px sans-serif";
                            ctx.textAlign = "right";
                            ctx.textBaseline = "top";
                            ctx.fillText("x", sx + sw - 4, trackY + 3);
                        }

                        const textOffset = (isAnchor && firstFrameFile) ? 32 : 4;

                        ctx.textAlign = "left";
                        ctx.textBaseline = "top";
                        ctx.font = "bold 9px sans-serif";
                        ctx.fillStyle = isAnchor ? "#c4b5fd" : (shot.hasDialogue ? "#a7f3d0" : "#93c5fd");
                        const tag = isAnchor ? (firstFrameFile ? "S1: I2V" : "S1: ANCHOR") : (shot.hasDialogue ? `S${i + 1}: DIA` : (shot.hasMotion ? `S${i + 1}: ACT` : `S${i + 1}: BEAT`));
                        ctx.fillText(tag, sx + textOffset, trackY + 3);

                        if (!isAnchor) {
                            ctx.fillStyle = "#64748b";
                            ctx.font = "8px sans-serif";
                            ctx.textAlign = "right";
                            ctx.fillText("::", sx + sw - 14, trackY + 3);

                            ctx.fillStyle = "#ef4444";
                            ctx.font = "bold 8px sans-serif";
                            ctx.fillText("x", sx + sw - 4, trackY + 3);
                        }

                        ctx.textAlign = "left";
                        ctx.font = "9px sans-serif";
                        ctx.fillStyle = "#e2e8f0";
                        ctx.fillText(`${shot.seconds}s (${shot.frames}f)`, sx + textOffset, trackY + 16);

                        const btnY = trackY + 32;
                        const btnH = 14;
                        const btnW = 14;

                        // [-]
                        ctx.fillStyle = "#1e293b";
                        ctx.beginPath();
                        ctx.roundRect(sx + textOffset, btnY, btnW, btnH, 2);
                        ctx.fill();
                        ctx.strokeStyle = "#475569";
                        ctx.lineWidth = 0.8;
                        ctx.stroke();

                        ctx.fillStyle = "#94a3b8";
                        ctx.font = "bold 9px sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText("-", sx + textOffset + btnW / 2, btnY + btnH / 2);

                        // [+]
                        ctx.fillStyle = "#1e293b";
                        ctx.beginPath();
                        ctx.roundRect(sx + textOffset + 16, btnY, btnW, btnH, 2);
                        ctx.fill();
                        ctx.stroke();

                        ctx.fillStyle = "#94a3b8";
                        ctx.fillText("+", sx + textOffset + 16 + btnW / 2, btnY + btnH / 2);

                        ctx.textAlign = "left";
                        ctx.font = "8px sans-serif";
                        ctx.fillStyle = "#64748b";
                        const snippet = shot.snippet.length > 8 ? shot.snippet.substring(0, 8) + ".." : shot.snippet;
                        ctx.fillText(snippet, sx + textOffset + 34, btnY + btnH / 2);
                    }
                }

                const footY = m.ribbonY + 72;
                ctx.fillStyle = "#64748b";
                ctx.font = "9px sans-serif";
                ctx.textAlign = "left";
                ctx.textBaseline = "middle";
                const coupledAudio = parseFloat((shiftV / 4.0).toFixed(2));
                ctx.fillText(`Audio: ${totalAudioLatents} latents @ 40Hz (Coupled shift: ${coupledAudio}) | 24 FPS`, margin + 8, footY + 8);
            }

            ctx.restore();
            return r;
        };

        // Full-Width Hit-Testing & Mouse Interaction
        const origNodeMouseDown = nodeType.prototype.onMouseDown;
        nodeType.prototype.onMouseDown = function(event, pos, canvas) {
            const node = this;
            const clickX = pos[0];
            const clickY = pos[1];
            const margin = 12;
            const fullW = node.size[0] - margin * 2;
            const m = getHeaderMetrics(node);

            // 1. Tab Bar Click
            if (clickY >= m.tabY && clickY <= (m.tabY + m.tabH) && clickX >= margin && clickX <= margin + fullW) {
                const tabW = fullW / TABS.length;
                const clickedIdx = Math.floor((clickX - margin) / tabW);
                if (clickedIdx >= 0 && clickedIdx < TABS.length) {
                    const newTab = TABS[clickedIdx].id;
                    if (node._h3_active_tab !== newTab) {
                        node._h3_active_tab = newTab;
                        applyTabFilter(node, newTab);
                    }
                    return true;
                }
            }

            // 2. Mode Button Click
            if (clickY >= m.modeY && clickY <= (m.modeY + m.modeH) && clickX >= margin && clickX <= margin + fullW) {
                const planW = node.widgets?.find(w => w.name === "plan_only");
                if (planW) {
                    planW.value = !planW.value;
                    if (planW.callback) planW.callback(planW.value);
                    safeSetDirty(node);
                    return true;
                }
            }

            // 3. Preset Selector Click
            if (clickY >= m.presetY && clickY <= (m.presetY + m.presetH) && clickX >= margin && clickX <= margin + fullW) {
                const cpW = node.widgets?.find(w => w.name === "config_preset");
                const current = cpW ? (cpW.value || PRESETS[0]) : PRESETS[0];
                let idx = PRESETS.indexOf(current);
                if (idx === -1) idx = 0;

                if (clickX >= margin + fullW - 60) {
                    idx = (idx + 1) % PRESETS.length;
                } else if (clickX >= margin + fullW - 120) {
                    idx = (idx - 1 + PRESETS.length) % PRESETS.length;
                } else {
                    idx = (idx + 1) % PRESETS.length;
                }

                applyPreset(node, PRESETS[idx]);
                return true;
            }

            // 4. Reference Tray Clicks
            if (node._h3_show_timeline && clickY >= m.refTrayY && clickY <= (m.refTrayY + m.refTrayH)) {
                for (let rb of (node._refBoxes || [])) {
                    if (clickX >= rb.x && clickX <= rb.x + rb.w && clickY >= rb.y && clickY <= rb.y + rb.h) {
                        const refW = node.widgets?.find(w => w.name === "ref_paths");
                        let current = {};
                        try { current = JSON.parse(refW?.value || "{}"); } catch(_) {}

                        if (rb.filename && clickX >= rb.x + rb.w - 14 && clickY <= rb.y + 14) {
                            delete current[rb.slot];
                            if (refW) refW.value = JSON.stringify(current);
                            safeSetDirty(node);
                            return true;
                        }

                        promptForLocalImage((filename) => {
                            current[rb.slot] = filename;
                            if (refW) refW.value = JSON.stringify(current);
                            safeSetDirty(node);
                        });
                        return true;
                    }
                }
            }

            // 5. Shot Sequence Timeline Interaction
            if (node._h3_show_timeline && clickY >= m.ribbonY && clickY <= (m.ribbonY + m.ribbonH) && clickX >= margin && clickX <= margin + fullW) {
                const promptW = node.widgets?.find(w => w.name === "prompt");

                if (clickY <= m.ribbonY + 16 && clickX >= margin + fullW - 70) {
                    addNewBeat(promptW);
                    safeSetDirty(node);
                    return true;
                }

                const hitBox = (node._shotBoxes || []).find(b =>
                    clickX >= b.x && clickX <= (b.x + b.w) && clickY >= b.y && clickY <= (b.y + b.h)
                );

                if (hitBox && promptW) {
                    const i = hitBox.index;
                    const ffW = node.widgets?.find(w => w.name === "first_frame_path");

                    if (hitBox.isAnchor && ffW?.value && clickX >= hitBox.x + hitBox.w - 14 && clickY <= hitBox.y + 14) {
                        ffW.value = "";
                        safeSetDirty(node);
                        return true;
                    }

                    if (hitBox.isAnchor && clickX <= hitBox.x + 30) {
                        promptForLocalImage((filename) => {
                            if (ffW) ffW.value = filename;
                            safeSetDirty(node);
                        });
                        return true;
                    }

                    if (!hitBox.isAnchor && clickX >= hitBox.x + hitBox.w - 12 && clickY <= hitBox.y + 14) {
                        deleteBeat(promptW, i);
                        safeSetDirty(node);
                        return true;
                    }

                    const offset = (hitBox.isAnchor && ffW?.value) ? 32 : 4;
                    const btnY = hitBox.y + 32;
                    const btnH = 14;
                    const btnW = 14;

                    // [-]
                    if (clickY >= btnY && clickY <= btnY + btnH && clickX >= hitBox.x + offset && clickX <= hitBox.x + offset + btnW) {
                        updatePromptShotDuration(promptW, i, -0.5);
                        safeSetDirty(node);
                        return true;
                    }

                    // [+]
                    if (clickY >= btnY && clickY <= btnY + btnH && clickX >= hitBox.x + offset + 16 && clickX <= hitBox.x + offset + 16 + btnW) {
                        updatePromptShotDuration(promptW, i, +0.5);
                        safeSetDirty(node);
                        return true;
                    }

                    if (!hitBox.isAnchor) {
                        node._draggingIndex = i;
                        node._dragStartX = clickX;
                        safeSetDirty(node);
                        return true;
                    }
                }
            }

            if (origNodeMouseDown) {
                return origNodeMouseDown.apply(this, arguments);
            }
        };

        const origNodeMouseUp = nodeType.prototype.onMouseUp;
        nodeType.prototype.onMouseUp = function(event, pos, canvas) {
            const node = this;
            if (node._draggingIndex !== null) {
                const fromIdx = node._draggingIndex;
                node._draggingIndex = null;
                const clickX = pos[0];
                const promptW = node.widgets?.find(w => w.name === "prompt");

                const targetBox = (node._shotBoxes || []).find(b =>
                    clickX >= b.x && clickX <= (b.x + b.w) && !b.isAnchor
                );

                if (targetBox && targetBox.index !== fromIdx && promptW) {
                    reorderPromptBeats(promptW, fromIdx, targetBox.index);
                }
                safeSetDirty(node);
                return true;
            }

            if (origNodeMouseUp) {
                return origNodeMouseUp.apply(this, arguments);
            }
        };

        // Configuration / Load Workflow Hook: Force slot & value sanitization
        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = origOnConfigure ? origOnConfigure.apply(this, arguments) : undefined;
            const n = this;
            setTimeout(() => {
                sanitizeNodeSlots(n);
                applyTabFilter(n, n._h3_active_tab || "core");
            }, 30);
            return r;
        };
    }
});
