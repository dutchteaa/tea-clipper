"""Live mic-input level meter for the settings UI.

Pure helpers (``peak_to_display_db``, ``db_to_fraction``) are unit-tested.
``MicLevelMonitor`` runs a standalone ``pipewiresrc … ! level`` pipeline polled from a
Qt timer (no GLib loop) and is probe-verified. ``LevelMeterBar`` paints the live level
plus the gate-threshold marker.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from tea_clipper.audio import AudioDevice

log = logging.getLogger("tea_clipper")


def peak_to_display_db(peaks: list[float], floor: float = -60.0) -> float:
    """Loudest channel peak (dB), clamped to ``floor``; ``floor`` for no data."""
    if not peaks:
        return floor
    return max(floor, max(peaks))


def db_to_fraction(db: float, floor: float = -60.0, ceil: float = 0.0) -> float:
    """Map a dB value to a bar position in [0.0, 1.0] over the [floor, ceil] scale."""
    if ceil <= floor:
        return 0.0
    return min(1.0, max(0.0, (db - floor) / (ceil - floor)))


def _build_monitor_launch(mics: list[AudioDevice]) -> str | None:
    """gst-launch string: each mic -> audiomixer -> level -> fakesink. None if no mics."""
    if not mics:
        return None
    chains = [
        f"pipewiresrc target-object={m.node_name} ! audioconvert ! amix."
        for m in mics
    ]
    chains.append(
        "audiomixer name=amix ! audioconvert ! "
        "level interval=50000000 post-messages=true ! fakesink sync=false"
    )
    return " ".join(chains)


class MicLevelMonitor(QObject):
    """Run a standalone mic-metering pipeline; emit the live peak dB ~20x/sec.

    Lives entirely on the Qt main thread: the GStreamer bus is polled by a QTimer, so no
    GLib main loop is needed. A second pipewiresrc on the mic alongside capture is fine
    (PipeWire allows multiple readers). Degrades to silent if no mic / build fails.
    """

    level_changed = Signal(float)

    def __init__(self, mics: list[AudioDevice], parent=None) -> None:
        super().__init__(parent)
        self._launch = _build_monitor_launch(mics)
        self._pipeline = None
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        if self._launch is None or self._pipeline is not None:
            return
        try:
            from gi.repository import Gst

            from tea_clipper.gst_init import ensure_gst

            ensure_gst()
            self._pipeline = Gst.parse_launch(self._launch)
            self._pipeline.set_state(Gst.State.PLAYING)
        except Exception:
            log.exception("mic level monitor failed to start")
            self._pipeline = None
            return
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self._pipeline is not None:
            from gi.repository import Gst

            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None

    def _poll(self) -> None:
        if self._pipeline is None:
            return
        from gi.repository import Gst

        bus = self._pipeline.get_bus()
        msg = bus.pop_filtered(Gst.MessageType.ELEMENT)
        while msg is not None:
            st = msg.get_structure()
            if st is not None and st.get_name() == "level":
                peaks = list(st.get_value("peak") or [])
                self.level_changed.emit(peak_to_display_db(peaks))
            msg = bus.pop_filtered(Gst.MessageType.ELEMENT)


class LevelMeterBar(QWidget):
    """Horizontal bar: live mic level fill + a marker line at the gate threshold.

    Drawn as a bordered, inset track so the meter area stays visible on any desktop
    theme even when empty (a borderless dark bar blends into a dark window background).
    The region left of the marker reads as "would be gated" (grey); past it is green
    ("passes"). Scale is fixed at [-60, 0] dB to match the meter helpers' defaults.
    """

    _TRACK = QColor("#15171a")     # inset well, distinct from typical window backgrounds
    _BORDER = QColor("#6b7079")    # mid grey: visible on both light and dark themes
    _BELOW = QColor("#8a8f98")     # signal below threshold (would be gated)
    _ABOVE = QColor("#3fb950")     # signal above threshold (passes)
    _MARKER = QColor("#f0a000")    # gate-threshold marker

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._level_db = -60.0
        self._threshold_db = -40.0
        self.setMinimumHeight(22)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_level(self, db: float) -> None:
        self._level_db = db
        self.update()

    def set_threshold(self, db: float) -> None:
        self._threshold_db = db
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, self._TRACK)

        inner_w = max(w - 2, 0)
        inner_h = max(h - 2, 0)
        level_x = int(db_to_fraction(self._level_db) * inner_w)
        thr_x = int(db_to_fraction(self._threshold_db) * inner_w)

        # Filled level: grey below threshold ("gated"), green above ("passes").
        painter.fillRect(1, 1, min(level_x, thr_x), inner_h, self._BELOW)
        if level_x > thr_x:
            painter.fillRect(1 + thr_x, 1, level_x - thr_x, inner_h, self._ABOVE)

        # Threshold marker line.
        painter.fillRect(1 + max(thr_x - 1, 0), 1, 2, inner_h, self._MARKER)

        # Border last so the meter's extent is always legible.
        painter.setPen(self._BORDER)
        painter.drawRect(0, 0, w - 1, h - 1)
        painter.end()
