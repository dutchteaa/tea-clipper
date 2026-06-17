# Mic noise gate + live input meter — design

**Date:** 2026-06-17
**Status:** approved (brainstorming)
**Scope:** silence quiet background noise on the microphone branch(es) below a
user-set threshold, with a live input-level meter in the settings UI so the user
can place the threshold just above their idle noise floor.

## Goal

Add a downward noise gate to the **mic** capture chain(s). Background noise below
a threshold is silenced; desktop audio and above-threshold speech pass through
untouched. The threshold is configurable in dB via the settings UI, alongside a
live meter showing the mic's raw (pre-gate) input level so the right value is
obvious. Applying the change restarts capture (same model as every other
setting).

## Engine mechanism

GStreamer ships no stock noise-gate element. Empirically verified on the target
hardware, `audiodynamic` in **expander** mode is a true downward gate:

```
audiodynamic mode=expander ratio=2 threshold=<linear>
```

- `threshold` is **linear amplitude**, range `0.0`–`1.0` (NOT dB).
- `ratio=2` fully silences below-threshold samples (measured ~-91 dB); higher
  ratios add nothing. `ratio=1` is passthrough. `ratio` is therefore fixed at 2
  and never exposed.
- `threshold=0` is a clean "gate off" (nothing is below 0 amplitude), verified:
  a quiet -34 dB tone passes unchanged.
- dB↔linear: `linear = 10 ** (db / 20)`. Reference: -40 dB ≈ 0.010,
  -30 dB ≈ 0.032, -20 dB ≈ 0.100.

Above-threshold signal is untouched (a -9 dB tone through a -20 dB-threshold gate
measured -9 dB out). The gate is per-sample with no attack/release timing; this
is acceptable for the scope (silencing idle hiss), and attack/release is
explicitly out of scope.

## Components

### 1. Settings (`settings.py`)

Two new dataclass fields:

```python
mic_noise_gate_enabled: bool = False
mic_noise_gate_db: float = -40.0      # gate threshold in dBFS
```

`Settings.load` already drops unknown keys, so existing configs forward-compat to
the defaults (gate off) with no migration.

### 2. Audio fragment (`audio.py`)

- New pure helper:

  ```python
  def gate_threshold_linear(db: float) -> float:
      """dBFS -> linear amplitude in [0.0, 1.0]."""
      return min(1.0, max(0.0, 10 ** (db / 20)))
  ```

- `build_audio_fragment(devices, gate_threshold=0.0)` gains an optional
  already-resolved **linear** threshold (a plain float, keeping `audio.py`
  decoupled from the Settings shape, consistent with the existing
  `resolve`/`build` split). `0.0` = no gate.

- `_device_fragment(device, gate_threshold)` inserts the gate **only** for mics
  (`not device.is_monitor`) when `gate_threshold > 0`, after `audioconvert`:

  ```
  pipewiresrc target-object=<mic> ! audioconvert !
    audiodynamic mode=expander threshold=<t> ratio=2 !
    audioresample ! queue ! amix.
  ```

  Sinks (desktop audio) and the `gate_threshold == 0` case produce the exact same
  fragment string as today, so existing unit tests stay green.

### 3. Controller wiring (`controller.py`, `build_controller`)

```python
gate = (
    gate_threshold_linear(settings.mic_noise_gate_db)
    if settings.mic_noise_gate_enabled
    else 0.0
)
audio = build_audio_fragment(devices, gate_threshold=gate)
```

### 4. UI — gate controls + live mic meter

The meter shows the mic's **raw** (pre-gate) input level so the user sees their
actual noise floor; the gate threshold is drawn as a marker over it.

**New `ui/level_meter.py`:**

- `peak_to_display_db(peaks: list[float], floor: float = -60.0) -> float` — pure:
  max peak across channels, clamped to `floor`; returns `floor` for empty input.
  **Unit-tested.**
- `db_to_fraction(db: float, floor: float = -60.0, ceil: float = 0.0) -> float` —
  pure dB → bar position in `[0.0, 1.0]`. **Unit-tested.**
- `MicLevelMonitor(QObject)` — builds
  `pipewiresrc target-object=<mic> ! audioconvert ! level interval=50ms post-messages=true ! fakesink`
  (mixed via `audiomixer` when more than one mic) from the resolved **mic**
  devices. A `QTimer` (~50 ms) pops `level` ELEMENT messages off the pipeline bus
  and emits `level_changed(peak_db: float)`. `start()`/`stop()` set the pipeline
  PLAYING/NULL. No GLib main loop is needed — the bus is polled from the Qt main
  thread, where this object lives entirely. Degrades to silent (no emissions) if
  no mic is available or pipewiresrc fails (caught + logged). **Probe-verified.**
- `LevelMeterBar(QWidget)` — a horizontal bar filled to the live level over a
  fixed −60…0 dB scale, with a vertical marker line at the current
  `mic_noise_gate_db`; the region below the marker is greyed to read as "would be
  gated". The dB→x mapping reuses `db_to_fraction`. Exposes setters for the live
  level and the threshold.

**`ui/settings_form.py`:** add an "Enable noise gate (mic)" checkbox + a dB
spinbox (range −60…−10, default −40, disabled when the checkbox is off) and the
`LevelMeterBar`, grouped with the audio controls. `load`/`collect` round-trip
`mic_noise_gate_enabled` + `mic_noise_gate_db` while preserving untouched fields.
Moving the spinbox updates the bar's threshold marker; `level_changed` from the
monitor updates the fill.

**`ui/main_window.py`:** start the `MicLevelMonitor` when the window is shown and
stop it when hidden (the meter only runs while settings are visible, so it does
not hold the mic or burn CPU in the background). A concurrent `pipewiresrc` on
the mic alongside the capture pipeline is fine — PipeWire allows multiple
readers of the same source node.

### 5. Testing

- **Unit:**
  - `gate_threshold_linear` — dB→linear values and `[0,1]` clamping.
  - `build_audio_fragment` / `_device_fragment` — `audiodynamic` inserted on mic
    chains only; never on sinks; absent when `gate_threshold == 0`; existing
    fragments unchanged.
  - `peak_to_display_db` and `db_to_fraction` — boundaries, clamping, empty input.
  - `Settings` round-trip and `SettingsForm` `load`/`collect` round-trip of the
    two new fields.
- **Hardware/probe:** the live daemon (`python -m tea_clipper`) confirms the gate
  silences idle mic hiss in a saved clip; `python -m tea_clipper.ui` confirms the
  settings window's meter tracks real mic level with the threshold marker
  visible. The `audiodynamic` gating behaviour and `level` message format are
  already empirically proven during design.

## Out of scope (YAGNI)

- Dragging the marker on the meter to set the value (the spinbox stays the input).
- Attack/release timing; exposing `ratio` or the knee `characteristics`.
- Per-device thresholds; gating desktop audio.
- A separate "currently gated?" live indicator.
