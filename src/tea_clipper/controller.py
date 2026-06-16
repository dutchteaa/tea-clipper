"""App lifecycle: wire capture + buffer + recorder + hotkeys into a runnable daemon."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path

from gi.repository import GLib

from tea_clipper.hotkeys import SAVE_CLIP, TOGGLE_RECORD, HotkeyService

log = logging.getLogger("tea_clipper")


def compute_max_segments(settings) -> int:
    """Rolling-buffer segment count: cover the clip length plus a small margin."""
    return math.ceil(settings.clip_length_seconds / settings.segment_seconds) + 2


class Controller:
    """Owns the app lifecycle and routes hotkeys to engine actions.

    Holds already-built collaborators; build_controller() wires the real ones.
    """

    def __init__(
        self, settings, pipeline, replay_buffer, manual_recorder, hotkey_service,
        portal=None, clip_saved_cb=None, recording_changed_cb=None,
    ) -> None:
        self._settings = settings
        self._pipeline = pipeline
        self._replay = replay_buffer
        self._recorder = manual_recorder
        self._hotkeys = hotkey_service
        self._portal = portal
        self._clip_saved_cb = clip_saved_cb
        self._recording_changed_cb = recording_changed_cb
        self._loop = None
        self.last_clip = None

    def _output_path(self, prefix: str) -> Path:
        out_dir = Path(self._settings.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.mkv"

    def _notify_saved(self) -> None:
        if self._clip_saved_cb is not None and self.last_clip is not None:
            try:
                self._clip_saved_cb(str(self.last_clip))
            except Exception:
                log.exception("clip_saved_cb raised")

    def _notify_recording(self, recording: bool) -> None:
        if self._recording_changed_cb is not None:
            try:
                self._recording_changed_cb(recording)
            except Exception:
                log.exception("recording_changed_cb raised")

    def save_clip(self) -> None:
        try:
            out = self._output_path("clip")
            self.last_clip = self._replay.save_last(
                self._settings.clip_length_seconds, out, self._pipeline
            )
            log.info("saved clip: %s", self.last_clip)
            self._notify_saved()
        except Exception:
            log.exception("failed to save clip")

    def toggle_record(self) -> None:
        try:
            if self._recorder.is_recording:
                self.last_clip = self._recorder.stop(self._output_path("recording"))
                log.info("stopped recording: %s", self.last_clip)
                self._notify_recording(False)
                self._notify_saved()
            else:
                self._recorder.start()
                log.info("started recording")
                self._notify_recording(True)
        except Exception:
            log.exception("failed to toggle recording")

    def start(self) -> None:
        self._hotkeys.add_listener(SAVE_CLIP, self.save_clip)
        self._hotkeys.add_listener(TOGGLE_RECORD, self.toggle_record)
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


def build_controller(settings, portal=None, clip_saved_cb=None, recording_changed_cb=None) -> Controller:
    """Wire the real components: portal capture → pipeline → buffer + recorder → hotkeys."""
    from tea_clipper.audio import (
        build_audio_fragment,
        discover_audio_devices,
        resolve_audio_devices,
    )
    from tea_clipper.encoders import EncoderRegistry
    from tea_clipper.manual_recorder import ManualRecorder
    from tea_clipper.pipeline import CapturePipeline
    from tea_clipper.portal import PortalManager
    from tea_clipper.replay_buffer import ReplayBuffer

    if portal is None:
        portal = PortalManager(settings)
    video = portal.open()
    devices = resolve_audio_devices(settings, discover_audio_devices())
    audio = build_audio_fragment(devices)
    spec = EncoderRegistry().resolve(
        settings.codec, hardware=settings.hardware, bitrate_kbps=settings.bitrate_kbps,
        fps=settings.fps, segment_seconds=settings.segment_seconds,
    )
    pipeline = CapturePipeline(
        source_desc=(video, audio), encoder=spec, buffer_dir=settings.buffer_dir,
        segment_seconds=settings.segment_seconds, max_segments=compute_max_segments(settings),
    )
    replay = ReplayBuffer(segment_seconds=settings.segment_seconds)
    recorder = ManualRecorder(pipeline=pipeline)
    pipeline.add_segment_listener(replay.on_segment_finalized)
    pipeline.add_segment_listener(recorder.on_segment_finalized)
    hotkeys = HotkeyService()
    return Controller(
        settings, pipeline, replay, recorder, hotkeys,
        portal=portal, clip_saved_cb=clip_saved_cb,
        recording_changed_cb=recording_changed_cb,
    )
