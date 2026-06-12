"""App lifecycle: wire capture + buffer + recorder + hotkeys into a runnable daemon."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path

from gi.repository import GLib

from tea_clipper.hotkeys import SAVE_CLIP, TOGGLE_RECORD

log = logging.getLogger("tea_clipper")


def compute_max_segments(settings) -> int:
    """Rolling-buffer segment count: cover the clip length plus a small margin."""
    return math.ceil(settings.clip_length_seconds / settings.segment_seconds) + 2


class Controller:
    """Owns the app lifecycle and routes hotkeys to engine actions.

    Holds already-built collaborators; build_controller() wires the real ones.
    """

    def __init__(
        self, settings, pipeline, replay_buffer, manual_recorder, hotkey_service, portal=None
    ) -> None:
        self._settings = settings
        self._pipeline = pipeline
        self._replay = replay_buffer
        self._recorder = manual_recorder
        self._hotkeys = hotkey_service
        self._portal = portal
        self._loop = None
        self.last_clip = None

    def _output_path(self, prefix: str) -> Path:
        out_dir = Path(self._settings.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.mkv"

    def _on_save_clip(self) -> None:
        try:
            out = self._output_path("clip")
            self.last_clip = self._replay.save_last(
                self._settings.clip_length_seconds, out, self._pipeline
            )
            log.info("saved clip: %s", self.last_clip)
        except Exception:
            log.exception("failed to save clip")

    def _on_toggle_record(self) -> None:
        try:
            if self._recorder.is_recording:
                self.last_clip = self._recorder.stop(self._output_path("recording"))
                log.info("stopped recording: %s", self.last_clip)
            else:
                self._recorder.start()
                log.info("started recording")
        except Exception:
            log.exception("failed to toggle recording")

    def start(self) -> None:
        self._hotkeys.add_listener(SAVE_CLIP, self._on_save_clip)
        self._hotkeys.add_listener(TOGGLE_RECORD, self._on_toggle_record)
        self._pipeline.start()
        self._hotkeys.start(run_loop=False)  # share this Controller's main loop

    def run(self) -> None:
        self._loop = GLib.MainLoop()
        self._loop.run()

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.quit()
            self._loop = None
        self._hotkeys.stop()
        self._pipeline.stop()
        if self._portal is not None:
            self._portal.close()
