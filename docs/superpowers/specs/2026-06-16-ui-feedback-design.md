# UI feedback: clip-saved toast + record-state sync — design

**Date:** 2026-06-16
**Status:** Approved (brainstorming)
**Repository:** https://github.com/dutchteaa/tea-clipper

## Goal

Make tea-clipper tell the user what it's doing. Two related gaps:

1. **Clip-saved toast** — a hotkey/tray save gives no feedback when the window is hidden.
   Show a desktop notification when a clip (instant or finished manual recording) is saved.
2. **Record-state sync** — the window's Record button doesn't update when recording is
   toggled via hotkey or tray, so it goes stale (a latent correctness bug).

Both are solved by routing engine events through the existing
`Controller` callback → `EngineHost` Qt signal → UI pattern (the same worker-thread →
main-thread queued-signal path already used by `clip_saved`/`state_changed`). No new
threading model, no new dependency.

## Context & constraints

- UI threading rule (CLAUDE.md): Qt owns the main thread; the engine runs on a worker
  thread; engine→UI updates come back as thread-safe Qt signals. New signals follow this.
- Scope is deliberately small (CLAUDE.md: YAGNI). GUI only — the headless daemon
  (`python -m tea_clipper`) is untouched.
- Current wiring of note:
  - `Controller` already takes a `clip_saved_cb`, invoked by `_notify_saved()` from both
    `save_clip()` and the stop branch of `toggle_record()`.
  - `EngineHost` already exposes `clip_saved = Signal(str)` and `state_changed`.
  - `MainWindow._record_btn` is checkable and its `toggled` signal *drives*
    `host.toggle_record()`; nothing drives the button back.

## Feature 2 — record-state sync

Engine state is the single source of truth; the UI reflects it.

### Controller
- Add a `recording_changed_cb` parameter (mirrors `clip_saved_cb`), stored on the instance.
- In `toggle_record()`, after a **successful** transition, invoke the callback with the
  new boolean: `True` after `self._recorder.start()`, `False` after a successful
  `self._recorder.stop(...)`. If the transition raises (caught by the existing
  `try/except`), **do not** invoke the callback — the button must never show a state the
  engine didn't reach.
- Wrap the callback invocation defensively (log-and-continue), like `_notify_saved()`.
- `build_controller(...)` gains a `recording_changed_cb=None` parameter and passes it to
  `Controller`.

### EngineHost
- New `recording_changed = Signal(bool)`.
- Add `_on_recording_changed(recording: bool)` that emits the signal.
- Pass `recording_changed_cb=self._on_recording_changed` to `self._builder(...)` in
  `_bring_up()`. (The callback fires on the worker thread; the auto/queued connection
  marshals the slot onto the main thread, exactly as `clip_saved` does today.)

### MainWindow
- The Record button reflects engine truth instead of driving itself blindly:
  - Switch the user trigger from `toggled` to `clicked` → request `host.toggle_record()`.
  - The checked state and label ("● Record" ↔ "■ Stop recording") are set **only** from a
    `recording_changed` slot.
  - Guard the programmatic sync so setting the checked state does not re-fire
    `toggle_record()` (e.g. `blockSignals` around the update, or only acting on the
    user `clicked` signal — never on programmatic check changes). The result: no feedback
    loop, and the button can't get stuck (a failed start emits nothing, so the button
    stays in its real "not recording" state).
- Connect `host.recording_changed` in `__init__`.

### TrayIcon
- Keep a reference to the "Toggle recording" `QAction`; on `recording_changed`, update its
  label to "Stop recording" (when recording) / "Start recording" (when not). Connect
  `host.recording_changed`.

## Feature 1 — clip-saved toast

Desktop notifications via the tray's built-in `QSystemTrayIcon.showMessage(title, body)`
(standard freedesktop toast; no new dependency; the tray already exists).

### TrayIcon
- Connect `host.clip_saved(path)` → `showMessage("Clip saved", <basename of path>)`.
  This already fires for **both** instant clips (`save_clip`) and finished manual
  recordings (the stop branch), so it covers the recording-stop case with one message.
- Connect `host.recording_changed(recording)`:
  - `True` → `showMessage("tea-clipper", "Recording started")`.
  - `False` → **no** toast (the `clip_saved` message already announces the saved
    recording; suppressing avoids a double notification on stop).

## Error handling

- Callback invocations in `Controller` are wrapped (log-and-continue) so a UI-side error
  never kills the engine action.
- A failed record transition emits no `recording_changed`, so the button/label/tray stay
  consistent with reality.
- `showMessage` is best-effort; if the platform has no notification support it is a
  silent no-op (Qt handles this).

## Testing

Consistent with the project split — unit-test the callback/signal plumbing with fakes;
the live tray toast + button visuals are manually verified.

Unit tests:
- `tests/test_controller.py` — `recording_changed_cb` is called with `True` on start and
  `False` on a successful stop; it is **not** called when the recorder raises during a
  transition; `clip_saved_cb` still fires on stop.
- `tests/test_engine_host.py` — the fake builder receives a `recording_changed_cb`;
  invoking it emits the `recording_changed` Qt signal with the right value.
- `MainWindow` button sync (offscreen, if a fake host is convenient): a
  `recording_changed(True)` updates the button to checked/"Stop recording" **without**
  invoking `toggle_record`; a user `clicked` **does** invoke `toggle_record`.

Manually verified (not CI):
- Hotkey/tray toggle updates the window Record button and the tray menu label.
- A hotkey-triggered save raises a "Clip saved — …" desktop toast while the window is
  hidden; starting a recording raises "Recording started"; stopping shows only the
  "Clip saved" toast (no duplicate).

## Out of scope (YAGNI)

- Failure toasts (clip/record errors remain logged-only).
- A custom `org.freedesktop.portal.Notification` path — the tray `showMessage` is enough.
- Notification actions (e.g. "Open clip" button on the toast).
- Any change to the headless daemon.
