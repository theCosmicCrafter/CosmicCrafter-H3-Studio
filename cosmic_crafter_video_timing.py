"""Universal video timing resolver for the CosmicCrafter studio graph.

A single source of truth for frame_rate, seconds and frames. Wire its outputs
across the graph so every node that cares about timing reads the same numbers:
frame_rate -> VHS Video Combine / H3 conditioning frame_rate, frames -> H3
length / batch_size / frame_count, seconds -> duration inputs.

If ``frames`` is non-zero it overrides ``seconds``; otherwise ``seconds``
drives the frame count. The three outputs are always mutually consistent:
frames = round(seconds * frame_rate), seconds = frames / frame_rate.
"""

FPS_DEFAULT = 24.0  # H3's native rate; also a sensible default for general video


class CosmicCrafterVideoTiming:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "frame_rate": ("FLOAT", {
                    "default": FPS_DEFAULT,
                    "min": 0.001,
                    "max": 1000.0,
                    "step": 0.001,
                    "round": 0.001,
                    "tooltip": "Frames per second. Defaults to 24 (H3 native). "
                               "Wire to VHS Video Combine frame_rate or H3 "
                               "conditioning frame_rate.",
                }),
                "seconds": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 1000000.0,
                    "step": 0.1,
                    "round": 0.001,
                    "tooltip": "Target duration in seconds. Ignored when frames "
                               "is non-zero.",
                }),
                "frames": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 100000000,
                    "tooltip": "Target frame count. When non-zero, overrides "
                               "seconds and drives the seconds output.",
                }),
            }
        }

    RETURN_TYPES = ("FLOAT", "FLOAT", "INT")
    RETURN_NAMES = ("frame_rate", "seconds", "frames")
    FUNCTION = "resolve"
    CATEGORY = "H3 Studio/Conditioning"
    DESCRIPTION = (
        "Resolve frame_rate, seconds and frames from any combination of inputs "
        "as mutually consistent outputs. frames overrides seconds when non-zero. "
        "Use as a universal timing hub: frame_rate -> video render / conditioning, "
        "frames -> length / batch_size, seconds -> duration inputs."
    )

    def resolve(self, frame_rate, seconds, frames):
        fps = float(frame_rate)
        if not (fps > 0 and fps == fps):  # finite and positive
            raise ValueError(
                "CosmicCrafter Video Timing: frame_rate must be > 0, got %r."
                % (frame_rate,))

        if int(frames) > 0:
            frames_out = int(frames)
            seconds_out = frames_out / fps
        else:
            s = float(seconds)
            if s < 0:
                raise ValueError(
                    "CosmicCrafter Video Timing: seconds must be >= 0, got %r."
                    % (seconds,))
            # Round half up to the nearest whole frame.
            frames_out = int(s * fps + 0.5)
            seconds_out = frames_out / fps

        return (fps, seconds_out, frames_out)


NODE_CLASS_MAPPINGS = {
    "CosmicCrafterVideoTiming": CosmicCrafterVideoTiming,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CosmicCrafterVideoTiming": "CosmicCrafter Video Timing",
}
