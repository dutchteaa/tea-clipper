"""Manual start/stop recording built on the shared segment stream."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


class ManualRecorder:
    """While active, collects finalized segments; on stop, stitches them into one file."""

    def __init__(self, pipeline) -> None:
        self._pipeline = pipeline
        self._active = False
        self._segments: list[Path] = []

    @property
    def is_recording(self) -> bool:
        return self._active

    def on_segment_finalized(self, path: Path) -> None:
        if self._active:
            self._segments.append(Path(path))

    def start(self) -> None:
        if self._active:
            return
        # Begin a fresh segment boundary so the take starts cleanly on a keyframe.
        self._pipeline.force_split()
        self._segments = []
        self._active = True

    def stop(self, output_path: Path) -> Path:
        if not self._active:
            raise RuntimeError("manual recorder is not active")
        self._pipeline.force_split()     # flush the final in-progress segment
        self._active = False
        segments = [p for p in self._segments if p.exists()]
        if not segments:
            raise RuntimeError("no segments captured for manual recording")
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
