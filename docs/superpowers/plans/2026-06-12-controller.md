# Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire capture + rolling buffer + manual recorder + hotkeys into a runnable headless daemon (`python -m tea_clipper`).

**Architecture:** A `Controller` holds already-built collaborators and owns lifecycle + the two hotkey handlers (`save_clip` → `ReplayBuffer.save_last`, `toggle_record` → `ManualRecorder` start/stop), unit-tested with fakes. A `build_controller()` factory does the real portal/encoder/pipeline wiring, and `__main__.py` is the entrypoint — both probe-verified.

**Tech Stack:** Python 3.12+ · `gi.repository.GLib` (app main loop) · existing tea_clipper modules · pytest. Spec: `docs/superpowers/specs/2026-06-12-controller-design.md`.

---

## File Structure

```
src/tea_clipper/controller.py   # CREATE: compute_max_segments, Controller, build_controller
src/tea_clipper/__main__.py     # CREATE: python -m tea_clipper entrypoint
tests/test_controller.py        # CREATE: pure helper + handler/lifecycle tests (fakes)
```

---

## Task 1: `compute_max_segments` + `Controller` core

**Files:**
- Create: `src/tea_clipper/controller.py`
- Test: `tests/test_controller.py`

- [ ] **Step 1: Write the failing tests** `tests/test_controller.py`

```python
from pathlib import Path

from tea_clipper.controller import Controller, compute_max_segments
from tea_clipper.hotkeys import SAVE_CLIP, TOGGLE_RECORD
from tea_clipper.settings import Settings


class FakePipeline:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeReplay:
    def __init__(self, raises=False):
        self.calls = []
        self._raises = raises

    def save_last(self, seconds, out, pipeline):
        self.calls.append((seconds, out, pipeline))
        if self._raises:
            raise RuntimeError("boom")
        return out


class FakeRecorder:
    def __init__(self):
        self.is_recording = False
        self.started = 0
        self.stopped = []

    def start(self):
        self.started += 1
        self.is_recording = True

    def stop(self, out):
        self.is_recording = False
        self.stopped.append(out)
        return out


class FakeHotkeys:
    def __init__(self):
        self.listeners = {}
        self.started = False
        self.stopped = False
        self.run_loop = None

    def add_listener(self, action, cb):
        self.listeners.setdefault(action, []).append(cb)

    def start(self, run_loop=True):
        self.started = True
        self.run_loop = run_loop

    def stop(self):
        self.stopped = True

    def fire(self, action):
        for cb in self.listeners.get(action, []):
            cb()


class FakePortal:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _controller(tmp_path, replay=None, recorder=None, portal=None):
    settings = Settings(output_dir=str(tmp_path), clip_length_seconds=20, segment_seconds=2)
    pipeline = FakePipeline()
    hotkeys = FakeHotkeys()
    ctl = Controller(
        settings, pipeline, replay or FakeReplay(), recorder or FakeRecorder(),
        hotkeys, portal=portal,
    )
    return ctl, pipeline, hotkeys


def test_compute_max_segments():
    assert compute_max_segments(Settings(clip_length_seconds=30, segment_seconds=2)) == 17
    assert compute_max_segments(Settings(clip_length_seconds=10, segment_seconds=3)) == 6


def test_start_wires_handlers_and_starts(tmp_path):
    ctl, pipeline, hotkeys = _controller(tmp_path)
    ctl.start()
    assert SAVE_CLIP in hotkeys.listeners
    assert TOGGLE_RECORD in hotkeys.listeners
    assert pipeline.started
    assert hotkeys.started and hotkeys.run_loop is False


def test_save_clip_handler_saves_with_clip_length(tmp_path):
    replay = FakeReplay()
    ctl, pipeline, hotkeys = _controller(tmp_path, replay=replay)
    ctl.start()
    hotkeys.fire(SAVE_CLIP)
    assert len(replay.calls) == 1
    seconds, out, pipe = replay.calls[0]
    assert seconds == 20                      # settings.clip_length_seconds
    assert pipe is pipeline
    assert Path(out).parent == tmp_path
    assert Path(out).name.startswith("clip_")
    assert ctl.last_clip == out


def test_toggle_record_alternates(tmp_path):
    recorder = FakeRecorder()
    ctl, pipeline, hotkeys = _controller(tmp_path, recorder=recorder)
    ctl.start()
    hotkeys.fire(TOGGLE_RECORD)
    assert recorder.started == 1 and recorder.is_recording
    hotkeys.fire(TOGGLE_RECORD)
    assert recorder.is_recording is False
    assert len(recorder.stopped) == 1
    assert Path(recorder.stopped[0]).name.startswith("recording_")


def test_save_clip_failure_is_caught(tmp_path):
    replay = FakeReplay(raises=True)
    ctl, pipeline, hotkeys = _controller(tmp_path, replay=replay)
    ctl.start()
    hotkeys.fire(SAVE_CLIP)   # must not raise
    assert ctl.last_clip is None


def test_stop_tears_down(tmp_path):
    portal = FakePortal()
    settings = Settings(output_dir=str(tmp_path))
    pipeline = FakePipeline()
    hotkeys = FakeHotkeys()
    ctl = Controller(settings, pipeline, FakeReplay(), FakeRecorder(), hotkeys, portal=portal)
    ctl.start()
    ctl.stop()
    assert hotkeys.stopped
    assert pipeline.stopped
    assert portal.closed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_controller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tea_clipper.controller'`

- [ ] **Step 3: Create `src/tea_clipper/controller.py` (helper + Controller)**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_controller.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/controller.py tests/test_controller.py
git commit -m "feat: Controller routes hotkeys to save-clip and toggle-record"
```

---

## Task 2: `build_controller` factory

**Files:**
- Modify: `src/tea_clipper/controller.py` (add `build_controller`)

The real wiring. Not unit-tested (needs the portal); exercised by the entrypoint in Task 3.

- [ ] **Step 1: Append `build_controller` to `src/tea_clipper/controller.py`**

```python
def build_controller(settings, portal=None) -> Controller:
    """Wire the real components: portal capture → pipeline → buffer + recorder → hotkeys."""
    from tea_clipper.encoders import EncoderRegistry
    from tea_clipper.manual_recorder import ManualRecorder
    from tea_clipper.pipeline import CapturePipeline
    from tea_clipper.portal import PortalManager
    from tea_clipper.replay_buffer import ReplayBuffer

    if portal is None:
        portal = PortalManager(settings)
    video = portal.open()
    spec = EncoderRegistry().resolve(
        settings.codec, hardware=settings.hardware, bitrate_kbps=settings.bitrate_kbps,
        fps=settings.fps, segment_seconds=settings.segment_seconds,
    )
    pipeline = CapturePipeline(
        source_desc=(video, None), encoder=spec, buffer_dir=settings.buffer_dir,
        segment_seconds=settings.segment_seconds, max_segments=compute_max_segments(settings),
    )
    replay = ReplayBuffer(segment_seconds=settings.segment_seconds)
    recorder = ManualRecorder(pipeline=pipeline)
    pipeline.add_segment_listener(replay.on_segment_finalized)
    pipeline.add_segment_listener(recorder.on_segment_finalized)
    hotkeys = HotkeyService()
    return Controller(settings, pipeline, replay, recorder, hotkeys, portal=portal)
```

Also add the `HotkeyService` import at the top of the file, changing:

```python
from tea_clipper.hotkeys import SAVE_CLIP, TOGGLE_RECORD
```

to:

```python
from tea_clipper.hotkeys import SAVE_CLIP, TOGGLE_RECORD, HotkeyService
```

- [ ] **Step 2: Verify the module imports and unit tests still pass**

Run: `.venv/bin/python -c "import tea_clipper.controller"`
Expected: no output, exit 0.

Run: `.venv/bin/pytest tests/test_controller.py -v`
Expected: 6 passed (unchanged — `build_controller` is not exercised here).

- [ ] **Step 3: Commit**

```bash
git add src/tea_clipper/controller.py
git commit -m "feat: build_controller wires the real capture/buffer/hotkey components"
```

---

## Task 3: `python -m tea_clipper` entrypoint

**Files:**
- Create: `src/tea_clipper/__main__.py`

- [ ] **Step 1: Create `src/tea_clipper/__main__.py`**

```python
"""Run tea-clipper as a daemon:  python -m tea_clipper

Opens screen capture (a portal picker appears the first time), keeps the rolling buffer
full, and routes the global hotkeys to save clips / toggle recording. Ctrl-C to quit.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from tea_clipper.controller import build_controller
from tea_clipper.portal import PortalError
from tea_clipper.settings import Settings


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Path.home() / ".config" / "tea-clipper" / "config.toml"
    settings = Settings.load(config)

    print("Starting screen capture (a picker may appear the first time)...")
    try:
        controller = build_controller(settings)
    except PortalError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1
    settings.save(config)  # persist the (possibly new) restore token

    controller.start()
    print("tea-clipper running. Press your hotkeys to save clips / toggle recording.")
    print(f"Clips are written to {settings.output_dir}. Ctrl-C to quit.")
    try:
        controller.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        controller.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-check the module imports (no capture)**

Run: `.venv/bin/python -c "import tea_clipper.__main__"`
Expected: no output, exit 0.

- [ ] **Step 3: Manual hardware run (on the KDE/Wayland desktop, not CI)**

Run: `.venv/bin/python -m tea_clipper`
Expected: a monitor picker appears (first run); "tea-clipper running…" prints. Pressing
the bound hotkeys writes `clip_*.mkv` / `recording_*.mkv` into the output dir. Ctrl-C exits
cleanly.

> If this can't run now (headless), leave it unchecked and note hardware verification is
> pending in the commit. The automated suite stays green regardless.

- [ ] **Step 4: Commit**

```bash
git add src/tea_clipper/__main__.py
git commit -m "feat: python -m tea_clipper entrypoint runs the capture daemon"
```

---

## Task 4: Docs + full suite + finish

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the entire suite**

Run: `.venv/bin/pytest -m "engine or not engine"`
Expected: all green — new `tests/test_controller.py` (6 tests) plus all existing tests.

- [ ] **Step 2: Add a "Status — Controller" section to `CLAUDE.md`**

After the HotkeyService status section, add a short section noting: implemented (TDD) on the
`controller` branch; `controller.Controller` owns the app loop and routes `save_clip` →
`ReplayBuffer.save_last(clip_length, …)` and `toggle_record` → `ManualRecorder` start/stop;
`build_controller()` wires the real portal/encoder/pipeline/buffer/recorder/hotkeys; the app
runs via `python -m tea_clipper` (hardware verification pending if not yet run). Note that the
MVP is now runnable headless, and that real desktop+mic audio and the PySide6 UI remain the
last deferred milestones. Reference the spec and plan. Match the existing format.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record Controller (runnable MVP) in CLAUDE.md status"
```

- [ ] **Step 4: Finish the branch**

Use superpowers:finishing-a-development-branch to verify tests, present integration options,
and complete the work (PR into `main`).

---

## Done criteria

- `pytest` green: `tests/test_controller.py` (helper + handler/lifecycle with fakes) plus all
  existing tests.
- `Controller` routes both hotkeys correctly, catches per-action failures, and tears down
  cleanly; `build_controller()` assembles the real stack.
- `python -m tea_clipper` runs the capture daemon end-to-end on the KDE/Wayland target.

## Deferred (later)

Real desktop+mic audio mixing, the PySide6 UI.
