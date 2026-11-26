import json
from pathlib import Path

wf_dir = Path(__file__).resolve().parent.parent / "workflows"
for wf_path in sorted(wf_dir.glob("*.json")):
    try:
        data = json.loads(wf_path.read_text(encoding="utf-8", errors="ignore"))
        nodes = data.get("nodes", [])
        for n in nodes:
            t = n.get("type", "")
            if any(k in t.lower() for k in ["prompt", "llm", "cosmic", "model"]):
                node_id = n.get("id")
                w = n.get("widgets_values", [])
                print(f"{wf_path.name} -> Node {node_id}: {t}")
                if w:
                    print(f"   widgets: {str(w)[:120]}")
    except Exception:
        pass
