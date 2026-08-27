import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

app.registerExtension({
    name: "CosmicCrafter.H3DynamicModels",
    async nodeCreated(node) {
        if (node.comfyClass !== "H3_Promptor" && node.comfyClass !== "H3_Vision_Analyzer") return;

        const isVision = node.comfyClass === "H3_Vision_Analyzer";
        const filterType = isVision ? "vision" : "text";

        const providerWidget = node.widgets.find(w => w.name === "provider");
        const modelWidget = node.widgets.find(w => w.name === "model");

        async function updateModelList(providerName) {
            if (!modelWidget) return;
            const prevVal = modelWidget.value;
            modelWidget.options.values = ["Querying " + providerName + "..."];
            modelWidget.value = "Querying " + providerName + "...";
            node.setDirtyCanvas(true, true);

            try {
                const res = await api.fetchApi(`/cosmic_h3/models?provider=${encodeURIComponent(providerName.toLowerCase())}&type=${filterType}`);
                const data = await res.json();
                if (data && data.models && data.models.length > 0) {
                    modelWidget.options.values = data.models;
                    if (data.models.includes(prevVal)) {
                        modelWidget.value = prevVal;
                    } else {
                        modelWidget.value = data.models[0];
                    }
                } else {
                    modelWidget.options.values = ["[No models available]"];
                    modelWidget.value = "[No models available]";
                }
            } catch (e) {
                console.error("Failed to query models:", e);
                modelWidget.options.values = ["[Connection error]"];
                modelWidget.value = "[Connection error]";
            }
            node.setDirtyCanvas(true, true);
        }

        if (providerWidget) {
            const origCallback = providerWidget.callback;
            providerWidget.callback = function(value) {
                if (origCallback) origCallback.apply(this, arguments);
                updateModelList(value);
            };
        }

        node.addWidget("button", "Refresh Models", null, () => {
            const currentProvider = providerWidget ? providerWidget.value : "Ollama";
            updateModelList(currentProvider);
        });

        function updatePromptPreview(text) {
            if (!text) return;
            const previewText = Array.isArray(text) ? text.join("\n") : String(text);
            let previewWidget = node.widgets ? node.widgets.find(w => w.name === "generated_prompt_preview") : null;
            if (!previewWidget) {
                previewWidget = node.addWidget("customtext", "generated_prompt_preview", previewText, () => {}, { multiline: true });
                if (previewWidget && previewWidget.inputEl) {
                    previewWidget.inputEl.readOnly = true;
                    previewWidget.inputEl.style.opacity = 0.85;
                    previewWidget.inputEl.style.fontSize = "11px";
                    previewWidget.inputEl.style.maxHeight = "180px";
                }
            } else {
                previewWidget.value = previewText;
            }
            node.setDirtyCanvas(true, true);
        }

        const origExecuted = node.onExecuted;
        node.onExecuted = function(message) {
            if (origExecuted) origExecuted.apply(this, arguments);
            if (message && message.text) {
                updatePromptPreview(message.text);
            }
        };

        function sanitizeWidgets() {
            if (!node.widgets) return;
            const refVids = node.widgets.find(w => w.name === "reference_videos");
            const refAuds = node.widgets.find(w => w.name === "reference_audios");
            const refImgs = node.widgets.find(w => w.name === "reference_images");
            const outLang = node.widgets.find(w => w.name === "output_language");
            const temp = node.widgets.find(w => w.name === "temperature");
            const maxTok = node.widgets.find(w => w.name === "max_tokens");
            const genMode = node.widgets.find(w => w.name === "generation_mode");
            const cineStyle = node.widgets.find(w => w.name === "cinematic_style");

            if (refVids && (refVids.value === "Auto (Adaptive)" || !["Auto", "1", "2", "3"].includes(refVids.value))) {
                refVids.value = "Auto";
            }
            if (refAuds && (!refAuds.value || !["Auto", "1", "2", "3"].includes(refAuds.value))) {
                refAuds.value = "Auto";
            }
            if (refImgs && !["Auto", "1", "2", "3", "4", "5", "6", "7", "8", "9"].includes(refImgs.value)) {
                refImgs.value = "Auto";
            }
            if (outLang && (outLang.value === "Auto" || !["English", "Chinese"].includes(outLang.value))) {
                outLang.value = "English";
            }
            if (temp && (typeof temp.value !== "number" || isNaN(temp.value) || temp.value === "Auto")) {
                temp.value = 0.4;
            }
            if (maxTok && (typeof maxTok.value !== "number" || isNaN(maxTok.value) || maxTok.value === "English" || maxTok.value === "Auto")) {
                maxTok.value = 4096;
            }
            if (genMode && !["Director (Two-Stage)", "Turbo (Single-Stage)"].includes(genMode.value)) {
                genMode.value = "Director (Two-Stage)";
            }
            if (cineStyle && !cineStyle.value) {
                cineStyle.value = "None (Neutral)";
            }
            node.setDirtyCanvas(true, true);
        }

        sanitizeWidgets();

        const origConfigure = node.onConfigure;
        node.onConfigure = function() {
            if (origConfigure) origConfigure.apply(this, arguments);
            sanitizeWidgets();
        };

        setTimeout(() => {
            if (providerWidget) {
                updateModelList(providerWidget.value);
            }
            sanitizeWidgets();
        }, 150);
    }
});
