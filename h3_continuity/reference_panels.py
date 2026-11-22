"""Find the separate views of a multi-panel reference sheet from the gutters between them."""
import numpy as np
from PIL import Image, ImageOps

WORKING_SIDE = 2048
FLAT = 20.0        # pixel spread (0-255) along a gutter line
EDGE = 0.15        # a gutter leaves at least this share of the side on each of its sides
THIN = 0.04        # and is at most this share of the side wide
CONTRAST = 30.0
DEPTH = 3


def _gutters(cell, axis):
    """Interior full-length uniform lines along axis 0 (rows) or 1 (columns) that differ from both neighbours."""
    other = 1 - axis
    spread, level = cell.std(axis=(other, 2)), cell.mean(axis=(other, 2))
    n, cuts, start = len(spread), [], None
    for i, flat in enumerate(list(spread < FLAT) + [False]):
        if flat and start is None:
            start = i
        elif not flat and start is not None:
            s, end, start = start, i, None
            if not (EDGE * n <= s and end <= (1 - EDGE) * n and end - s <= max(1, THIN * n)):
                continue
            inner_spread, inner_level = spread[s:end].mean(), level[s:end].mean()
            sides = [slice(max(0, s - 3), s), slice(end, min(n, end + 3))]
            if all(abs(level[side].mean() - inner_level) > CONTRAST or spread[side].mean() > 2 * inner_spread + 5
                   for side in sides):
                cuts.append((s, end))
    return cuts


def _split(cell, y, x, depth):
    rows, cols = _gutters(cell, 0), _gutters(cell, 1)
    if depth == DEPTH or not (rows or cols):
        return [(x, y, cell.shape[1], cell.shape[0])]
    def spans(cuts, size):
        edges = [0] + [v for cut in cuts for v in cut] + [size]
        return [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2)]
    found = []
    for top, bottom in spans(rows, cell.shape[0]):
        for left, right in spans(cols, cell.shape[1]):
            found += _split(cell[top:bottom, left:right], y + top, x + left, depth + 1)
    return found


def panels(path):
    """Boxes (x, y, width, height) of each view in reading order, or [] for an ordinary single image."""
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        width, height = image.size
        scale = max(1.0, max(width, height) / WORKING_SIDE)
        small = np.asarray(image.resize((max(1, round(width / scale)), max(1, round(height / scale))), Image.BOX), dtype=np.float32)
    found = _split(small, 0, 0, 0)
    if len(found) < 2:
        return []
    sx, sy = width / small.shape[1], height / small.shape[0]
    pad = int(np.ceil(max(sx, sy)))
    boxes = []
    for x, y, w, h in found:
        left, top = min(width, round(x * sx) + (pad if x else 0)), min(height, round(y * sy) + (pad if y else 0))
        right = max(left + 1, round((x + w) * sx) - (pad if x + w < small.shape[1] else 0))
        bottom = max(top + 1, round((y + h) * sy) - (pad if y + h < small.shape[0] else 0))
        boxes.append((left, top, right - left, bottom - top))
    return boxes
