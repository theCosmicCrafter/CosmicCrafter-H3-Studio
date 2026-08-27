import { app } from "../../scripts/app.js";

/**
 * MiniMax-H3 LongVideos Dynamic Tabbed Studio Interface
 * Provides clean categorised tab navigation, 1-click presets,
 * responsive canvas layouts, and real-time parameter coupling.
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

function applyTabFilter(node, activeTab) {
    if (!node || !node.widgets) return;

    for (const w of node.widgets) {
        // Never filter custom tab bar, action bar, or plan preview widgets
        if (w.name === "h3_tabs" || w.name === "h3_action_bar" || w.name === "h3_plan_preview") {
            continue;
        }

        // Cache original widget type and computeSize safely (never store "hidden")
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
            // Presets tab: Show preset selector and primary core dials
            shouldShow = ["config_preset", "steps", "megapixels", "resolution", "plan_only"].includes(w.name);
        } else if (w.name === "config_preset") {
            // config_preset is ALWAYS shown above prompt on Core as well!
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

    // Recalculate dynamic node dimensions smoothly
    const minWidth = 500;
    const computedSize = node.computeSize();
    const newWidth = Math.max(node.size[0] || minWidth, minWidth);
    const newHeight = Math.max(computedSize[1] || 200, 200);
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
                    this.last_y = y; // CRITICAL for ComfyUI hit testing
                    const margin = 6;
                    const availableWidth = widget_width - margin * 2;
                    const tabWidth = availableWidth / TABS.length;
                    const tabHeight = 26;

                    ctx.save();
                    for (let i = 0; i < TABS.length; i++) {
                        const tab = TABS[i];
                        const x = margin + i * tabWidth;
                        const isActive = (node._h3_active_tab === tab.id);

                        // Pill background
                        ctx.fillStyle = isActive ? "#3a3875" : "#1e1e28";
                        ctx.beginPath();
                        ctx.roundRect(x + 1, y + 2, tabWidth - 2, tabHeight - 4, 4);
                        ctx.fill();

                        // Accent border on active
                        if (isActive) {
                            ctx.strokeStyle = "#8b78ff";
                            ctx.lineWidth = 1.5;
                            ctx.stroke();
                        } else {
                            ctx.strokeStyle = "#333344";
                            ctx.lineWidth = 0.8;
                            ctx.stroke();
                        }

                        // Tab text
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
                    this.last_y = y; // CRITICAL for ComfyUI hit testing
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

            // Insert custom widgets at top
            node.widgets.unshift(actionBarWidget);
            node.widgets.unshift(tabBarWidget);

            // Hook node.onMouseDown delegation to guarantee tab bar hit testing works
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
                if (origNodeMouseDown) {
                    return origNodeMouseDown.apply(this, arguments);
                }
            };

            // Hook preset auto-configuration and reordering
            setTimeout(() => {
                // Ensure config_preset sits at the top of parameters, directly above prompt
                const cpIndex = node.widgets.findIndex(w => w.name === "config_preset");
                const promptIndex = node.widgets.findIndex(w => w.name === "prompt");
                if (cpIndex !== -1 && promptIndex !== -1 && cpIndex > promptIndex) {
                    const cpWidget = node.widgets.splice(cpIndex, 1)[0];
                    node.widgets.splice(promptIndex, 0, cpWidget);
                }

                // Clean up any legacy or orphaned exposed_terms DOM widget
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

                // Initial layout filtering
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

        // Top-level onConfigure hook for restoring workflows safely
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
