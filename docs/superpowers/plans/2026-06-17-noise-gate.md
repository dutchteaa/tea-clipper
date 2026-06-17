# Mic Noise Gate + Live Input Meter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a downward noise gate to the microphone capture chain(s), with a dB threshold configurable in the settings UI alongside a live mic-input meter so the user can place the threshold just above their idle noise floor.

**Architecture:** A pure dB→linear helper feeds an `audiodynamic mode=expander ratio=2` element inserted only on mic chains in `audio.build_audio_fragment`. Two new `Settings` fields drive it. The settings UI gains a checkbox + dB spinbox and a `LevelMeterBar` fed by a `MicLevelMonitor` (a standalone `pipewiresrc … ! level` pipeline polled from a Qt `QTimer`, running only while the window is visible).

**Tech Stack:** Python 3.12+, GStreamer via PyGObject (`audiodynamic`, `level`), PySide6 (Qt 6), pytest. Pure/orchestration logic is unit-tested; live GStreamer/PipeWire code is probe-verified (the project's established split).

## Global Constraints

- Python 3.12+; match surrounding code style (readable Python; the hot path is in GStreamer).
- No new runtime dependencies — `audiodynamic` and `level` ship in the already-required GStreamer plugin set.
- `Settings.load` drops unknown keys; new fields must have defaults so old configs forward-compat (gate off).
- Engine mechanism (empirically verified on target hardware): `audiodynamic mode=expander ratio=2 threshold=<linear 0..1>`; `threshold=0` = off; `ratio=2` fully silences below-threshold; `linear = 10 ** (db / 20)`.
- Gate is **mic-only** (`not device.is_monitor`); desktop sinks and the `gate_threshold == 0` case must produce byte-for-byte the same fragment as today (existing `tests/test_audio.py` stays green).
- Run the suite with `.venv/bin/pytest`. Unit tests run offscreen via the `qapp` conftest fixture; engine tests are gated by `requires_engine`.
- Commit after each task.

---

### Task 1: Settings fields

**Files:**
- Modify: `src/tea_clipper/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings.mic_noise_gate_enabled: bool` (default `False`), `Settings.mic_noise_gate_db: float` (default `-40.0`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings.py`:

```python
def test_noise_gate_defaults():
    s = Settings()
    assert s.mic_noise_gate_enabled is False
    assert s.mic_noise_gate_db == -40.0


def test_noise_gate_round_trip(tmp_path: Path):
    s = Settings(mic_noise_gate_enabled=True, mic_noise_gate_db=-32.0)
    cfg = tmp_path / "config.toml"
    s.save(cfg)
    loaded = Settings.load(cfg)
    assert loaded.mic_noise_gate_enabled is True
    assert loaded.mic_noise_gate_db == -32.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_settings.py::test_noise_gate_defaults -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument` / `AttributeError`.

- [ ] **Step 3: Add the fields**

In `src/tea_clipper/settings.py`, after the `skipped_update_version` field:

```python
    skipped_update_version: str = ""   # release tag the user chose to skip
    mic_noise_gate_enabled: bool = False
    mic_noise_gate_db: float = -40.0   # gate threshold in dBFS (applied to mic chains)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: PASS (all settings tests).

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/settings.py tests/test_settings.py
git commit -m "feat: add mic_noise_gate settings fields"
```

---

### Task 2: dB→linear helper + gate insertion in `audio.py`

**Files:**
- Modify: `src/tea_clipper/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Consumes: `Settings.mic_noise_gate_enabled`, `Settings.mic_noise_gate_db` (Task 1) — via duck-typed `_SettingsLike`.
- Produces:
  - `gate_threshold_linear(db: float) -> float` — `10 ** (db/20)` clamped to `[0.0, 1.0]`.
  - `resolve_gate_threshold(settings) -> float` — `gate_threshold_linear(settings.mic_noise_gate_db)` if enabled else `0.0`.
  - `build_audio_fragment(devices, gate_threshold: float = 0.0) -> str | None` — gate param threaded to mic chains.
  - `_device_fragment(device, gate_threshold: float = 0.0) -> str`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_audio.py`:

```python
from tea_clipper.audio import gate_threshold_linear, resolve_gate_threshold


def test_gate_threshold_linear_known_points():
    assert gate_threshold_linear(0.0) == 1.0
    assert abs(gate_threshold_linear(-40.0) - 0.01) < 1e-6
    assert abs(gate_threshold_linear(-20.0) - 0.1) < 1e-6


def test_gate_threshold_linear_clamped():
    assert gate_threshold_linear(60.0) == 1.0        # never above 1.0
    assert gate_threshold_linear(-1000.0) >= 0.0     # never below 0.0


def test_resolve_gate_threshold_disabled_is_zero():
    s = _S([])
    s.mic_noise_gate_enabled = False
    s.mic_noise_gate_db = -40.0
    assert resolve_gate_threshold(s) == 0.0


def test_resolve_gate_threshold_enabled_is_linear():
    s = _S([])
    s.mic_noise_gate_enabled = True
    s.mic_noise_gate_db = -40.0
    assert abs(resolve_gate_threshold(s) - 0.01) < 1e-6


def test_gate_inserted_on_mic_chain_only():
    frag = build_audio_fragment([_mic("mic.node")], gate_threshold=0.01)
    assert "audiodynamic mode=expander" in frag
    assert "ratio=2" in frag


def test_gate_not_inserted_on_sink_chain():
    frag = build_audio_fragment([_sink("sink.node")], gate_threshold=0.01)
    assert "audiodynamic" not in frag


def test_gate_absent_when_threshold_zero():
    frag = build_audio_fragment([_mic("mic.node")], gate_threshold=0.0)
    assert "audiodynamic" not in frag


def test_gate_only_on_mic_in_mixed_set():
    frag = build_audio_fragment(
        [_sink("sink.node"), _mic("mic.node")], gate_threshold=0.05
    )
    assert frag.count("audiodynamic") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_audio.py -k "gate" -v`
Expected: FAIL — `ImportError: cannot import name 'gate_threshold_linear'`.

- [ ] **Step 3: Implement the helpers and gate insertion**

In `src/tea_clipper/audio.py`, add after the imports/constants (near `MIC_TOKEN`):

```python
def gate_threshold_linear(db: float) -> float:
    """Convert a dBFS gate threshold to a linear amplitude in [0.0, 1.0]."""
    return min(1.0, max(0.0, 10 ** (db / 20)))
```

Replace `_device_fragment` with:

```python
def _device_fragment(device: AudioDevice, gate_threshold: float = 0.0) -> str:
    """One ``pipewiresrc`` capture chain feeding the shared ``audiomixer``.

    Desktop (sink) devices need ``stream.capture.sink=true`` so pipewiresrc taps the sink's
    monitor ports rather than treating it as a (silent) regular source. Mic (source) chains
    get a downward noise gate (``audiodynamic mode=expander``) when ``gate_threshold > 0``.
    """
    props = ""
    if device.is_monitor:
        props = ' stream-properties="props,stream.capture.sink=true"'
    gate = ""
    if not device.is_monitor and gate_threshold > 0:
        gate = f"audiodynamic mode=expander threshold={gate_threshold:.6f} ratio=2 ! "
    return (
        f"pipewiresrc target-object={device.node_name}{props} ! "
        f"audioconvert ! {gate}audioresample ! queue ! amix."
    )
```

Update `build_audio_fragment`'s signature and chain build:

```python
def build_audio_fragment(
    devices: list[AudioDevice], gate_threshold: float = 0.0
) -> str | None:
    """Capture each device and mix them via ``audiomixer``; ``None`` if no devices.

    ``gate_threshold`` (linear amplitude, 0.0 = off) applies a noise gate to mic chains only.
    The returned fragment ends in ``queue name=aenc_in`` so the pipeline can append
    ``! opusenc ! replaymux.audio_0`` exactly as it does for the test source. The mixer
    output is pinned to stereo so a mono mic doesn't collapse desktop audio to mono.
    """
    if not devices:
        return None
    chains = [_device_fragment(d, gate_threshold) for d in devices]
    chains.append(
        "audiomixer name=amix ! audioconvert ! audioresample ! "
        "audio/x-raw,channels=2 ! queue name=aenc_in"
    )
    return " ".join(chains)
```

Add `mic_noise_gate_enabled`/`mic_noise_gate_db` to the `_SettingsLike` Protocol and add `resolve_gate_threshold`:

```python
class _SettingsLike(Protocol):
    audio_devices: list[str]
    mic_noise_gate_enabled: bool
    mic_noise_gate_db: float


def resolve_gate_threshold(settings: _SettingsLike) -> float:
    """Linear gate threshold from settings; 0.0 when the gate is disabled."""
    if not settings.mic_noise_gate_enabled:
        return 0.0
    return gate_threshold_linear(settings.mic_noise_gate_db)
```

> Note: the existing `test_audio.py` helper class `_S` only sets `audio_devices`. The new `resolve_gate_threshold` tests set `mic_noise_gate_enabled`/`mic_noise_gate_db` as attributes on the `_S` instance directly (shown in Step 1), so no `_S` change is required. `resolve_audio_devices` still only reads `audio_devices`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_audio.py -v`
Expected: PASS — new gate tests pass AND all pre-existing fragment tests (sink capture-sink, stereo pin, etc.) still pass.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/audio.py tests/test_audio.py
git commit -m "feat: noise-gate helpers and mic-chain gate insertion"
```

---

### Task 3: Wire the gate into `build_controller`

**Files:**
- Modify: `src/tea_clipper/controller.py:107-124`
- Test: none new (build_controller does live portal I/O and is probe-verified; the gate math is unit-tested in Task 2). Verification = full suite stays green.

**Interfaces:**
- Consumes: `resolve_gate_threshold` and `build_audio_fragment(devices, gate_threshold=…)` (Task 2).

- [ ] **Step 1: Update the import and the audio wiring**

In `src/tea_clipper/controller.py`, change the `from tea_clipper.audio import (...)` block to also import `resolve_gate_threshold`:

```python
    from tea_clipper.audio import (
        build_audio_fragment,
        discover_audio_devices,
        resolve_audio_devices,
        resolve_gate_threshold,
    )
```

Then change the two audio lines:

```python
    devices = resolve_audio_devices(settings, discover_audio_devices())
    audio = build_audio_fragment(devices, gate_threshold=resolve_gate_threshold(settings))
```

- [ ] **Step 2: Run the full suite to verify nothing regressed**

Run: `.venv/bin/pytest`
Expected: PASS — same count as before this task plus Tasks 1–2 additions; no import errors.

- [ ] **Step 3: Commit**

```bash
git add src/tea_clipper/controller.py
git commit -m "feat: apply mic noise gate in build_controller"
```

---

### Task 4: Level-meter pure helpers (`ui/level_meter.py`)

**Files:**
- Create: `src/tea_clipper/ui/level_meter.py`
- Test: `tests/test_level_meter.py`

**Interfaces:**
- Produces:
  - `peak_to_display_db(peaks: list[float], floor: float = -60.0) -> float` — max peak across channels, clamped to `floor`; returns `floor` for empty input.
  - `db_to_fraction(db: float, floor: float = -60.0, ceil: float = 0.0) -> float` — bar position in `[0.0, 1.0]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_level_meter.py`:

```python
from tea_clipper.ui.level_meter import db_to_fraction, peak_to_display_db


def test_peak_empty_returns_floor():
    assert peak_to_display_db([]) == -60.0


def test_peak_takes_max_channel():
    assert peak_to_display_db([-40.0, -12.0]) == -12.0


def test_peak_clamped_to_floor():
    assert peak_to_display_db([-90.0]) == -60.0


def test_fraction_endpoints():
    assert db_to_fraction(-60.0) == 0.0
    assert db_to_fraction(0.0) == 1.0


def test_fraction_midpoint():
    assert abs(db_to_fraction(-30.0) - 0.5) < 1e-6


def test_fraction_clamped():
    assert db_to_fraction(-100.0) == 0.0
    assert db_to_fraction(12.0) == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_level_meter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tea_clipper.ui.level_meter'`.

- [ ] **Step 3: Create the module with the pure helpers**

Create `src/tea_clipper/ui/level_meter.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_level_meter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/ui/level_meter.py tests/test_level_meter.py
git commit -m "feat: level-meter pure helpers"
```

---

### Task 5: `MicLevelMonitor` (live pipeline + Qt-polled level)

**Files:**
- Modify: `src/tea_clipper/ui/level_meter.py`
- Test: `tests/test_level_meter.py`

**Interfaces:**
- Consumes: `AudioDevice` (`tea_clipper.audio`), `ensure_gst` (`tea_clipper.gst_init`), `peak_to_display_db` (Task 4).
- Produces:
  - `_build_monitor_launch(mics: list[AudioDevice]) -> str | None` — gst-launch string for mic metering, or `None` if no mics.
  - `MicLevelMonitor(QObject)` with `level_changed = Signal(float)`, `start()`, `stop()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_level_meter.py`:

```python
from tea_clipper.audio import AudioDevice
from tea_clipper.ui.level_meter import MicLevelMonitor, _build_monitor_launch


def _mic(name):
    return AudioDevice(name, name, is_monitor=False, is_default=False)


def test_monitor_launch_none_without_mics():
    assert _build_monitor_launch([]) is None


def test_monitor_launch_builds_level_pipeline():
    launch = _build_monitor_launch([_mic("mic.a")])
    assert "pipewiresrc target-object=mic.a" in launch
    assert "level" in launch
    assert "post-messages=true" in launch
    assert "audiomixer name=amix" in launch


def test_monitor_launch_one_chain_per_mic():
    launch = _build_monitor_launch([_mic("mic.a"), _mic("mic.b")])
    assert launch.count("pipewiresrc") == 2


def test_monitor_start_is_noop_without_mics(qapp):
    # No mics -> launch is None -> start()/stop() must not raise and must not build a pipeline.
    mon = MicLevelMonitor([])
    mon.start()
    assert mon._pipeline is None
    mon.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_level_meter.py -k "monitor" -v`
Expected: FAIL — `ImportError: cannot import name 'MicLevelMonitor'`.

- [ ] **Step 3: Implement the monitor**

Append to `src/tea_clipper/ui/level_meter.py` (add imports at top of file):

```python
from PySide6.QtCore import QObject, QTimer, Signal

from tea_clipper.audio import AudioDevice
```

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_level_meter.py -v`
Expected: PASS (the no-mic start path never touches GStreamer, so it runs headlessly).

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/ui/level_meter.py tests/test_level_meter.py
git commit -m "feat: MicLevelMonitor live metering pipeline"
```

---

### Task 6: `LevelMeterBar` widget

**Files:**
- Modify: `src/tea_clipper/ui/level_meter.py`
- Test: `tests/test_level_meter.py`

**Interfaces:**
- Consumes: `db_to_fraction` (Task 4).
- Produces: `LevelMeterBar(QWidget)` with `set_level(db: float)`, `set_threshold(db: float)`, properties `_level_db`, `_threshold_db`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_level_meter.py`:

```python
from tea_clipper.ui.level_meter import LevelMeterBar


def test_meter_bar_stores_level(qapp):
    bar = LevelMeterBar()
    bar.set_level(-18.0)
    assert bar._level_db == -18.0


def test_meter_bar_stores_threshold(qapp):
    bar = LevelMeterBar()
    bar.set_threshold(-35.0)
    assert bar._threshold_db == -35.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_level_meter.py -k "meter_bar" -v`
Expected: FAIL — `ImportError: cannot import name 'LevelMeterBar'`.

- [ ] **Step 3: Implement the widget**

Add to the top-of-file imports in `src/tea_clipper/ui/level_meter.py`:

```python
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget
```

Append:

```python
class LevelMeterBar(QWidget):
    """Horizontal bar: live mic level fill + a marker line at the gate threshold.

    The region left of the marker reads as "would be gated" (greyed). Scale is fixed
    at [-60, 0] dB to match the meter helpers' defaults.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._level_db = -60.0
        self._threshold_db = -40.0
        self.setMinimumHeight(18)

    def set_level(self, db: float) -> None:
        self._level_db = db
        self.update()

    def set_threshold(self, db: float) -> None:
        self._threshold_db = db
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#222"))

        level_x = int(db_to_fraction(self._level_db) * w)
        thr_x = int(db_to_fraction(self._threshold_db) * w)

        # Filled level: greyed below threshold ("gated"), green above.
        painter.fillRect(0, 0, min(level_x, thr_x), h, QColor("#555"))
        if level_x > thr_x:
            painter.fillRect(thr_x, 0, level_x - thr_x, h, QColor("#2e9e2e"))

        # Threshold marker line.
        painter.fillRect(max(thr_x - 1, 0), 0, 2, h, QColor("#e0a800"))
        painter.end()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_level_meter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/ui/level_meter.py tests/test_level_meter.py
git commit -m "feat: LevelMeterBar widget"
```

---

### Task 7: SettingsForm gate controls + meter wiring

**Files:**
- Modify: `src/tea_clipper/ui/settings_form.py`
- Test: `tests/test_settings_form.py`

**Interfaces:**
- Consumes: `LevelMeterBar`, `MicLevelMonitor` (Tasks 5–6); `resolve_audio_devices`, `discover_audio_devices` (`tea_clipper.audio`).
- Produces: `SettingsForm` gains `gate_enabled` (QCheckBox), `gate_db` (QSpinBox), `meter` (LevelMeterBar), `start_metering()`, `stop_metering()`, and an injectable `monitor_factory` (default `MicLevelMonitor`). `load`/`collect` round-trip `mic_noise_gate_enabled` + `mic_noise_gate_db`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings_form.py`:

```python
def test_noise_gate_round_trip(qapp):
    s = Settings(mic_noise_gate_enabled=True, mic_noise_gate_db=-30.0)
    form = _form()
    form.load(s)
    out = form.collect()
    assert out.mic_noise_gate_enabled is True
    assert out.mic_noise_gate_db == -30.0


def test_gate_db_disabled_when_gate_off(qapp):
    s = Settings(mic_noise_gate_enabled=False)
    form = _form()
    form.load(s)
    assert form.gate_db.isEnabled() is False


def test_threshold_marker_follows_spinbox(qapp):
    form = _form()
    form.gate_db.setValue(-25)
    assert form.meter._threshold_db == -25.0


def test_start_metering_uses_factory(qapp):
    from PySide6.QtCore import QObject, Signal

    created = {}

    # The fake must expose a real Qt Signal so `level_changed.connect(...)` works.
    class FakeMonitor(QObject):
        level_changed = Signal(float)

        def __init__(self, mics, parent=None):
            super().__init__(parent)
            created["mics"] = mics
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

    form = SettingsForm(
        codecs=["h264"],
        devices=[AudioDevice("mic.x", "Mic X", is_monitor=False, is_default=True)],
        monitor_factory=FakeMonitor,
    )
    form.load(Settings(audio_devices=["@mic@"]))
    form.start_metering()
    assert created["mics"][0].node_name == "mic.x"
    assert form._monitor.started is True
    form.stop_metering()
    assert form._monitor is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_settings_form.py -k "gate or metering or marker" -v`
Expected: FAIL — `AttributeError: 'SettingsForm' object has no attribute 'gate_enabled'` / unexpected `monitor_factory` kwarg.

- [ ] **Step 3: Update SettingsForm**

In `src/tea_clipper/ui/settings_form.py`:

Update imports:

```python
from tea_clipper.audio import AudioDevice, discover_audio_devices, resolve_audio_devices
from tea_clipper.settings import Settings
from tea_clipper.ui.audio_picker import AudioPicker
from tea_clipper.ui.level_meter import LevelMeterBar, MicLevelMonitor
```

Change `__init__` signature and body. Discover devices once (shared with the picker and the meter), add the gate widgets, and store the monitor factory:

```python
    def __init__(
        self,
        codecs: list[str] | None = None,
        devices: list[AudioDevice] | None = None,
        monitor_factory=MicLevelMonitor,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if codecs is None:
            from tea_clipper.encoders import EncoderRegistry

            codecs = EncoderRegistry().available_codecs()
        if devices is None:
            devices = discover_audio_devices()
        self._devices = devices
        self._monitor_factory = monitor_factory
        self._monitor = None
        self._base = Settings()

        self.clip_length = _spin(1, 600, self._base.clip_length_seconds)
        self.codec = QComboBox()
        self.codec.addItems(codecs)
        self.hardware = QCheckBox("Use hardware encoder (VAAPI)")
        self.bitrate = _spin(500, 200000, self._base.bitrate_kbps)
        self.fps = _spin(1, 240, self._base.fps)
        self.output_dir = QLineEdit(self._base.output_dir)
        self.audio = AudioPicker(devices=devices)

        self.gate_enabled = QCheckBox("Enable noise gate (mic)")
        self.gate_db = _spin(-60, -10, int(round(self._base.mic_noise_gate_db)))
        self.meter = LevelMeterBar()
        self.gate_enabled.toggled.connect(self.gate_db.setEnabled)
        self.gate_db.valueChanged.connect(
            lambda v: self.meter.set_threshold(float(v))
        )
        self.gate_db.setEnabled(self.gate_enabled.isChecked())
        self.meter.set_threshold(float(self.gate_db.value()))

        layout = QFormLayout(self)
        layout.addRow("Clip length (s)", self.clip_length)
        layout.addRow("Codec", self.codec)
        layout.addRow("", self.hardware)
        layout.addRow("Bitrate (kbps)", self.bitrate)
        layout.addRow("FPS", self.fps)
        layout.addRow("Output folder", self.output_dir)
        layout.addRow("Audio sources", self.audio)
        layout.addRow("", self.gate_enabled)
        layout.addRow("Gate threshold (dB)", self.gate_db)
        layout.addRow("Mic level", self.meter)
```

Update `load` (add the two fields + keep the marker in sync):

```python
    def load(self, settings: Settings) -> None:
        self._base = settings
        self.clip_length.setValue(settings.clip_length_seconds)
        self._select_codec(settings.codec)
        self.hardware.setChecked(settings.hardware)
        self.bitrate.setValue(settings.bitrate_kbps)
        self.fps.setValue(settings.fps)
        self.output_dir.setText(settings.output_dir)
        self.audio.set_selection(settings.audio_devices)
        self.gate_enabled.setChecked(settings.mic_noise_gate_enabled)
        self.gate_db.setValue(int(round(settings.mic_noise_gate_db)))
        self.gate_db.setEnabled(settings.mic_noise_gate_enabled)
        self.meter.set_threshold(float(self.gate_db.value()))
```

Update `collect`:

```python
    def collect(self) -> Settings:
        return replace(
            self._base,
            clip_length_seconds=self.clip_length.value(),
            codec=self.codec.currentText(),
            hardware=self.hardware.isChecked(),
            bitrate_kbps=self.bitrate.value(),
            fps=self.fps.value(),
            output_dir=self.output_dir.text(),
            audio_devices=self.audio.selected_entries(),
            mic_noise_gate_enabled=self.gate_enabled.isChecked(),
            mic_noise_gate_db=float(self.gate_db.value()),
        )
```

Add the metering lifecycle methods (after `collect`):

```python
    def start_metering(self) -> None:
        """Begin live mic metering for the currently-selected mics (no-op if running)."""
        if self._monitor is not None:
            return
        mics = [
            d for d in resolve_audio_devices(self._base, self._devices)
            if not d.is_monitor
        ]
        self._monitor = self._monitor_factory(mics)
        self._monitor.level_changed.connect(self.meter.set_level)
        self._monitor.start()

    def stop_metering(self) -> None:
        """Tear down the metering pipeline (no-op if not running)."""
        if self._monitor is None:
            return
        self._monitor.stop()
        self._monitor = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_settings_form.py -v`
Expected: PASS — new gate/metering tests AND the existing round-trip/preserve tests.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/ui/settings_form.py tests/test_settings_form.py
git commit -m "feat: settings-form noise-gate controls + mic meter wiring"
```

---

### Task 8: Start/stop metering on window show/hide

**Files:**
- Modify: `src/tea_clipper/ui/main_window.py`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `SettingsForm.start_metering()` / `stop_metering()` (Task 7).
- Produces: `MainWindow.showEvent` / `hideEvent` drive form metering.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main_window.py` (follow the file's existing host-fake pattern; if it builds a `MainWindow`, reuse that helper). Minimal additions:

```python
def test_show_starts_and_hide_stops_metering(qapp, monkeypatch):
    import tea_clipper.ui.main_window as mw
    calls = []

    # Patch SettingsForm.start/stop_metering to record calls without real GStreamer.
    monkeypatch.setattr(mw.SettingsForm, "start_metering", lambda self: calls.append("start"))
    monkeypatch.setattr(mw.SettingsForm, "stop_metering", lambda self: calls.append("stop"))

    window = _make_window()  # existing helper in this test file
    window.showEvent(_FakeEvent())
    window.hideEvent(_FakeEvent())
    assert calls == ["start", "stop"]
```

If the test file has no `_make_window` / `_FakeEvent` helpers, add:

```python
class _FakeEvent:
    def ignore(self): pass
    def accept(self): pass
```

and construct the window the same way the existing `MainWindow` tests in this file do (with their fake host + a `Settings()`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_main_window.py -k "metering" -v`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute 'showEvent'` override / metering not called.

- [ ] **Step 3: Add the show/hide hooks**

In `src/tea_clipper/ui/main_window.py`, add two methods to `MainWindow` (next to `closeEvent`):

```python
    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._form.start_metering()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._form.stop_metering()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_main_window.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/ui/main_window.py tests/test_main_window.py
git commit -m "feat: run mic meter only while the window is visible"
```

---

### Task 9: Full-suite gate + hardware verification, docs

**Files:**
- Modify: `CLAUDE.md` (add a "Status — mic noise gate" section)
- Test: full suite

- [ ] **Step 1: Run the entire suite**

Run: `.venv/bin/pytest`
Expected: PASS — 101 prior + the new settings/audio/level-meter/settings-form/main-window tests, no failures, no skips beyond the usual `requires_engine` ones when hardware is absent.

- [ ] **Step 2: Hardware verification (manual, on KDE/Wayland with a mic)**

Document the outcome in the commit / CLAUDE.md. Steps:

1. `python -m tea_clipper.ui` — open the settings window; confirm the **Mic level** bar tracks real mic input and the amber threshold marker sits where the dB spinbox points.
2. Tick **Enable noise gate (mic)**, set the threshold just above the idle-noise level, click **Apply** (confirm the restart dialog).
3. Stay silent a few seconds, then save a clip (hotkey/tray). Measure with the project's idiom:
   `ffmpeg -hide_banner -i <clip> -af volumedetect -f null /dev/null 2>&1 | grep volume`
   Expected: the silent stretch reads near the gate floor (≈ −91 dB) while speech passes at normal level — versus an un-gated clip showing idle hiss around −50 dB.

- [ ] **Step 3: Update CLAUDE.md**

Add a `## Status — mic noise gate` section summarizing: the `audiodynamic mode=expander ratio=2` mechanism, the two Settings fields, mic-only scope, the `ui/level_meter.py` meter (probe-verified), and the hardware-verification result. Note the gotcha: GStreamer's `audiodynamic` has **no `cutoff` mode** — expander with `ratio≥2` is the gate; `threshold` is linear (0–1), not dB.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record mic noise-gate status (hardware-verified)"
```

---

## Self-Review

**Spec coverage:**
- Engine mechanism (`audiodynamic mode=expander ratio=2`) → Task 2. ✓
- Settings fields `mic_noise_gate_enabled` / `mic_noise_gate_db` → Task 1. ✓
- `gate_threshold_linear` + `build_audio_fragment(gate_threshold=…)` mic-only insertion → Task 2. ✓
- `resolve_gate_threshold` + controller wiring → Tasks 2–3. ✓
- `peak_to_display_db`, `db_to_fraction` → Task 4. ✓
- `MicLevelMonitor` (pipewiresrc → level, QTimer bus poll) → Task 5. ✓
- `LevelMeterBar` (fill + threshold marker) → Task 6. ✓
- SettingsForm checkbox + dB spinbox + meter, load/collect round-trip → Task 7. ✓
- Meter runs only while window visible → Task 8. ✓
- Unit-test + hardware-probe split → Tasks 1–8 unit, Task 9 probe. ✓
- YAGNI exclusions (no draggable marker, no attack/release, no ratio/knee, no desktop gate) → respected; not implemented. ✓

**Placeholder scan:** No TBD/TODO. Every code step shows complete code. Task 3 has no new test by design (live portal I/O; gate math unit-tested in Task 2) — verification is the full green suite, stated explicitly.

**Type consistency:** `gate_threshold` is a `float` (linear) throughout Tasks 2–3. `mic_noise_gate_db` is `float` in Settings; the UI spinbox is integer dB, converted with `float(...)` on collect and `int(round(...))` on load — round-trips for integer dB values (the only values the UI can produce). `peak_to_display_db`/`db_to_fraction`/`set_level`/`set_threshold` signatures match across Tasks 4, 6, 7. `MicLevelMonitor(mics)` constructor + `level_changed`/`start`/`stop` match between Tasks 5 and 7.
