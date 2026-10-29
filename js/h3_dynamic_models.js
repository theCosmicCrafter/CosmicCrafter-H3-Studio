import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

// Live model dropdowns for the H3 prompt toolkit. The backend declares `model`
// as a free STRING (blank = auto-pick); this extension swaps that widget for a
// combo filled from /cosmic_h3/models so local servers' real names are one
// click away. Tagged values ("[Vision] name") are stripped server-side.
const PROMPT_CLASSES = new Set(["H3_Promptor", "CosmicH3Promptor"]);
const VISION_CLASSES = new Set(["H3_Vision_Analyzer", "CosmicH3VisionAnalyzer"]);

app.registerExtension({
    name: "CosmicCrafter.H3DynamicModels",
    async nodeCreated(node) {
        const isVision = VISION_CLASSES.has(node.comfyClass);
        if (!isVision && !PROMPT_CLASSES.has(node.comfyClass)) return;
        const filterType = isVision ? "vision" : "text";

        const providerWidget = node.widgets.find(w => w.name === "provider");
        const modelWidget = node.widgets.find(w => w.name === "model");
        if (!modelWidget) return;

        // Turn the free-text model widget into a combo at the same index so
        // widget order (and therefore serialization) does not move.
        const modelIdx = node.widgets.indexOf(modelWidget);
        const prevVal = modelWidget.value;
        node.widgets.splice(modelIdx, 1);
        const combo = node.addWidget("combo", "model", prevVal || "", () => {}, {
            values: ["(fetching models...)"],
        });
        node.widgets.splice(node.widgets.indexOf(combo), 1);
        node.widgets.splice(modelIdx, 0, combo);

        async function updateModelList() {
            const providerName = providerWidget ? providerWidget.value : "ollama";
            const keep = combo.value;
            combo.options.values = [`Querying ${providerName}...`];
            combo.value = `Querying ${providerName}...`;
            node.setDirtyCanvas(true, true);
            try {
                const res = await api.fetchApi(
                    `/cosmic_h3/models?provider=${encodeURIComponent(String(providerName).toLowerCase())}&type=${filterType}`
                );
                const data = await res.json();
                if (data && data.models && data.models.length > 0) {
                    combo.options.values = data.models;
                    combo.value = data.models.includes(keep) ? keep : data.models[0];
                } else {
                    combo.options.values = ["[No models available]"];
                    combo.value = "[No models available]";
                }
            } catch (e) {
                console.error("H3 model query failed:", e);
                combo.options.values = ["[Connection error]"];
                combo.value = "[Connection error]";
            }
            node.setDirtyCanvas(true, true);
        }

        if (providerWidget) {
            const origCallback = providerWidget.callback;
            providerWidget.callback = function () {
                if (origCallback) origCallback.apply(this, arguments);
                updateModelList();
            };
        }

        node.addWidget("button", "Refresh Models", null, updateModelList);

        // In-node preview of the prompt / vision context the backend just wrote.
        const origExecuted = node.onExecuted;
        node.onExecuted = function (message) {
            if (origExecuted) origExecuted.apply(this, arguments);
            if (!message || !message.text) return;
            const previewText = Array.isArray(message.text) ? message.text.join("\n") : String(message.text);
            let preview = node.widgets ? node.widgets.find(w => w.name === "generated_prompt_preview") : null;
            if (!preview) {
                preview = node.addWidget("customtext", "generated_prompt_preview", previewText, () => {}, { multiline: true });
                if (preview && preview.inputEl) {
                    preview.inputEl.readOnly = true;
                    preview.inputEl.style.opacity = 0.85;
                    preview.inputEl.style.fontSize = "11px";
                    preview.inputEl.style.maxHeight = "180px";
                }
            } else {
                preview.value = previewText;
            }
            node.setDirtyCanvas(true, true);
        };

        setTimeout(updateModelList, 150);
    }
});
