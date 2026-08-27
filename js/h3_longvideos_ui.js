import { app } from "../../scripts/app.js";

/**
 * MiniMax-H3 LongVideos Dynamic Studio Interface
 * - Professional Studio Typography (Zero Emojis)
 * - Dynamic Full-Width Vector Drawing (Matches node width dynamically)
 * - Zero Widget Shifting (Preserves 100% positional widgets_values integrity)
 * - Interactive Shot Sequence Timeline Ribbon with Drag-and-Drop Reordering
 * - Instant Duration Controls (+/- 0.5s)
 * - Category Tab Navigation & 1-Click Presets
 */

const TARGET_NODES = new Set(["H3LongVideos", "H3_Promptor"]);

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
    // Core
    prompt: "core",
    resolution: "core",
    megapixels: "core",
    steps: "core",
    cfg: "core",
    seed: "core",
    sampler_name: "core",
    scheduler: "core",

    // Directing & Pacing
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

    // Soundscape & Audio
    auto_soundscape: "audio",
    global_soundscape: "audio",
    non_diegetic_music: "audio",
    auto_silence_nonspeech: "audio",
    allow_nonspeech_vocals: "audio",
    mute_nonspeech_audio: "audio",
    mute_fade_ms: "audio",

    // Guards & Physical Logic
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

    // Overlays & Post
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

    // Advanced Engine & Hardware
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
    config_preset: "presets"
};

function safeSetDirty(node) {
    try { node?.setDirtyCanvas?.(true, true); } catch (_) {}
    try { node?.graph?.setDirtyCanvas?.(true, true); } catch (_) {}
    try { app?.graph?.setDirtyCanvas?.(true, true); } catch (_) {}
    try { app?.canvas?.setDirty?.(true, true); } catch (_) {}
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
    if (fromIndex === 0 || toIndex === 0) return; // Keep Anchor at Paragraph 0
    if (fromIndex < 0 || fromIndex >= paragraphs.length || toIndex < 0 || toIndex >= paragraphs.length) return;

    const item = paragraphs.splice(fromIndex, 1)[0];
    paragraphs.splice(toIndex, 0, item);

    promptWidget.value = paragraphs.join("\n\n");
    if (promptWidget.inputEl) promptWidget.inputEl.value = promptWidget.value;
    if (promptWidget.callback) promptWidget.callback(promptWidget.value);
}

function applyPreset(node, presetName) {
    const cpW = node.widgets.find(w => w.name === "config_preset");
    if (cpW) cpW.value = presetName;

    const stepsW = node.widgets.find(w => w.name === "steps");
    const mpW = node.widgets.find(w => w.name === "megapixels");
    const cfgW = node.widgets.find(w => w.name === "cfg");
    const samplerW = node.widgets.find(w => w.name === "sampler_name");
    const schedW = node.widgets.find(w => w.name === "scheduler");
    const shiftVW = node.widgets.find(w => w.name === "shift_video");
    const shiftAW = node.widgets.find(w => w.name === "shift_audio");
    const motionW = node.widgets.find(w => w.name === "motion_guard");
    const contactW = node.widgets.find(w => w.name === "contact_guard");
    const solidW = node.widgets.find(w => w.name === "solidity_guard");
    const anatW = node.widgets.find(w => w.name === "anatomy_guard");
    const subCountW = node.widgets.find(w => w.name === "subject_count_guard");
    const tileF = node.widgets.find(w => w.name === "decode_tile_frames");
    const tileS = node.widgets.find(w => w.name === "decode_tile_size");
    const upscaleW = node.widgets.find(w => w.name === "upscale");
    const upShortW = node.widgets.find(w => w.name === "upscale_target_short_edge");

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
    if (!node || !node.widgets) return;

    const showTimeline = (activeTab === "core" || activeTab === "directing" || activeTab === "all");
    node._h3_show_timeline = showTimeline;

    // Header layout heights:
    // Tab bar (26px) + Mode button (24px) + Preset bar (24px) + Timeline (84px when visible)
    const headerHeight = showTimeline ? 216 : 126;
    node.widgets_start_y = headerHeight;

    for (const w of node.widgets) {
        if (w.name === "config_preset") {
            // Drawn in custom header bar at top
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

    const minWidth = 560;
    const computedSize = node.computeSize();
    const newWidth = Math.max(node.size[0] || minWidth, minWidth);
    const newHeight = Math.max(computedSize[1] || 240, 240);
    node.setSize([newWidth, newHeight]);

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
            node._h3_show_timeline = true;
            node._shotBoxes = [];
            node._draggingIndex = null;
            node._dragStartX = 0;

            // Hook dynamic audio shift coupling: maintain 4:1 video:audio shift scale
            setTimeout(() => {
                const shiftVW = node.widgets ? node.widgets.find(w => w.name === "shift_video") : null;
                const shiftAW = node.widgets ? node.widgets.find(w => w.name === "shift_audio") : null;
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

                // Clean orphaned exposed_terms textareas from DOM
                document.querySelectorAll("textarea").forEach(el => {
                    if (el.className && el.className.includes("exposed_terms")) {
                        el.remove();
                    }
                });

                applyTabFilter(node, node._h3_active_tab || "core");
            }, 20);

            // Inline Plan Execution Hook
            const origOnExecuted = node.onExecuted;
            node.onExecuted = function(message) {
                if (origOnExecuted) origOnExecuted.apply(this, arguments);
                const infoText = (message && message.text && message.text[0]) ? message.text[0] : null;
                if (!infoText) return;

                let previewWidget = node.widgets.find(w => w.name === "h3_plan_preview");
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

        // Full-Width Vector Canvas Drawing (Zero Emojis, Responsive Scaling)
        const origOnDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function(ctx, canvas) {
            const r = origOnDrawForeground ? origOnDrawForeground.apply(this, arguments) : undefined;
            const node = this;

            const nodeW = node.size[0];
            const margin = 12;
            const fullW = nodeW - margin * 2;
            if (fullW <= 100) return r;

            ctx.save();

            // 1. Tab Navigation Bar (y = 34, h = 26)
            const tabY = 34;
            const tabH = 26;
            const tabW = fullW / TABS.length;

            for (let i = 0; i < TABS.length; i++) {
                const tab = TABS[i];
                const tx = margin + i * tabW;
                const isActive = (node._h3_active_tab === tab.id);

                ctx.fillStyle = isActive ? "#3a3875" : "#1a1a24";
                ctx.beginPath();
                ctx.roundRect(tx + 1, tabY, tabW - 2, tabH, 3);
                ctx.fill();

                ctx.strokeStyle = isActive ? "#8b78ff" : "#333348";
                ctx.lineWidth = isActive ? 1.5 : 0.8;
                ctx.stroke();

                ctx.fillStyle = isActive ? "#ffffff" : "#94a3b8";
                ctx.font = isActive ? "bold 10px sans-serif" : "9px sans-serif";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(tab.label, tx + tabW / 2, tabY + tabH / 2);
            }

            // 2. Mode Action Button (y = 66, h = 24)
            const modeY = 66;
            const modeH = 24;
            const planW = node.widgets ? node.widgets.find(w => w.name === "plan_only") : null;
            const isPlanOnly = planW ? Boolean(planW.value) : false;

            ctx.fillStyle = isPlanOnly ? "#143020" : "#20202e";
            ctx.beginPath();
            ctx.roundRect(margin, modeY, fullW, modeH, 4);
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
            ctx.fillText(modeText, margin + fullW / 2, modeY + modeH / 2);

            // 3. Workflow Preset Selector (y = 96, h = 24)
            const presetY = 96;
            const presetH = 24;
            const cpW = node.widgets ? node.widgets.find(w => w.name === "config_preset") : null;
            const currentPreset = cpW ? (cpW.value || PRESETS[0]) : PRESETS[0];

            ctx.fillStyle = "#181822";
            ctx.beginPath();
            ctx.roundRect(margin, presetY, fullW, presetH, 4);
            ctx.fill();

            ctx.strokeStyle = "#38384e";
            ctx.lineWidth = 1;
            ctx.stroke();

            ctx.textAlign = "left";
            ctx.font = "bold 10px sans-serif";
            ctx.fillStyle = "#8b78ff";
            ctx.fillText("PRESET:", margin + 8, presetY + presetH / 2);

            ctx.font = "10px sans-serif";
            ctx.fillStyle = "#f1f5f9";
            ctx.fillText(currentPreset, margin + 65, presetY + presetH / 2);

            // Cycle button indicators on right
            ctx.textAlign = "right";
            ctx.font = "bold 9px sans-serif";
            ctx.fillStyle = "#94a3b8";
            ctx.fillText("[ PREV | NEXT ]", margin + fullW - 8, presetY + presetH / 2);

            // 4. Shot Sequence Timeline Ribbon (y = 126, h = 82, shown on core/directing/all)
            if (node._h3_show_timeline) {
                const ribbonY = 126;
                const ribbonH = 82;
                const promptW = node.widgets ? node.widgets.find(w => w.name === "prompt") : null;
                const promptText = promptW ? promptW.value : "";
                const shotSecW = node.widgets ? node.widgets.find(w => w.name === "shot_seconds") : null;
                const defaultSec = shotSecW ? parseFloat(shotSecW.value || 5.0) : 5.0;
                const shiftVW = node.widgets ? node.widgets.find(w => w.name === "shift_video") : null;
                const shiftV = shiftVW ? parseFloat(shiftVW.value || 12.0) : 12.0;

                const { shots } = parsePromptBeats(promptText, defaultSec);
                node._shotBoxes = [];

                const totalSec = shots.reduce((acc, s) => acc + s.seconds, 0);
                const totalFrames = Math.round(totalSec * 24);
                const totalAudioLatents = Math.round(totalSec * 40);

                // Container
                ctx.fillStyle = "#121218";
                ctx.beginPath();
                ctx.roundRect(margin, ribbonY, fullW, ribbonH, 4);
                ctx.fill();
                ctx.strokeStyle = "#28283a";
                ctx.lineWidth = 1;
                ctx.stroke();

                // Ribbon Header
                ctx.fillStyle = "#94a3b8";
                ctx.font = "bold 9px sans-serif";
                ctx.textAlign = "left";
                ctx.textBaseline = "top";
                const titleText = shots.length > 0
                    ? `SHOT TIMELINE [ ${shots.length} Shots, ${totalSec.toFixed(1)}s / ${totalFrames}f ]`
                    : "SHOT TIMELINE [ Type beats in prompt to visualize shots ]";
                ctx.fillText(titleText, margin + 8, ribbonY + 6);

                ctx.textAlign = "right";
                ctx.fillStyle = "#64748b";
                ctx.font = "9px sans-serif";
                ctx.fillText("[ Drag to Reorder | +/- Duration ]", margin + fullW - 8, ribbonY + 6);

                // Track area
                const trackY = ribbonY + 20;
                const trackH = 44;
                const trackW = fullW - 12;
                const trackX = margin + 6;

                if (shots.length === 0) {
                    ctx.fillStyle = "#333348";
                    ctx.font = "italic 10px sans-serif";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    ctx.fillText("No paragraphs detected. Type Paragraph 1 (Anchor) and Paragraphs 2..N (Beats)", trackX + trackW / 2, trackY + trackH / 2);
                } else {
                    const itemW = Math.max(80, trackW / shots.length);
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

                        // Label
                        ctx.textAlign = "left";
                        ctx.textBaseline = "top";
                        ctx.font = "bold 9px sans-serif";
                        ctx.fillStyle = isAnchor ? "#c4b5fd" : (shot.hasDialogue ? "#a7f3d0" : "#93c5fd");
                        const tag = isAnchor ? "ANCHOR" : (shot.hasDialogue ? "DIA" : (shot.hasMotion ? "ACT" : "BEAT"));
                        ctx.fillText(`S${i + 1}: ${tag}`, sx + 4, trackY + 3);

                        // Drag Grip Icon
                        if (!isAnchor) {
                            ctx.fillStyle = "#64748b";
                            ctx.font = "8px sans-serif";
                            ctx.textAlign = "right";
                            ctx.fillText("::", sx + sw - 4, trackY + 3);
                        }

                        // Duration Text & +/- Buttons
                        ctx.textAlign = "left";
                        ctx.font = "9px sans-serif";
                        ctx.fillStyle = "#e2e8f0";
                        ctx.fillText(`${shot.seconds}s (${shot.frames}f)`, sx + 4, trackY + 16);

                        const btnY = trackY + 28;
                        const btnH = 13;
                        const btnW = 14;

                        // Minus Button [-]
                        ctx.fillStyle = "#1e293b";
                        ctx.beginPath();
                        ctx.roundRect(sx + 4, btnY, btnW, btnH, 2);
                        ctx.fill();
                        ctx.strokeStyle = "#475569";
                        ctx.lineWidth = 0.8;
                        ctx.stroke();

                        ctx.fillStyle = "#94a3b8";
                        ctx.font = "bold 9px sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText("-", sx + 4 + btnW / 2, btnY + btnH / 2);

                        // Plus Button [+]
                        ctx.fillStyle = "#1e293b";
                        ctx.beginPath();
                        ctx.roundRect(sx + 20, btnY, btnW, btnH, 2);
                        ctx.fill();
                        ctx.stroke();

                        ctx.fillStyle = "#94a3b8";
                        ctx.fillText("+", sx + 20 + btnW / 2, btnY + btnH / 2);

                        // Snippet text
                        ctx.textAlign = "left";
                        ctx.font = "8px sans-serif";
                        ctx.fillStyle = "#64748b";
                        const snippet = shot.snippet.length > 10 ? shot.snippet.substring(0, 10) + ".." : shot.snippet;
                        ctx.fillText(snippet, sx + 38, btnY + btnH / 2);
                    }
                }

                // Status Footer
                const footY = ribbonY + 68;
                ctx.fillStyle = "#64748b";
                ctx.font = "9px sans-serif";
                ctx.textAlign = "left";
                ctx.textBaseline = "middle";
                const coupledAudio = parseFloat((shiftV / 4.0).toFixed(2));
                ctx.fillText(`Audio: ${totalAudioLatents} latents @ 40Hz (Coupled: ${coupledAudio}) | 24 FPS`, margin + 8, footY + 7);
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

            // 1. Tab Bar Click (y: 34 to 60)
            if (clickY >= 34 && clickY <= 60 && clickX >= margin && clickX <= margin + fullW) {
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

            // 2. Mode Button Click (y: 66 to 90)
            if (clickY >= 66 && clickY <= 90 && clickX >= margin && clickX <= margin + fullW) {
                const planW = node.widgets ? node.widgets.find(w => w.name === "plan_only") : null;
                if (planW) {
                    planW.value = !planW.value;
                    if (planW.callback) planW.callback(planW.value);
                    safeSetDirty(node);
                    return true;
                }
            }

            // 3. Preset Selector Click (y: 96 to 120)
            if (clickY >= 96 && clickY <= 120 && clickX >= margin && clickX <= margin + fullW) {
                const cpW = node.widgets ? node.widgets.find(w => w.name === "config_preset") : null;
                const current = cpW ? (cpW.value || PRESETS[0]) : PRESETS[0];
                let idx = PRESETS.indexOf(current);
                if (idx === -1) idx = 0;

                // Check if PREV clicked
                if (clickX >= margin + fullW - 60) {
                    // NEXT
                    idx = (idx + 1) % PRESETS.length;
                } else if (clickX >= margin + fullW - 120) {
                    // PREV
                    idx = (idx - 1 + PRESETS.length) % PRESETS.length;
                } else {
                    // Clicked on name -> cycle next
                    idx = (idx + 1) % PRESETS.length;
                }

                applyPreset(node, PRESETS[idx]);
                return true;
            }

            // 4. Shot Sequence Timeline Interaction (y: 146 to 190)
            if (node._h3_show_timeline && clickY >= 146 && clickY <= 190 && clickX >= margin && clickX <= margin + fullW) {
                const promptW = node.widgets ? node.widgets.find(w => w.name === "prompt") : null;
                const hitBox = (node._shotBoxes || []).find(b =>
                    clickX >= b.x && clickX <= (b.x + b.w) && clickY >= b.y && clickY <= (b.y + b.h)
                );

                if (hitBox && promptW) {
                    const i = hitBox.index;
                    const btnY = hitBox.y + 28;
                    const btnH = 13;
                    const btnW = 14;

                    // Minus Button [-]
                    if (clickY >= btnY && clickY <= btnY + btnH && clickX >= hitBox.x + 4 && clickX <= hitBox.x + 4 + btnW) {
                        updatePromptShotDuration(promptW, i, -0.5);
                        safeSetDirty(node);
                        return true;
                    }

                    // Plus Button [+]
                    if (clickY >= btnY && clickY <= btnY + btnH && clickX >= hitBox.x + 20 && clickX <= hitBox.x + 20 + btnW) {
                        updatePromptShotDuration(promptW, i, +0.5);
                        safeSetDirty(node);
                        return true;
                    }

                    // Drag to Reorder
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

        // Drag Release Hook
        const origNodeMouseUp = nodeType.prototype.onMouseUp;
        nodeType.prototype.onMouseUp = function(event, pos, canvas) {
            const node = this;
            if (node._draggingIndex !== null) {
                const fromIdx = node._draggingIndex;
                node._draggingIndex = null;
                const clickX = pos[0];
                const promptW = node.widgets ? node.widgets.find(w => w.name === "prompt") : null;

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

        // Configuration / Load Workflow Hook
        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = origOnConfigure ? origOnConfigure.apply(this, arguments) : undefined;
            const n = this;
            setTimeout(() => {
                applyTabFilter(n, n._h3_active_tab || "core");
            }, 30);
            return r;
        };
    }
});
