"""Track recently finalized segments and stitch the most recent ones into a clip."""

from __future__ import annotations

import math
import subprocess
from collections import deque
from pathlib import Path


class ReplayBuffer:
    """Consumes finalized-segment paths and stitches the last N seconds on demand."""

    def __init__(self, segment_seconds: int, max_tracked: int = 256) -> None:
        self.segment_seconds = segment_seconds
        self._segments: deque[Path] = deque(maxlen=max_tracked)

    def on_segment_finalized(self, path: Path) -> None:
        """Listener for CapturePipeline's segment-finalized event."""
        self._segments.append(Path(path))

    def segments_for(self, seconds: float) -> list[Path]:
        """Return the most recent segments (that still exist) covering `seconds`."""
        existing = [p for p in self._segments if p.exists()]
        count = max(1, math.ceil(seconds / self.segment_seconds))
        return existing[-count:]

    def stitch(self, segments: list[Path], output_path: Path) -> Path:
        """Losslessly concat `segments` into `output_path` via ffmpeg -c copy."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        list_file = output_path.with_suffix(".concat.txt")
        list_file.write_text(
            "".join(f"file '{p.resolve()}'\n" for p in segments)
        )
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", str(output_path),
                ],
                check=True,
            )
        finally:
            list_file.unlink(missing_ok=True)
        return output_path
