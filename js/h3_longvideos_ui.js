import { app } from "../../scripts/app.js";

/**
 * MiniMax-H3 LongVideos Dynamic Tabbed Studio & Shot Sequence Timeline
 * Features:
 * - Interactive Visual Shot Sequence Ribbon (Timeline Track)
 * - Drag-and-Drop Scene Beat Reordering
 * - Instant 1-Click Duration Adjustments (±0.5s) with inline directive sync
 * - Categorised tab navigation and highest quality presets
 * - Real-time 4:1 audio coupling and DOM safety guards
 */

const TARGET_NODES = new Set(["H3LongVideos", "H3_Promptor"]);

const TABS = [
    { id: "presets", label: "⚡ Presets" },
    { id: "core", label: "🎬 Core" },
    { id: "directing", label: "⏱️ Directing" },
    { id: "audio", label: "🔊 Audio" },
    { id: "guards", label: "🛡️ Guards" },
    { id: "overlays", label: "🎨 Overlays" },
    { id: "advanced", label: "⚙️ Advanced" },
    { id: "all", label: "📄 All" }
];

const WIDGET_CATEGORIES = {
    // ⚡ Presets & 🎬 Core Setup
    config_preset: "core",
    prompt: "core",
    resolution: "core",
    megapixels: "core",
    steps: "core",
    cfg: "core",
    seed: "core",
    sampler_name: "core",
    scheduler: "core",

    // ⏱️ Directing & Pacing
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

    // 🔊 Soundscape & Audio
    auto_soundscape: "audio",
    global_soundscape: "audio",
    non_diegetic_music: "audio",
    auto_silence_nonspeech: "audio",
    allow_nonspeech_vocals: "audio",
    mute_nonspeech_audio: "audio",
    mute_fade_ms: "audio",

    // 🛡️ Guards & Physical Logic
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

    // 🎨 Overlays, Watermarks & Upscale
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

    // ⚙️ Advanced Engine & Hardware
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
    decode_tile_size: "advanced"
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

        const hasDialogue = /"[^"]+"|«[^»]+»|<d>[^<]+<\/d>/i.test(p);
        const hasWardrobe = /\bwardrobe\s*:/i.test(p);
        const hasMotion = /\b(walks|runs|turns|moves|jumps|struggles|dances|fights|steps|opens|stops|glances|whispers)\b/i.test(p);
        const isAnchor = (i === 0);

        const cleanLines = p.split("\n").filter(l => !/^\s*(?:seconds|duration|wardrobe):/i.test(l));
        const snippet = cleanLines.join(" ").substring(0, 35);

        shots.append ? null : shots.push({
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
    if (fromIndex === 0 || toIndex === 0) return; // Keep Anchor as Paragraph 0
    if (fromIndex < 0 || fromIndex >= paragraphs.length || toIndex < 0 || toIndex >= paragraphs.length) return;

    const item = paragraphs.splice(fromIndex, 1)[0];
    paragraphs.splice(toIndex, 0, item);

    promptWidget.value = paragraphs.join("\n\n");
    if (promptWidget.inputEl) promptWidget.inputEl.value = promptWidget.value;
    if (promptWidget.callback) promptWidget.callback(promptWidget.value);
}

function applyTabFilter(node, activeTab) {
    if (!node || !node.widgets) return;

    for (const w of node.widgets) {
        if (w.name === "h3_tabs" || w.name === "h3_action_bar" || w.name === "h3_plan_preview") {
            continue;
        }

        // Dedicated filter for the Shot Sequence Ribbon
        if (w.name === "h3_shot_ribbon") {
            const showRibbon = (activeTab === "core" || activeTab === "directing" || activeTab === "all");
            w.hidden = !showRibbon;
            if (w.options) w.options.hidden = !showRibbon;
            w.type = showRibbon ? "h3_shot_ribbon" : "hidden";
            w.computeSize = showRibbon ? (() => [node.size[0] - 20, 96]) : (() => [0, -4]);
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
            shouldShow = ["config_preset", "steps", "megapixels", "resolution", "plan_only"].includes(w.name);
        } else if (w.name === "config_preset") {
            shouldShow = (activeTab === "core" || activeTab === "presets");
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

    const minWidth = 520;
    const computedSize = node.computeSize();
    const newWidth = Math.max(node.size[0] || minWidth, minWidth);
    const newHeight = Math.max(computedSize[1] || 220, 220);
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

            // 1. Tab Bar Widget
            const tabBarWidget = {
                name: "h3_tabs",
                type: "h3_tabs",
                value: "core",
                last_y: 0,
                draw(ctx, node, widget_width, y, widget_height) {
                    this.last_y = y;
                    const margin = 6;
                    const availableWidth = widget_width - margin * 2;
                    const tabWidth = availableWidth / TABS.length;
                    const tabHeight = 26;

                    ctx.save();
                    for (let i = 0; i < TABS.length; i++) {
                        const tab = TABS[i];
                        const x = margin + i * tabWidth;
                        const isActive = (node._h3_active_tab === tab.id);

                        ctx.fillStyle = isActive ? "#3a3875" : "#1e1e28";
                        ctx.beginPath();
                        ctx.roundRect(x + 1, y + 2, tabWidth - 2, tabHeight - 4, 4);
                        ctx.fill();

                        if (isActive) {
                            ctx.strokeStyle = "#8b78ff";
                            ctx.lineWidth = 1.5;
                            ctx.stroke();
                        } else {
                            ctx.strokeStyle = "#333344";
                            ctx.lineWidth = 0.8;
                            ctx.stroke();
                        }

                        ctx.fillStyle = isActive ? "#ffffff" : "#aaaaaa";
                        ctx.font = isActive ? "bold 11px sans-serif" : "10px sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText(tab.label, x + tabWidth / 2, y + tabHeight / 2);
                    }
                    ctx.restore();
                },
                mouse(event, pos, node) {
                    const margin = 6;
                    const widget_width = node.size[0];
                    const availableWidth = widget_width - margin * 2;
                    const tabWidth = availableWidth / TABS.length;
                    const clickX = pos[0] - margin;

                    if (clickX < 0 || clickX > availableWidth) return false;

                    const clickedIndex = Math.floor(clickX / tabWidth);
                    if (clickedIndex >= 0 && clickedIndex < TABS.length) {
                        const newTab = TABS[clickedIndex].id;
                        if (node._h3_active_tab !== newTab) {
                            node._h3_active_tab = newTab;
                            applyTabFilter(node, newTab);
                        }
                        return true;
                    }
                    return false;
                },
                computeSize(width) {
                    return [width, 32];
                }
            };

            // 2. Action Strip Widget (Quick Plan Only Toggle)
            const actionBarWidget = {
                name: "h3_action_bar",
                type: "h3_action_bar",
                last_y: 0,
                draw(ctx, node, widget_width, y, widget_height) {
                    this.last_y = y;
                    const planWidget = node.widgets ? node.widgets.find(w => w.name === "plan_only") : null;
                    const isPlanOnly = planWidget ? Boolean(planWidget.value) : false;

                    const btnWidth = widget_width - 16;
                    const btnHeight = 24;
                    const x = 8;

                    ctx.save();
                    ctx.fillStyle = isPlanOnly ? "#1c3d28" : "#262635";
                    ctx.beginPath();
                    ctx.roundRect(x, y + 2, btnWidth, btnHeight - 4, 4);
                    ctx.fill();

                    ctx.strokeStyle = isPlanOnly ? "#34d399" : "#4b4b66";
                    ctx.lineWidth = 1;
                    ctx.stroke();

                    ctx.fillStyle = isPlanOnly ? "#6ee7b7" : "#cbd5e1";
                    ctx.font = "bold 11px sans-serif";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";

                    const statusText = isPlanOnly
                        ? "⚡ MODE: PLAN ONLY (Fast Preview, 0s Render)"
                        : "▶ MODE: FULL RENDER (Generate Video & Audio)";
                    ctx.fillText(statusText, x + btnWidth / 2, y + btnHeight / 2);

                    ctx.restore();
                },
                mouse(event, pos, node) {
                    const planWidget = node.widgets ? node.widgets.find(w => w.name === "plan_only") : null;
                    if (planWidget) {
                        planWidget.value = !planWidget.value;
                        if (planWidget.callback) {
                            planWidget.callback(planWidget.value);
                        }
                        safeSetDirty(node);
                        return true;
                    }
                    return false;
                },
                computeSize(width) {
                    return [width, 28];
                }
            };

            // 3. Interactive Shot Sequence Timeline Ribbon
            const shotRibbonWidget = {
                name: "h3_shot_ribbon",
                type: "h3_shot_ribbon",
                last_y: 0,
                _shotBoxes: [],
                _draggingIndex: null,
                _dragStartX: 0,
                draw(ctx, node, widget_width, y, widget_height) {
                    this.last_y = y;
                    const promptW = node.widgets ? node.widgets.find(w => w.name === "prompt") : null;
                    const promptText = promptW ? promptW.value : "";
                    const shotSecW = node.widgets ? node.widgets.find(w => w.name === "shot_seconds") : null;
                    const defaultSec = shotSecW ? parseFloat(shotSecW.value || 5.0) : 5.0;
                    const shiftVW = node.widgets ? node.widgets.find(w => w.name === "shift_video") : null;
                    const shiftV = shiftVW ? parseFloat(shiftVW.value || 12.0) : 12.0;

                    const { shots } = parsePromptBeats(promptText, defaultSec);
                    this._shots = shots;
                    this._shotBoxes = [];

                    const margin = 8;
                    const boxW = widget_width - margin * 2;
                    const totalSec = shots.reduce((acc, s) => acc + s.seconds, 0);
                    const totalFrames = Math.round(totalSec * 24);
                    const totalAudioLatents = Math.round(totalSec * 40);

                    ctx.save();

                    // Outer Card Container
                    ctx.fillStyle = "#14141c";
                    ctx.beginPath();
                    ctx.roundRect(margin, y + 2, boxW, 90, 6);
                    ctx.fill();
                    ctx.strokeStyle = "#2e2e44";
                    ctx.lineWidth = 1;
                    ctx.stroke();

                    // Header Row: Sequence title and duration
                    ctx.fillStyle = "#94a3b8";
                    ctx.font = "bold 10px sans-serif";
                    ctx.textAlign = "left";
                    ctx.textBaseline = "top";
                    const shotCountText = shots.length > 0
                        ? `🎬 SHOT TIMELINE (${shots.length} Shots, ${totalSec.toFixed(1)}s / ${totalFrames}f)`
                        : "🎬 SHOT TIMELINE (Type beats in prompt to visualize shots)";
                    ctx.fillText(shotCountText, margin + 8, y + 6);

                    ctx.textAlign = "right";
                    ctx.fillStyle = "#64748b";
                    ctx.font = "9px sans-serif";
                    ctx.fillText("⇆ Drag to Reorder | ± Duration", margin + boxW - 8, y + 6);

                    // Horizontal Shot Track Area
                    const trackY = y + 20;
                    const trackH = 50;
                    const trackW = boxW - 12;
                    const trackX = margin + 6;

                    if (shots.length === 0) {
                        ctx.fillStyle = "#333348";
                        ctx.font = "italic 11px sans-serif";
                        ctx.textAlign = "center";
                        ctx.textBaseline = "middle";
                        ctx.fillText("No paragraphs detected. Type Paragraph 1 (Anchor) and Paragraphs 2..N (Beats)", trackX + trackW / 2, trackY + trackH / 2);
                    } else {
                        const itemW = Math.max(88, trackW / shots.length);
                        for (let i = 0; i < shots.length; i++) {
                            const shot = shots[i];
                            const sx = trackX + i * itemW;
                            const sw = Math.min(itemW - 4, trackW - (i * itemW));
                            if (sw <= 10) break;

                            const isAnchor = shot.isAnchor;
                            const isBeingDragged = (this._draggingIndex === i);

                            // Store bounding box for hit-testing
                            this._shotBoxes.push({
                                index: i,
                                x: sx,
                                y: trackY,
                                w: sw,
                                h: trackH,
                                isAnchor
                            });

                            // Box Background styling
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
                            ctx.roundRect(sx, trackY, sw, trackH, 4);
                            ctx.fill();
                            ctx.lineWidth = isBeingDragged ? 2 : 1;
                            ctx.stroke();

                            // Shot label & badges
                            ctx.textAlign = "left";
                            ctx.textBaseline = "top";
                            ctx.font = "bold 10px sans-serif";
                            ctx.fillStyle = isAnchor ? "#c4b5fd" : (shot.hasDialogue ? "#a7f3d0" : "#93c5fd");
                            const badge = isAnchor ? "⚓" : (shot.hasDialogue ? "💬" : (shot.hasMotion ? "🏃" : "🎞️"));
                            ctx.fillText(`${badge} S${i + 1}`, sx + 5, trackY + 4);

                            // Drag Handle Icon
                            if (!isAnchor) {
                                ctx.fillStyle = "#64748b";
                                ctx.font = "8px sans-serif";
                                ctx.textAlign = "right";
                                ctx.fillText("⋮⋮", sx + sw - 4, trackY + 4);
                            }

                            // Duration Text & +/- Buttons
                            ctx.textAlign = "left";
                            ctx.font = "9px sans-serif";
                            ctx.fillStyle = "#e2e8f0";
                            ctx.fillText(`${shot.seconds}s (${shot.frames}f)`, sx + 5, trackY + 18);

                            // Mini duration +/- controls
                            const btnY = trackY + 31;
                            const btnH = 14;
                            const btnW = 16;

                            // Minus Button [-]
                            ctx.fillStyle = "#1e293b";
                            ctx.beginPath();
                            ctx.roundRect(sx + 5, btnY, btnW, btnH, 2);
                            ctx.fill();
                            ctx.strokeStyle = "#475569";
                            ctx.lineWidth = 0.8;
                            ctx.stroke();

                            ctx.fillStyle = "#94a3b8";
                            ctx.font = "bold 9px sans-serif";
                            ctx.textAlign = "center";
                            ctx.textBaseline = "middle";
                            ctx.fillText("-", sx + 5 + btnW / 2, btnY + btnH / 2);

                            // Plus Button [+]
                            ctx.fillStyle = "#1e293b";
                            ctx.beginPath();
                            ctx.roundRect(sx + 24, btnY, btnW, btnH, 2);
                            ctx.fill();
                            ctx.stroke();

                            ctx.fillStyle = "#94a3b8";
                            ctx.fillText("+", sx + 24 + btnW / 2, btnY + btnH / 2);

                            // Snippet preview text
                            ctx.textAlign = "left";
                            ctx.font = "8px sans-serif";
                            ctx.fillStyle = "#94a3b8";
                            const clipSnippet = shot.snippet.length > 10 ? shot.snippet.substring(0, 10) + ".." : shot.snippet;
                            ctx.fillText(clipSnippet, sx + 44, btnY + btnH / 2);
                        }
                    }

                    // Footer Bar: Audio coupling & hardware info
                    const footY = y + 74;
                    ctx.fillStyle = "#64748b";
                    ctx.font = "9px sans-serif";
                    ctx.textAlign = "left";
                    ctx.textBaseline = "middle";
                    const coupledAudio = parseFloat((shiftV / 4.0).toFixed(2));
                    ctx.fillText(`🔊 Audio Latents: ${totalAudioLatents} @ 40Hz (Coupled shift: ${coupledAudio}) | 🎞️ 24 FPS`, margin + 8, footY + 7);

                    ctx.restore();
                },
                mouse(event, pos, node) {
                    const promptW = node.widgets ? node.widgets.find(w => w.name === "prompt") : null;
                    if (!promptW) return false;

                    const clickX = pos[0];
                    const clickY = pos[1];

                    // Check which shot was hit
                    const hitBox = (this._shotBoxes || []).find(b =>
                        clickX >= b.x && clickX <= (b.x + b.w) && clickY >= b.y && clickY <= (b.y + b.h)
                    );

                    if (hitBox) {
                        const i = hitBox.index;
                        const btnY = hitBox.y + 31;
                        const btnH = 14;
                        const btnW = 16;

                        // Click on [-] button
                        if (clickY >= btnY && clickY <= btnY + btnH && clickX >= hitBox.x + 5 && clickX <= hitBox.x + 5 + btnW) {
                            updatePromptShotDuration(promptW, i, -0.5);
                            safeSetDirty(node);
                            return true;
                        }

                        // Click on [+] button
                        if (clickY >= btnY && clickY <= btnY + btnH && clickX >= hitBox.x + 24 && clickX <= hitBox.x + 24 + btnW) {
                            updatePromptShotDuration(promptW, i, +0.5);
                            safeSetDirty(node);
                            return true;
                        }

                        // Dragging scene beats to reorder (only non-anchor beats 1..N)
                        if (event.type === "pointerdown" || event.type === "mousedown") {
                            if (!hitBox.isAnchor) {
                                this._draggingIndex = i;
                                this._dragStartX = clickX;
                                safeSetDirty(node);
                                return true;
                            }
                        }
                    }

                    // Handle Drop on Pointer Up
                    if (event.type === "pointerup" || event.type === "mouseup") {
                        if (this._draggingIndex !== null) {
                            const fromIdx = this._draggingIndex;
                            this._draggingIndex = null;

                            const targetBox = (this._shotBoxes || []).find(b =>
                                clickX >= b.x && clickX <= (b.x + b.w) && !b.isAnchor
                            );

                            if (targetBox && targetBox.index !== fromIdx) {
                                reorderPromptBeats(promptW, fromIdx, targetBox.index);
                            }
                            safeSetDirty(node);
                            return true;
                        }
                    }

                    return false;
                },
                computeSize(width) {
                    return [width, 96];
                }
            };

            // Insert custom widgets at top
            node.widgets.unshift(shotRibbonWidget);
            node.widgets.unshift(actionBarWidget);
            node.widgets.unshift(tabBarWidget);

            // Hook node.onMouseDown delegation to guarantee tab bar and timeline clicks always fire
            const origNodeMouseDown = node.onMouseDown;
            node.onMouseDown = function(event, pos, canvas) {
                if (tabBarWidget.last_y !== undefined) {
                    const ty = tabBarWidget.last_y;
                    if (pos[1] >= ty - 2 && pos[1] <= ty + 34) {
                        if (tabBarWidget.mouse(event, pos, this)) {
                            return true;
                        }
                    }
                }
                if (actionBarWidget.last_y !== undefined) {
                    const ay = actionBarWidget.last_y;
                    if (pos[1] >= ay - 2 && pos[1] <= ay + 30) {
                        if (actionBarWidget.mouse(event, pos, this)) {
                            return true;
                        }
                    }
                }
                if (shotRibbonWidget.last_y !== undefined) {
                    const ry = shotRibbonWidget.last_y;
                    if (pos[1] >= ry - 2 && pos[1] <= ry + 96) {
                        if (shotRibbonWidget.mouse(event, pos, this)) {
                            return true;
                        }
                    }
                }
                if (origNodeMouseDown) {
                    return origNodeMouseDown.apply(this, arguments);
                }
            };

            // Hook node.onMouseUp delegation for drag release
            const origNodeMouseUp = node.onMouseUp;
            node.onMouseUp = function(event, pos, canvas) {
                if (shotRibbonWidget.last_y !== undefined && shotRibbonWidget._draggingIndex !== null) {
                    shotRibbonWidget.mouse(event, pos, this);
                }
                if (origNodeMouseUp) {
                    return origNodeMouseUp.apply(this, arguments);
                }
            };

            // Hook preset auto-configuration and reordering
            setTimeout(() => {
                const cpIndex = node.widgets.findIndex(w => w.name === "config_preset");
                const promptIndex = node.widgets.findIndex(w => w.name === "prompt");
                if (cpIndex !== -1 && promptIndex !== -1 && cpIndex > promptIndex) {
                    const cpWidget = node.widgets.splice(cpIndex, 1)[0];
                    node.widgets.splice(promptIndex, 0, cpWidget);
                }

                const expWidget = node.widgets.find(w => w.name === "exposed_terms");
                if (expWidget) {
                    if (expWidget.inputEl) expWidget.inputEl.remove();
                    const idx = node.widgets.indexOf(expWidget);
                    if (idx !== -1) node.widgets.splice(idx, 1);
                }

                const presetWidget = node.widgets.find(w => w.name === "config_preset");
                if (presetWidget) {
                    const origCb = presetWidget.callback;
                    presetWidget.callback = function(val) {
                        if (origCb) origCb.apply(this, arguments);

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

                        if (val && val.includes("Cinematic Master")) {
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
                        } else if (val && val.includes("Quality Base H3")) {
                            if (stepsW) stepsW.value = 20;
                            if (mpW) mpW.value = 1.0;
                            if (cfgW) cfgW.value = 1.0;
                            if (samplerW) samplerW.value = "res_multistep";
                            if (schedW) schedW.value = "simple";
                            if (shiftVW) shiftVW.value = 12.0;
                            if (shiftAW) shiftAW.value = 3.0;
                        } else if (val && val.includes("Ultra-Detailed 4K Master")) {
                            if (stepsW) stepsW.value = 25;
                            if (mpW) mpW.value = 1.0;
                            if (cfgW) cfgW.value = 1.0;
                            if (samplerW) samplerW.value = "res_multistep";
                            if (schedW) schedW.value = "simple";
                            if (shiftVW) shiftVW.value = 12.0;
                            if (shiftAW) shiftAW.value = 3.0;
                            if (upscaleW) upscaleW.value = "model";
                            if (upShortW) upShortW.value = 1440;
                        } else if (val && val.includes("Action & Kinetic Dynamics")) {
                            if (stepsW) stepsW.value = 25;
                            if (mpW) mpW.value = 1.0;
                            if (motionW) motionW.value = "on";
                            if (contactW) contactW.value = "on";
                            if (solidW) solidW.value = "on";
                        } else if (val && val.includes("Turbo LoRA")) {
                            if (stepsW) stepsW.value = 8;
                            if (mpW) mpW.value = 0.83;
                            if (shiftVW) shiftVW.value = 8.0;
                            if (shiftAW) shiftAW.value = 2.0;
                        } else if (val && val.includes("Low VRAM")) {
                            if (stepsW) stepsW.value = 15;
                            if (mpW) mpW.value = 0.65;
                            if (tileF) tileF.value = 8;
                            if (tileS) tileS.value = 256;
                        }
                        safeSetDirty(node);
                    };
                }

                // Dynamic Audio Shift coupling: maintain 4:1 video:audio shift scale
                const shiftVW = node.widgets.find(w => w.name === "shift_video");
                const shiftAW = node.widgets.find(w => w.name === "shift_audio");
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

                // Clean orphaned textareas in DOM
                document.querySelectorAll("textarea").forEach(el => {
                    if (el.className && el.className.includes("exposed_terms")) {
                        el.remove();
                    }
                });

                applyTabFilter(node, node._h3_active_tab || "core");
            }, 10);

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
                    previewWidget._h3_origComputeSize = () => [node.size[0] - 20, 140];
                }

                previewWidget.value = "📋 LAST EXECUTION / SHOT PLAN:\n" + infoText;
                safeSetDirty(node);
            };

            return r;
        };

        const origOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = origOnConfigure ? origOnConfigure.apply(this, arguments) : undefined;
            const n = this;
            setTimeout(() => {
                if (n.widgets) {
                    const cpIndex = n.widgets.findIndex(w => w.name === "config_preset");
                    const promptIndex = n.widgets.findIndex(w => w.name === "prompt");
                    if (cpIndex !== -1 && promptIndex !== -1 && cpIndex > promptIndex) {
                        const cpWidget = n.widgets.splice(cpIndex, 1)[0];
                        n.widgets.splice(promptIndex, 0, cpWidget);
                    }
                    const expW = n.widgets.find(w => w.name === "exposed_terms");
                    if (expW) {
                        if (expW.inputEl) expW.inputEl.remove();
                        const idx = n.widgets.indexOf(expW);
                        if (idx !== -1) n.widgets.splice(idx, 1);
                    }
                }
                applyTabFilter(n, n._h3_active_tab || "core");
            }, 50);
            return r;
        };
    }
});
