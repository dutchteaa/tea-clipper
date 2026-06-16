# UI Feedback (toast + record-state sync) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a desktop toast when a clip is saved, and keep the window Record button + tray menu in sync with the real recording state (including when toggled via hotkey/tray).

**Architecture:** Route engine events through the existing `Controller` callback → `EngineHost` Qt signal → UI pattern. Add a `recording_changed_cb` to `Controller` (emitted only on a successful start/stop) and a matching `recording_changed = Signal(bool)` on `EngineHost`. `MainWindow` makes engine state the source of truth for the Record button; `TrayIcon` updates its menu label and raises toasts via `QSystemTrayIcon.showMessage`.

**Tech Stack:** Python 3.12, PySide6 (Qt signals, `QSystemTrayIcon.showMessage`), pytest.

Spec: `docs/superpowers/specs/2026-06-16-ui-feedback-design.md`

---

### Task 1: `Controller.recording_changed_cb`

**Files:**
- Modify: `src/tea_clipper/controller.py:28-38` (constructor), `:65-75` (`toggle_record`), `:97-131` (`build_controller`)
- Test: `tests/test_controller.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_controller.py`:

```python
def test_recording_changed_cb_fires_true_then_false(tmp_path):
    events = []
    recorder = FakeRecorder()
    ctl, _pipeline, _hotkeys = _controller(tmp_path, recorder=recorder)
    ctl._recording_changed_cb = events.append
    ctl.start()
    ctl.toggle_record()   # start
    ctl.toggle_record()   # stop
    assert events == [True, False]


def test_recording_changed_cb_not_called_on_failure(tmp_path):
    events = []

    class BoomRecorder(FakeRecorder):
        def start(self):
            raise RuntimeError("cannot start")

    ctl, _pipeline, _hotkeys = _controller(tmp_path, recorder=BoomRecorder())
    ctl._recording_changed_cb = events.append
    ctl.start()
    ctl.toggle_record()   # start raises, caught
    assert events == []


def test_recording_changed_cb_passed_via_constructor(tmp_path):
    events = []
    settings = Settings(output_dir=str(tmp_path))
    ctl = Controller(
        settings, FakePipeline(), FakeReplay(), FakeRecorder(), FakeHotkeys(),
        recording_changed_cb=events.append,
    )
    ctl.start()
    ctl.toggle_record()
    assert events == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_controller.py -k recording_changed -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'recording_changed_cb'` / `AttributeError`.

- [ ] **Step 3: Add the callback to `Controller`**

In `src/tea_clipper/controller.py`, extend the constructor signature and store it:

```python
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
```

Add a helper next to `_notify_saved`:

```python
    def _notify_recording(self, recording: bool) -> None:
        if self._recording_changed_cb is not None:
            try:
                self._recording_changed_cb(recording)
            except Exception:
                log.exception("recording_changed_cb raised")
```

Update `toggle_record` to notify only after a successful transition:

```python
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
```

- [ ] **Step 4: Thread it through `build_controller`**

In `src/tea_clipper/controller.py`, update the factory signature and the `Controller(...)`
construction:

```python
def build_controller(
    settings, portal=None, clip_saved_cb=None, recording_changed_cb=None
) -> Controller:
```

and at the return:

```python
    return Controller(
        settings, pipeline, replay, recorder, hotkeys,
        portal=portal, clip_saved_cb=clip_saved_cb,
        recording_changed_cb=recording_changed_cb,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_controller.py -v`
Expected: PASS (all controller tests, including the three new ones).

- [ ] **Step 6: Commit**

```bash
git add src/tea_clipper/controller.py tests/test_controller.py
git commit -m "feat: Controller.recording_changed_cb (success-only)"
```

---

### Task 2: `EngineHost.recording_changed` signal

**Files:**
- Modify: `src/tea_clipper/ui/engine_host.py:21-23` (signals), `:42-49` (handlers + builder call)
- Test: `tests/test_engine_host.py`

Note: the existing test builders use the signature `def builder(settings, clip_saved_cb=None)`.
After this task `_bring_up` also passes `recording_changed_cb=...`, so every fake builder
must accept it. Step 4 updates them.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_engine_host.py`:

```python
def test_recording_changed_cb_reemits_qt_signal(qapp, tmp_path):
    captured = {}

    def builder(settings, clip_saved_cb=None, recording_changed_cb=None):
        captured["rec_cb"] = recording_changed_cb
        return FakeController()

    host, _cfg = _host(tmp_path, builder)
    got = []
    host.recording_changed.connect(got.append)
    host._bring_up()
    captured["rec_cb"](True)
    captured["rec_cb"](False)
    assert got == [True, False]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_engine_host.py::test_recording_changed_cb_reemits_qt_signal -v`
Expected: FAIL — `AttributeError: 'EngineHost' object has no attribute 'recording_changed'`.

- [ ] **Step 3: Add the signal + handler + builder wiring**

In `src/tea_clipper/ui/engine_host.py`, add the signal next to the others:

```python
    state_changed = Signal(str, str)
    clip_saved = Signal(str)
    recording_changed = Signal(bool)
```

Add a handler next to `_on_clip_saved`:

```python
    def _on_recording_changed(self, recording: bool) -> None:
        self.recording_changed.emit(recording)
```

Update the builder call in `_bring_up`:

```python
            self._controller = self._builder(
                self._settings,
                clip_saved_cb=self._on_clip_saved,
                recording_changed_cb=self._on_recording_changed,
            )
```

- [ ] **Step 4: Update existing fake builders to accept the new kwarg**

In `tests/test_engine_host.py`, every `def builder(settings, clip_saved_cb=None)` and every
`lambda s, clip_saved_cb=None: ...` must also accept `recording_changed_cb=None`. Update
each occurrence:

- `test_bring_up_success_persists_and_emits`: `def builder(settings, clip_saved_cb=None, recording_changed_cb=None):`
- `test_bring_up_failure_emits_error`: `def builder(settings, clip_saved_cb=None, recording_changed_cb=None):`
- `test_clip_saved_cb_reemits_qt_signal`: `def builder(settings, clip_saved_cb=None, recording_changed_cb=None):`
- `test_save_and_toggle_dispatch_to_controller`: `lambda s, clip_saved_cb=None, recording_changed_cb=None: fake`
- `test_apply_settings_swaps_and_restarts`: `lambda s, clip_saved_cb=None, recording_changed_cb=None: FakeController()`
- `test_repick_clears_token_then_restarts`: `builder=lambda s, clip_saved_cb=None, recording_changed_cb=None: FakeController()`

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_engine_host.py -v`
Expected: PASS (all engine-host tests, including the new one).

- [ ] **Step 6: Commit**

```bash
git add src/tea_clipper/ui/engine_host.py tests/test_engine_host.py
git commit -m "feat: EngineHost.recording_changed signal"
```

---

### Task 3: `MainWindow` Record button reflects engine truth

**Files:**
- Modify: `src/tea_clipper/ui/main_window.py:42-44` (button), `:76-92` (connections + handlers)
- Test: `tests/test_main_window.py`

The button must (a) request a toggle on user click, (b) display the real state only from
`recording_changed`, and (c) never re-fire `toggle_record` when synced programmatically.
Use `clicked` for the user request and `blockSignals` is unnecessary because `clicked`
(unlike `toggled`) does not fire on programmatic `setChecked`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_main_window.py`:

```python
from tea_clipper.settings import Settings
from tea_clipper.ui.main_window import MainWindow


class FakeHost:
    """Minimal EngineHost stand-in exposing the signals MainWindow connects to."""

    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class _Sig(QObject):
            state_changed = Signal(str, str)
            clip_saved = Signal(str)
            recording_changed = Signal(bool)

        self._sig = _Sig()
        self.state_changed = self._sig.state_changed
        self.clip_saved = self._sig.clip_saved
        self.recording_changed = self._sig.recording_changed
        self.state = "Recording"
        self.toggles = 0

    def save_clip(self):
        pass

    def toggle_record(self):
        self.toggles += 1


def test_recording_changed_updates_button_without_toggling(qapp):
    host = FakeHost()
    win = MainWindow(host, Settings())
    host.recording_changed.emit(True)
    assert win._record_btn.isChecked() is True
    assert "Stop" in win._record_btn.text()
    assert host.toggles == 0          # programmatic sync must NOT call toggle_record


def test_button_click_requests_toggle(qapp):
    host = FakeHost()
    win = MainWindow(host, Settings())
    win._record_btn.click()
    assert host.toggles == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_main_window.py -v`
Expected: FAIL — `test_recording_changed_updates_button_without_toggling` fails because the
button does not yet respond to `recording_changed` (and currently `toggled` would call
`toggle_record`).

- [ ] **Step 3: Rewire the button**

In `src/tea_clipper/ui/main_window.py`, change the button construction (around line 42)
from `toggled` to `clicked`:

```python
        self._record_btn = QPushButton("● Record")
        self._record_btn.setCheckable(True)
        self._record_btn.clicked.connect(self._on_record_clicked)
```

Replace the `_on_record_toggled` method with two methods:

```python
    def _on_record_clicked(self) -> None:
        # User intent only; the real checked state is driven by recording_changed.
        self._host.toggle_record()

    def _on_recording_changed(self, recording: bool) -> None:
        self._record_btn.setChecked(recording)
        self._record_btn.setText("■ Stop recording" if recording else "● Record")
```

Connect the signal in `__init__` next to the existing `host.*` connections:

```python
        host.state_changed.connect(self._on_state)
        host.clip_saved.connect(self._on_clip_saved)
        host.recording_changed.connect(self._on_recording_changed)
        self._on_state(host.state, "")
```

Note: `QPushButton.clicked` does not fire on programmatic `setChecked`, so
`_on_recording_changed` cannot re-enter `_on_record_clicked` — no feedback loop, no signal
blocking needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_main_window.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/ui/main_window.py tests/test_main_window.py
git commit -m "feat: MainWindow Record button reflects engine recording state"
```

---

### Task 4: `TrayIcon` toast + menu-label sync

**Files:**
- Modify: `src/tea_clipper/ui/tray.py:24-36` (menu + connections), add handlers
- Test: `tests/test_tray.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tray.py` (it defines its own `FakeHost` copy — do not import across
test modules, which is path-fragile under pytest):

```python
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from tea_clipper.settings import Settings
from tea_clipper.ui.tray import TrayIcon


class _Sig(QObject):
    state_changed = Signal(str, str)
    clip_saved = Signal(str)
    recording_changed = Signal(bool)


class FakeHost:
    def __init__(self):
        self._sig = _Sig()
        self.state_changed = self._sig.state_changed
        self.clip_saved = self._sig.clip_saved
        self.recording_changed = self._sig.recording_changed
        self.state = "Recording"

    def save_clip(self):
        pass

    def toggle_record(self):
        pass


def test_clip_saved_raises_toast(qapp, monkeypatch, tmp_path):
    host = FakeHost()
    window = object()  # tray only calls window methods on user interaction
    tray = TrayIcon(host, window, Settings(output_dir=str(tmp_path)))
    messages = []
    monkeypatch.setattr(tray, "showMessage", lambda title, body, *a, **k: messages.append((title, body)))
    host.clip_saved.emit(str(Path(tmp_path) / "clip_x.mkv"))
    assert messages == [("Clip saved", "clip_x.mkv")]


def test_recording_started_toast_and_label(qapp, monkeypatch, tmp_path):
    host = FakeHost()
    tray = TrayIcon(host, object(), Settings(output_dir=str(tmp_path)))
    messages = []
    monkeypatch.setattr(tray, "showMessage", lambda title, body, *a, **k: messages.append((title, body)))
    host.recording_changed.emit(True)
    assert ("tea-clipper", "Recording started") in messages
    assert tray._record_action.text() == "Stop recording"
    messages.clear()
    host.recording_changed.emit(False)
    assert messages == []                      # no toast on stop (clip_saved covers it)
    assert tray._record_action.text() == "Start recording"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tray.py -v`
Expected: FAIL — `AttributeError: 'TrayIcon' object has no attribute '_record_action'`.

- [ ] **Step 3: Add the toast + label wiring**

In `src/tea_clipper/ui/tray.py`, keep a reference to the toggle action and connect the new
signals. Change the menu construction so the "Toggle recording" action is stored:

```python
        menu = QMenu()
        menu.addAction(self._action("Open settings", self._open_settings))
        menu.addAction(self._action("Save clip now", host.save_clip))
        self._record_action = self._action("Start recording", host.toggle_record)
        menu.addAction(self._record_action)
        menu.addAction(self._action("Open clips folder", self._open_folder))
        menu.addAction(self._action("Configure shortcuts…", self._open_shortcuts))
        menu.addSeparator()
        menu.addAction(self._action("Quit", self._quit))
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

        host.state_changed.connect(self._on_state)
        host.clip_saved.connect(self._on_clip_saved)
        host.recording_changed.connect(self._on_recording_changed)
        self._on_state(host.state, "")
```

Add the two handlers (e.g. after `_on_state`):

```python
    def _on_clip_saved(self, path: str) -> None:
        self.showMessage("Clip saved", Path(path).name)

    def _on_recording_changed(self, recording: bool) -> None:
        self._record_action.setText("Stop recording" if recording else "Start recording")
        if recording:
            self.showMessage("tea-clipper", "Recording started")
```

(`Path` is already imported at the top of `tray.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_tray.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS (entire unit suite).

- [ ] **Step 6: Commit**

```bash
git add src/tea_clipper/ui/tray.py tests/test_tray.py
git commit -m "feat: tray clip-saved toast + recording menu-label sync"
```

---

### Task 5: Manual hardware verification (not CI)

**Files:** none (verification only).

- [ ] **Step 1: Run the GUI and exercise both features**

Run: `.venv/bin/python -m tea_clipper.ui`

Verify:
- Toggling recording via the **hotkey** (Ctrl+Alt+R by default) updates the window Record
  button (checked + "■ Stop recording") and the tray menu label ("Stop recording"); toggling
  again reverts both.
- Toggling via the **tray** menu and the **window button** stays consistent across all three.
- A hotkey **Save clip** (Ctrl+Alt+C) raises a "Clip saved — `<filename>`" desktop toast
  while the window is hidden to tray.
- Starting a recording raises a "Recording started" toast; **stopping** shows only the
  "Clip saved" toast (no duplicate).

- [ ] **Step 2: Record the result**

Add a "Status — UI feedback (toast + record sync)" section to `CLAUDE.md` (match the
existing status-section style) noting the hardware verification, then commit.

```bash
git add CLAUDE.md
git commit -m "docs: record UI-feedback hardware verification"
```
