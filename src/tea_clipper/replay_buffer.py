"""Track recently finalized segments and stitch the most recent ones into a clip."""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
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
        fd, list_name = tempfile.mkstemp(
            dir=output_path.parent, prefix=".concat-", suffix=".txt"
        )
        list_file = Path(list_name)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write("".join(f"file '{p.resolve()}'\n" for p in segments))
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", str(output_path),
                ],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg concat failed (exit {result.returncode}): {result.stderr.strip()}"
                )
        finally:
            list_file.unlink(missing_ok=True)
        return output_path

    def save_last(self, seconds: float, output_path: Path, pipeline) -> Path:
        """Finalize the in-progress segment, then stitch the last `seconds` into a clip."""
        pipeline.force_split()           # ensure up-to-now footage is on disk
        segments = self.segments_for(seconds)
        if not segments:
            raise RuntimeError("no buffered segments available to save")
        return self.stitch(segments, output_path)
