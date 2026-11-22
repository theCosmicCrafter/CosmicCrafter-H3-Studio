# Install

## Requirements

- A **current ComfyUI** with working **MiniMax H3** support and its model files installed. H3 Continuity builds on ComfyUI's native H3 nodes; it does not download models.
- The models your H3 workflow uses: the H3 diffusion model, text encoder, video VAE, audio VAE, and an optional LoRA.
- A **GPU** suitable for your chosen model. The node pack itself was also started on a CPU-only ComfyUI to check that it loads, but generation needs a GPU.
- Python packages from `requirements.txt` (currently `jsonschema`).
- Optional: an **OpenAI-compatible language-model endpoint** for the [Story writer](../story/writer.md).
- Optional: a ComfyUI version that includes the core **MiniMax H3 Context Windows** node, for [long clips](../build/long-clips.md).

## Install the node pack

1. Clone the repository into ComfyUI's `custom_nodes` folder, or extract the source archive there:

    ```bash
    cd ComfyUI/custom_nodes
    git clone https://github.com/KadoBOT/ComfyUI-H3-Continuity-Studio.git
    ```

2. Install the requirements with **the same Python that runs ComfyUI**:

    ```bash
    python -m pip install -r ComfyUI-H3-Continuity-Studio/requirements.txt
    ```

    On Windows portable installs, use the portable Python instead: `python_embeded\python.exe -m pip install -r ...`.

3. **Restart ComfyUI** and refresh the browser tab so the matching frontend loads.

!!! warning "Install one copy only"
    Two copies of H3 Continuity both register the same nodes and routes. Remove or rename an older copy first, and back up your projects before replacing an installation.

## Check that it loaded

Double-click the canvas, search for `H3`, and you should find these nodes (full list in [Nodes](../reference/nodes.md)):

- **H3 Timeline**
- **H3 Story**
- **H3 Save Segment**
- **H3 Context Windows** and **H3 Join Chain**

If they are missing, read the ComfyUI console for an import error and see [Troubleshooting](../reference/troubleshooting.md).

## Optional MiniMax prompt guides

The public package does **not** include MiniMax's H3 prompt guides. Without them the node pack runs normally and its instruction bundle reports the guides as missing. If you have obtained the guides under terms that permit your use, place `base-en.txt` and `ref-en.txt` in `h3_continuity/h3_guide/` and restart ComfyUI. The guides and the H3 model are subject to MiniMax's terms, including territorial restrictions; see the repository's third-party notices.

## Security

H3 Continuity adds HTTP routes to ComfyUI. Keep ComfyUI behind your usual authenticated access boundary if you expose it beyond your own machine. API keys you save for the Story writer are stored on the ComfyUI server, by host.
