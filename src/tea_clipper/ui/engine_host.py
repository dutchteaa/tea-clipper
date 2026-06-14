"""Owns the engine on a GLib worker thread; bridges to Qt via signals."""

from __future__ import annotations

import threading
from pathlib import Path

from gi.repository import GLib
from PySide6.QtCore import QObject, Signal

from tea_clipper.controller import build_controller


class EngineHost(QObject):
    """Build/run the Controller on a worker thread; marshal actions + emit Qt signals.

    state_changed(state, detail): "Idle" | "Starting" | "Recording" | "Restarting" | "Error".
    clip_saved(path): a clip or recording was finalized (hotkey- or UI-triggered).
    """

    state_changed = Signal(str, str)
    clip_saved = Signal(str)

    def __init__(self, settings, config_path, builder=build_controller, dispatch=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._config_path = Path(config_path)
        self._builder = builder
        self._dispatch_fn = dispatch or GLib.idle_add
        self._controller = None
        self._thread = None
        self._state = "Idle"

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        self.state_changed.emit(state, detail)

    def _on_clip_saved(self, path: str) -> None:
        self.clip_saved.emit(path)

    def _bring_up(self) -> None:
        """Build + start the controller. Runs on the worker thread (sync in tests)."""
        try:
            self._set_state("Starting")
            self._controller = self._builder(self._settings, clip_saved_cb=self._on_clip_saved)
            self._settings.save(self._config_path)
            self._controller.start()
            self._set_state("Recording")
        except Exception as exc:  # portal denial / encoder failure / build error
            self._controller = None
            self._set_state("Error", str(exc))

    def _run(self) -> None:
        self._bring_up()
        if self._controller is not None:
            self._controller.run()  # blocks on GLib.MainLoop until stop()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        controller = self._controller
        if controller is not None:
            controller.stop()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._controller = None
        self._set_state("Idle")

    def restart(self) -> None:
        self._set_state("Restarting")
        self.stop()
        self.start()

    def apply_settings(self, settings) -> None:
        self._settings = settings
        self.restart()

    def repick_source(self) -> None:
        self._settings.source_restore_token = ""
        self.stop()
        self.start()

    def _dispatch(self, fn) -> None:
        self._dispatch_fn(fn)

    def save_clip(self) -> None:
        controller = self._controller
        if controller is not None:
            self._dispatch(controller.save_clip)

    def toggle_record(self) -> None:
        controller = self._controller
        if controller is not None:
            self._dispatch(controller.toggle_record)
