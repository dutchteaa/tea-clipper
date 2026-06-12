# Controller Design — App Lifecycle & Wiring

**Date:** 2026-06-12 · **Status:** Approved (compressed flow)

## Goal

Wire the existing components into a runnable headless daemon: capture the screen, keep the
rolling buffer full, and route the two hotkeys to engine actions. `python -m tea_clipper`
becomes the MVP — launch, press `Ctrl+Alt+C` mid-game, get a clip.

## Components

**`Controller` (`src/tea_clipper/controller.py`) — unit-tested core.**
Holds already-built collaborators (`settings`, `pipeline`, `replay_buffer`,
`manual_recorder`, `hotkey_service`) and owns lifecycle + the two hotkey handlers:
- `_on_save_clip()` → `replay_buffer.save_last(settings.clip_length_seconds, out, pipeline)`
  where `out = <output_dir>/clip_<timestamp>.mkv`. Failures are caught and logged, not fatal.
- `_on_toggle_record()` → if `manual_recorder.is_recording` is False, `start()`; else
  `stop(<output_dir>/recording_<timestamp>.mkv)`. Failures caught and logged.
- `start()` registers both handlers on `hotkey_service` (`SAVE_CLIP`, `TOGGLE_RECORD`),
  starts the pipeline, and starts the hotkey service with `run_loop=False`.
- `run()` runs the owned `GLib.MainLoop` (the app loop shared by the hotkey service).
- `stop()` quits the loop, stops the hotkey service, stops the pipeline.
- `last_clip` attribute records the most recent saved path (handy for tests/logging).

**`build_controller(settings, portal=None)` factory — probe-verified, not unit-tested.**
Real wiring: `PortalManager(settings).open()` → `EncoderRegistry().resolve(codec, hardware,
bitrate_kbps, fps, segment_seconds)` → `CapturePipeline(source_desc=(portal_video, None),
encoder=spec, buffer_dir=settings.buffer_dir, segment_seconds=settings.segment_seconds,
max_segments=compute_max_segments(settings))` → attach `ReplayBuffer` + `ManualRecorder` as
segment listeners → build `HotkeyService`. Returns a `Controller`. Keeps a reference to the
`PortalManager` so `Controller.stop()` can close it (the factory passes it in).

**`compute_max_segments(settings)` — pure helper.**
`ceil(clip_length_seconds / segment_seconds) + 2` (margin so save-last always has coverage).

**App entrypoint `src/tea_clipper/__main__.py` (`python -m tea_clipper`).**
`Settings.load(config)` → `build_controller(settings)` → persist restore token via
`settings.save` → `start()` → `run()`; on `KeyboardInterrupt`, `stop()`.

## Decisions

- Video-only capture (audio milestone is separate); reuses the optional-audio pipeline.
- Output filenames timestamped under `settings.output_dir` (created if missing).
- The hotkey service shares the Controller's main loop (`run_loop=False`).
- Portal startup failure aborts cleanly (exception propagates out of `build_controller`);
  a failed `save_last`/`stop` logs and the daemon keeps running.

## Testing

**Unit (`tests/test_controller.py`, CI, no real portal/bus):**
- `compute_max_segments` math.
- `Controller.start()` registers handlers for `SAVE_CLIP` and `TOGGLE_RECORD` on a fake
  hotkey service and starts the (fake) pipeline.
- firing `SAVE_CLIP` calls `replay_buffer.save_last` with `clip_length_seconds`, the pipeline,
  and a path under `output_dir`; sets `last_clip`.
- firing `TOGGLE_RECORD` alternates `manual_recorder.start()` then `stop(<path>)`.
- a `save_last` that raises is caught (daemon survives, no exception escapes the handler).
- `stop()` stops pipeline + hotkey service.

Collaborators are simple fakes (record calls). A `FakeHotkeyService` exposes `add_listener`
+ `fire(action)` like the real one's dispatch.

**Manual:** `python -m tea_clipper` on the KDE/Wayland target — capture starts, the bound
hotkeys save clips / toggle recording into `output_dir`.

## Files

```
src/tea_clipper/controller.py     # Controller + build_controller + compute_max_segments
src/tea_clipper/__main__.py       # python -m tea_clipper entrypoint
tests/test_controller.py          # unit tests with fakes
```

## Deferred

Real desktop+mic audio, the PySide6 UI, and any in-app status/log surface beyond stdout.
