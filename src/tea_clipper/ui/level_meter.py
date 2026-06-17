"""Live mic-input level meter for the settings UI.

Pure helpers (``peak_to_display_db``, ``db_to_fraction``) are unit-tested.
``MicLevelMonitor`` runs a standalone ``pipewiresrc … ! level`` pipeline polled from a
Qt timer (no GLib loop) and is probe-verified. ``LevelMeterBar`` paints the live level
plus the gate-threshold marker.
"""

from __future__ import annotations

import logging

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
