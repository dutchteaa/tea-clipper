# Single-instance lock — design

**Date:** 2026-06-21
**Status:** Approved (brainstorm) → ready for implementation plan

## Problem

`tea-clipper` has two entrypoints:

- `python -m tea_clipper.ui` (`tea-clipper`) — Qt GUI with a window + tray; capture runs on
  a worker thread.
- `python -m tea_clipper` (`tea-clipper-daemon`) — headless daemon on a GLib main loop.

Both open an `org.freedesktop.portal.ScreenCast` session, a rolling replay buffer, a
manual-record branch, and register the same `org.freedesktop.portal.GlobalShortcuts`. A
second concurrent instance (of either kind) would open a second screencast session + buffer
and fight over the hotkeys. We need at most **one** instance running at a time, across
**both** entrypoints.

## Goals

- Mutual exclusion across both entrypoints: running either of GUI/daemon blocks launching
  either again.
- When a **second GUI** launch is blocked by a running **GUI**, raise/focus the existing
  window (un-hide from tray) instead of doing nothing visible, then exit.
- No stale-lock problem after a crash.
- Degrade gracefully: if the lock file can't be created at all, log and proceed rather than
  permanently blocking launch.

## Non-goals

- D-Bus single-instance activation (`org.freedesktop.Application`) — heavier; YAGNI given
  the existing Qt app and the headless daemon.
- Raising a window when the running holder is the headless daemon (it has none) — the
  blocked GUI just logs and exits.
- Cross-machine / cross-user coordination — the lock is per-user (runtime dir).

## Approach

Two cleanly separated layers:

1. **Lock layer (both entrypoints)** — a `fcntl.flock`-based lock file. Works for the
   GLib-based daemon (no Qt needed), and the OS auto-releases the lock on process
   exit/crash, so there is no stale-PID cleanup.
2. **Activation layer (GUI only)** — a Qt `QLocalServer`/`QLocalSocket` channel so a
   blocked second GUI can tell the running GUI to raise its window.

Alternatives rejected: D-Bus single-instance name (heavier, awkward for the daemon); Qt
`QLockFile` only (Qt-only — awkward in the GLib daemon — and can't signal a window raise).

## Components

### `src/tea_clipper/single_instance.py` (no Qt dependency)

Usable by both entrypoints.

- `lock_path() -> Path` — returns `$XDG_RUNTIME_DIR/tea-clipper.lock`, falling back to
  `tempfile.gettempdir()/tea-clipper.lock` when `XDG_RUNTIME_DIR` is unset/empty. Pure
  (reads env only); unit-testable.
- `class InstanceLock`
  - `__init__(path: Path | None = None)` — defaults to `lock_path()`.
  - `acquire() -> bool` — open the lock file (`O_CREAT | O_RDWR`), then
    `fcntl.flock(fd, LOCK_EX | LOCK_NB)`.
    - success → keep the fd open on the instance (held for the process lifetime), write the
      current PID into the file for debuggability, return `True`.
    - `BlockingIOError` / `OSError` from `flock` (contention) → close fd, return `False`.
    - failure to **open/create** the file (e.g. permissions) → log a warning and return
      `True` (degrade gracefully; never block launch on an unusable lock dir).
  - `release() -> None` — `flock(LOCK_UN)` + close, if held; idempotent.

  Callers use `acquire()` + `release()` (in a `finally`) directly, since the boolean return
  of `acquire()` drives control flow. No context-manager sugar — it would hide the bool.

### `src/tea_clipper/ui/instance_server.py` (Qt, GUI-only)

- `SERVER_NAME = "tea-clipper"` — the local-socket name (lives in the runtime dir on Linux).
- `serve(on_activate: Callable[[], None]) -> QLocalServer` — call
  `QLocalServer.removeServer(SERVER_NAME)` first (clears a stale socket left by a crash),
  then `listen(SERVER_NAME)`; connect `newConnection` to a handler that drains the
  connection and calls `on_activate()`. Returns the server so the caller keeps it alive.
- `try_activate() -> bool` — `QLocalSocket.connectToServer(SERVER_NAME)` with a short
  timeout; on success write a byte + flush + return `True`; otherwise `False` (no server,
  i.e. either nothing running or the holder is the headless daemon).

### `MainWindow.bring_to_front()`

New method on the existing window: `showNormal()` (restore if minimized) → `show()`
(un-hide from tray) → `raise_()` → `activateWindow()`. Idempotent and safe to call when
already visible.

## Flow

### GUI — `ui/app.py`

```
app = QApplication(...)
lock = InstanceLock()
if not lock.acquire():
    try_activate()          # raise the running GUI's window (no-op vs daemon holder)
    log "tea-clipper is already running"
    return 0
# acquired:
server = serve(window.bring_to_front)   # keep ref alive (e.g. app._tea_instance_server)
... normal startup (host.start(), updater, etc.) ...
try:
    return app.exec()
finally:
    lock.release()
```

The lock is acquired *before* building `EngineHost` / starting capture, so a blocked
launch never touches the portal.

### Daemon — `__main__.py`

```
lock = InstanceLock()
if not lock.acquire():
    print("tea-clipper is already running.", file=sys.stderr)
    return 1
try:
    ... build_controller / run ...
finally:
    lock.release()
```

Acquired *before* `build_controller()` (which blocks on portal negotiation), so a blocked
daemon launch never opens a portal.

## Exit codes

- GUI blocked: `return 0` — it did its job (activated the running instance / nothing to do).
- Daemon blocked: `return 1` — it could not start its service.

## Error handling

- Unusable lock dir/file (open fails, not contention): warn + proceed without protection.
- Stale `QLocalServer` socket after a crash: `removeServer()` before `listen()`.
- `try_activate()` failures (timeout, refused): swallow — the GUI exits regardless.
- Lock fd: held on the `InstanceLock` instance; released in the entrypoint's `finally`
  (and by the OS on exit as a backstop).

## Testing

Consistent with the project convention (unit-test pure/logic, probe real IPC/portal):

- **Unit (headless):**
  - `lock_path()` — `XDG_RUNTIME_DIR` set vs unset (fallback).
  - `InstanceLock` — first `acquire()` on a tmp path is `True`; a second `InstanceLock` on
    the same path is `False`; after `release()` a new acquire is `True` again.
- **Unit (offscreen `qapp` fixture):**
  - `MainWindow.bring_to_front()` — hide → `bring_to_front()` → `isVisible()` is `True`.
  - `serve` + `try_activate` round-trip — start a server with a recording `on_activate`,
    call `try_activate()`, spin the event loop briefly, assert the callback fired and the
    return was `True`; with no server, `try_activate()` is `False`.
- **Manual / probe:** launch two `tea-clipper` processes → second raises the first's window
  and exits 0; launch `tea-clipper-daemon` then `tea-clipper` (and vice-versa) → second is
  blocked.

## Files touched

- New: `src/tea_clipper/single_instance.py`, `src/tea_clipper/ui/instance_server.py`.
- Edit: `src/tea_clipper/ui/app.py`, `src/tea_clipper/__main__.py`,
  `src/tea_clipper/ui/main_window.py` (add `bring_to_front`).
- New tests: `tests/test_single_instance.py`, plus a `bring_to_front` case in the existing
  main-window tests and a `serve`/`try_activate` case (offscreen).
