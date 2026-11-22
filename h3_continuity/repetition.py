"""Conservative detection of sustained, consecutive generated-text loops.

Repeated JSON keys, names and non-adjacent phrases are not evidence of a loop.
Only a long periodic suffix triggers; this is a heuristic, not a semantic judge.
"""

import re


class RepetitionGuard:
    WINDOW = 8192
    CHECK_EVERY = 128

    def __init__(self):
        self.tail = ""
        self.pending = 0

    def feed(self, text, final=False):
        """True when output contains a sustained exact phrase/block/whitespace loop."""
        # Process bounded pieces even when a provider buffers one large delta.
        for offset in range(0, len(text), self.CHECK_EVERY):
            part = text[offset:offset + self.CHECK_EVERY]
            self.tail = (self.tail + part)[-self.WINDOW:]
            self.pending += len(part)
            if self.pending >= self.CHECK_EVERY:
                self.pending = 0
                if self._loop():
                    return True
        return final and self._loop()

    def _loop(self):
        # An endless whitespace suffix can consume the entire output allowance.
        if len(self.tail) >= 1024 and self.tail[-1024:].isspace():
            return True
        text = re.sub(r"\s+", " ", self.tail)
        for size in range(16, min(1024, len(text) // 4) + 1):
            block = text[-size:]
            if text[-2 * size:-size] != block:
                continue
            # Short phrases need 768 repeated characters; whole JSON records need
            # 2048, to avoid mistaking ordinary repeated structure for degeneration.
            minimum = 2048 if any(c in block for c in '{}[]') else 768
            copies = max(4, (minimum + size - 1) // size)
            if len(text) >= size * copies and text.endswith(block * copies):
                return True
        return False
