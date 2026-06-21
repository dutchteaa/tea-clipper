# Single-instance Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure at most one `tea-clipper` instance runs at a time across both entrypoints, and have a blocked second GUI raise the running GUI's window instead of starting a second capture session.

**Architecture:** Two layers. (1) A `fcntl.flock` lock file in the runtime dir gives cross-entrypoint mutual exclusion (works for the GLib daemon; auto-released by the OS on crash). (2) A Qt `QLocalServer`/`QLocalSocket` channel, GUI-only, lets a blocked second GUI tell the running GUI to un-hide/focus its window.

**Tech Stack:** Python 3.12+, stdlib `fcntl`/`os`/`tempfile`, PySide6 (`QLocalServer`, `QLocalSocket`), pytest with the offscreen `qapp` fixture.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-21-single-instance-design.md`.
- Lock file path: `$XDG_RUNTIME_DIR/tea-clipper.lock`, fallback `tempfile.gettempdir()/tea-clipper.lock` when `XDG_RUNTIME_DIR` is unset/empty.
- Local-socket name: `"tea-clipper"`.
- The lock layer (`single_instance.py`) must have **no Qt dependency** (the headless daemon imports it).
- Degrade gracefully: if the lock file can't be opened/created (not contention), log a warning and return `True` (never permanently block launch).
- Exit codes when blocked: GUI → `0`; daemon → `1`.
- Acquire the lock **before** any portal/capture work (`build_controller` / `EngineHost.start`).
- Convention: unit-test pure logic + offscreen-Qt round-trips; real launcher behavior is probe/manual-verified.
- Tests run via `.venv/bin/pytest`. Qt tests use the session `qapp` fixture from `tests/conftest.py` (offscreen).

---

### Task 1: `single_instance` lock module

**Files:**
- Create: `src/tea_clipper/single_instance.py`
- Test: `tests/test_single_instance.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `lock_path() -> pathlib.Path`
  - `class InstanceLock` with `__init__(self, path: Path | None = None)`, `acquire(self) -> bool`, `release(self) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_single_instance.py
from pathlib import Path

from tea_clipper.single_instance import InstanceLock, lock_path


def test_lock_path_uses_xdg_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert lock_path() == tmp_path / "tea-clipper.lock"


def test_lock_path_falls_back_to_tempdir(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    import tempfile

    assert lock_path() == Path(tempfile.gettempdir()) / "tea-clipper.lock"


def test_second_acquire_on_same_path_fails(tmp_path):
    path = tmp_path / "tea-clipper.lock"
    first = InstanceLock(path)
    second = InstanceLock(path)
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    # once released, a fresh lock can acquire again
    third = InstanceLock(path)
    assert third.acquire() is True
    third.release()


def test_release_is_idempotent(tmp_path):
    lock = InstanceLock(tmp_path / "tea-clipper.lock")
    assert lock.acquire() is True
    lock.release()
    lock.release()  # must not raise


def test_unusable_lock_dir_degrades_to_true(tmp_path):
    # path inside a non-existent, non-creatable directory -> open fails, not contention
    bad = tmp_path / "nope" / "deeper" / "tea-clipper.lock"
    lock = InstanceLock(bad)
    assert lock.acquire() is True  # degrades gracefully
    lock.release()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_single_instance.py -v`
Expected: FAIL (ModuleNotFoundError: tea_clipper.single_instance)

- [ ] **Step 3: Write the implementation**

```python
# src/tea_clipper/single_instance.py
"""Cross-entrypoint single-instance lock (no Qt dependency).

A flock-based lock file in the runtime dir gives mutual exclusion across both the GUI
(`python -m tea_clipper.ui`) and the headless daemon (`python -m tea_clipper`). The OS
releases the lock automatically on process exit/crash, so there is no stale-PID cleanup.
"""

from __future__ import annotations

import fcntl
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCK_NAME = "tea-clipper.lock"


def lock_path() -> Path:
    """Return the lock file path: $XDG_RUNTIME_DIR, else the system temp dir."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path(tempfile.gettempdir())
    return base / _LOCK_NAME


class InstanceLock:
    """An exclusive, non-blocking flock held for the process lifetime."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else lock_path()
        self._fd: int | None = None

    def acquire(self) -> bool:
        """True if we hold the lock (or the lock is unusable); False on contention."""
        try:
            fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o644)
        except OSError as exc:
            logger.warning("single-instance lock unusable (%s); proceeding without it", exc)
            return True
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd
        return True

    def release(self) -> None:
        """Release the lock and close the fd. Idempotent."""
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(self._fd)
        self._fd = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_single_instance.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/single_instance.py tests/test_single_instance.py
git commit -m "feat: add flock-based single-instance lock"
```

---

### Task 2: GUI activation channel (`instance_server`)

**Files:**
- Create: `src/tea_clipper/ui/instance_server.py`
- Test: `tests/test_instance_server.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `SERVER_NAME = "tea-clipper"` (str)
  - `serve(on_activate: Callable[[], None]) -> QLocalServer`
  - `try_activate() -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_instance_server.py
from tea_clipper.ui.instance_server import SERVER_NAME, serve, try_activate


def _spin(app, ms=200):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_try_activate_false_when_nothing_listening(qapp):
    from PySide6.QtNetwork import QLocalServer

    QLocalServer.removeServer(SERVER_NAME)  # ensure clean
    assert try_activate() is False


def test_serve_then_activate_fires_callback(qapp):
    fired = []
    server = serve(lambda: fired.append(True))
    try:
        assert try_activate() is True
        _spin(qapp)
        assert fired == [True]
    finally:
        server.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_instance_server.py -v`
Expected: FAIL (ModuleNotFoundError: tea_clipper.ui.instance_server)

- [ ] **Step 3: Write the implementation**

```python
# src/tea_clipper/ui/instance_server.py
"""GUI-only activation channel over a Qt local socket.

The running GUI listens on a named local socket; a second GUI launch connects as a client
to ask the running instance to raise its window, then exits.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

SERVER_NAME = "tea-clipper"


def serve(on_activate: Callable[[], None]) -> QLocalServer:
    """Listen for activation requests; call on_activate() for each one.

    Caller must keep the returned server alive for the app's lifetime.
    """
    QLocalServer.removeServer(SERVER_NAME)  # clear a stale socket from a crashed run
    server = QLocalServer()

    def _handle() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        on_activate()

    server.newConnection.connect(_handle)
    if not server.listen(SERVER_NAME):
        logger.warning("could not listen on local socket %r: %s", SERVER_NAME, server.errorString())
    return server


def try_activate() -> bool:
    """Ask a running GUI to raise its window. False if none is listening."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(500):
        return False
    sock.write(b"activate")
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_instance_server.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/ui/instance_server.py tests/test_instance_server.py
git commit -m "feat: add GUI local-socket activation channel"
```

---

### Task 3: `MainWindow.bring_to_front()`

**Files:**
- Modify: `src/tea_clipper/ui/main_window.py` (add a method to `MainWindow`)
- Test: `tests/test_main_window.py` (add one test)

**Interfaces:**
- Consumes: existing `MainWindow(host, settings)` constructor.
- Produces: `MainWindow.bring_to_front(self) -> None`.

- [ ] **Step 1: Write the failing test (append to `tests/test_main_window.py`)**

```python
def test_bring_to_front_unhides_window(qapp):
    from tea_clipper.ui.main_window import MainWindow

    host = FakeHost()
    win = MainWindow(host, Settings())
    win.hide()
    assert win.isVisible() is False
    win.bring_to_front()
    assert win.isVisible() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_main_window.py::test_bring_to_front_unhides_window -v`
Expected: FAIL (AttributeError: 'MainWindow' object has no attribute 'bring_to_front')

- [ ] **Step 3: Add the method to `MainWindow` (in `src/tea_clipper/ui/main_window.py`)**

```python
    def bring_to_front(self) -> None:
        """Un-hide from tray and focus the window. Safe to call when already visible."""
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_main_window.py::test_bring_to_front_unhides_window -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/ui/main_window.py tests/test_main_window.py
git commit -m "feat: add MainWindow.bring_to_front"
```

---

### Task 4: Wire the lock + activation into both entrypoints

**Files:**
- Modify: `src/tea_clipper/ui/app.py`
- Modify: `src/tea_clipper/__main__.py`

**Interfaces:**
- Consumes: `InstanceLock` (Task 1); `serve`, `try_activate` (Task 2); `MainWindow.bring_to_front` (Task 3).
- Produces: nothing for later tasks (terminal wiring task).

This task is integration wiring around code that already touches the real portal, so it has no new unit test; it is verified by the full suite staying green plus the manual probe in Task 5.

- [ ] **Step 1: Edit `src/tea_clipper/ui/app.py`**

Add imports near the other `tea_clipper.ui` imports:

```python
from tea_clipper.single_instance import InstanceLock
from tea_clipper.ui.instance_server import serve, try_activate
```

Replace the body of `main()` from the `app = QApplication(...)` setup onward so the lock is
acquired right after the QApplication is created and before `EngineHost`. The full edited
`main()` reads:

```python
def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Path.home() / ".config" / "tea-clipper" / "config.toml"
    settings = Settings.load(config)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("tea-clipper")
    app.setApplicationDisplayName("tea-clipper")
    app.setDesktopFileName("tea-clipper")  # ties window/tray to a stable app identity
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)  # closing the window hides to tray

    lock = InstanceLock()
    if not lock.acquire():
        try_activate()  # raise the running GUI's window (no-op if a daemon holds the lock)
        logging.info("tea-clipper is already running; raised the existing window.")
        return 0

    try:
        host = EngineHost(settings, config)
        window = MainWindow(host, settings)
        tray = TrayIcon(host, window, settings)
        tray.show()
        window.show()

        app._tea_instance_server = serve(window.bring_to_front)  # keep ref alive

        host.start()  # auto-start capture (picker may appear the first time)

        updater = UpdateChecker(settings, config)
        updater.start()
        app._tea_updater = updater  # keep a reference alive for the app's lifetime

        return app.exec()
    finally:
        lock.release()
```

- [ ] **Step 2: Edit `src/tea_clipper/__main__.py`**

Add the import near the other `tea_clipper` imports:

```python
from tea_clipper.single_instance import InstanceLock
```

Replace the body of `main()` so the lock is acquired before `build_controller()`. The full
edited `main()` reads:

```python
def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Path.home() / ".config" / "tea-clipper" / "config.toml"
    settings = Settings.load(config)

    lock = InstanceLock()
    if not lock.acquire():
        print("tea-clipper is already running.", file=sys.stderr)
        return 1

    try:
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
    finally:
        lock.release()
```

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS (128 prior + 8 new = 136 passed; count is approximate — all green is the gate)

- [ ] **Step 4: Commit**

```bash
git add src/tea_clipper/ui/app.py src/tea_clipper/__main__.py
git commit -m "feat: enforce single instance in both entrypoints"
```

---

### Task 5: Manual hardware verification + status docs

**Files:**
- Modify: `CLAUDE.md` (add a "Status — single-instance lock" section)

This task is the probe-verify step (consistent with the project's IPC/portal convention) plus the status writeup. No code.

- [ ] **Step 1: Verify GUI-vs-GUI window raise**

Run in two terminals:
```bash
.venv/bin/python -m tea_clipper.ui   # terminal 1: starts, then hide window to tray
.venv/bin/python -m tea_clipper.ui   # terminal 2
```
Expected: terminal 2 logs "already running", exits 0, and terminal 1's window pops to the front.

- [ ] **Step 2: Verify cross-entrypoint exclusion**

```bash
.venv/bin/python -m tea_clipper          # terminal 1: leave running
.venv/bin/python -m tea_clipper.ui       # terminal 2: should print/log already running, exit 0
```
Then the reverse:
```bash
.venv/bin/python -m tea_clipper.ui       # terminal 1: leave running
.venv/bin/python -m tea_clipper          # terminal 2: should print "tea-clipper is already running.", exit 1
```
Expected: in every case the second launch does not open a second portal/capture session.

- [ ] **Step 3: Record status in `CLAUDE.md`**

Add a `## Status — single-instance lock` section summarizing: the flock lock + Qt
activation design, the spec/plan paths, the test count, and the hardware-verification
result. Update the NEXT SESSION handoff to mark item 2 (single-instance lock) done.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record single-instance lock status"
```

---

## Self-Review

- **Spec coverage:** lock module (Task 1) ✓; activation channel (Task 2) ✓; `bring_to_front` (Task 3) ✓; both-entrypoint wiring + exit codes + acquire-before-portal (Task 4) ✓; graceful-degrade and contention covered by Task 1 tests ✓; stale-socket `removeServer` in Task 2 ✓; manual probe (Task 5) ✓.
- **Placeholders:** none — all steps carry real code/commands.
- **Type consistency:** `lock_path`/`InstanceLock.acquire`/`release`, `serve`/`try_activate`/`SERVER_NAME`, and `bring_to_front` names are used identically across producing and consuming tasks.
