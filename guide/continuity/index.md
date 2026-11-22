# Continuity

H3 Continuity keeps a film coherent across clips in four ways:

| Mechanism | Keeps | Page |
| --- | --- | --- |
| **Carried context** | Motion and sound across a *Continue* join, from the previous clip's saved latents. | [Joins and bridges](joins-and-bridges.md) |
| **Visual memory** | People, clothes, objects and places across a *Cut* or a new camera angle, from chosen earlier moments. | [Visual memory](visual-memory.md) |
| **Bridges** | A generated move across a hard cut, without re-rendering either neighbour. | [Joins and bridges](joins-and-bridges.md#bridges) |
| **Takes and the check** | Your ability to retry a clip and to see what changed. | [Takes](takes.md), [The continuity check](check.md) |
| **Long-chain settings** | Less burn over many continuing clips (experimental). | [Long continuing chains](long-chains.md) |

Rendered clips are saved with their **original** audio and video latents, which is what lets a later clip continue or remember them exactly, with no decode and re-encode in between.

!!! note "What this does and does not promise"
    These controls give H3 more context; they do not guarantee identical geometry or identity. The bundled demo shows retained details in one example, not a guarantee. Review every join and use takes to retry.
