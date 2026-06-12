# HotkeyService Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register the `save_clip` and `toggle_record` global shortcuts through `org.freedesktop.portal.GlobalShortcuts` and dispatch their activations to zero-argument callbacks the future Controller wires to the engine.

**Architecture:** A standalone `hotkeys.py` module with three layers mirroring `portal.py`: a pure `build_shortcuts_list()` helper, a `GlobalShortcutsPortal` raw Gio/GDBus wrapper (its own copy of the session/await-response machinery; `ScreenCastPortal` untouched), and a `HotkeyService` orchestrator that binds the shortcuts, subscribes to the `Activated` signal on a long-lived loop thread, and fans activations out to per-action listeners. Pure helper + orchestration are unit-tested with a fake portal; the raw wrapper is verified by a probe script on real hardware.

**Tech Stack:** Python 3.12+ · `gi.repository.Gio`/`GLib` (GDBus, no new dependency) · pytest. Spec: `docs/superpowers/specs/2026-06-12-hotkeyservice-design.md`.

---

## File Structure

```
src/tea_clipper/hotkeys.py        # CREATE: constants, build_shortcuts_list, HotkeyService, GlobalShortcutsPortal
src/tea_clipper/hotkey_probe.py   # CREATE: __main__ real-hardware probe
tests/test_hotkeys.py             # CREATE: pure-helper + orchestration unit tests (fake portal, no real bus)
```

**Boundaries:**
- `hotkeys.py` owns all GlobalShortcuts D-Bus knowledge. Pure helper + `HotkeyService` are
  unit-tested with a fake portal; `GlobalShortcutsPortal` (raw Gio) is hardware-verified via
  the probe.
- The only coupling to `portal.py` is importing its exception classes.
- The probe is the end-to-end proof; it is not part of the automated suite.

---

## Task 1: Constants + pure `build_shortcuts_list()`

**Files:**
- Create: `src/tea_clipper/hotkeys.py`
- Test: `tests/test_hotkeys.py`

- [ ] **Step 1: Write the failing test** `tests/test_hotkeys.py`

```python
from tea_clipper.hotkeys import (
    SAVE_CLIP,
    TOGGLE_RECORD,
    build_shortcuts_list,
)


def test_build_shortcuts_list_ids_in_order():
    shortcuts = build_shortcuts_list()
    assert [s[0] for s in shortcuts] == [SAVE_CLIP, TOGGLE_RECORD]


def test_build_shortcuts_list_descriptions_and_triggers():
    shortcuts = build_shortcuts_list()
    save_opts = shortcuts[0][1]
    assert save_opts["description"].unpack() == "Save clip (last N seconds)"
    assert save_opts["preferred_trigger"].unpack() == "CTRL+ALT+c"
    rec_opts = shortcuts[1][1]
    assert rec_opts["description"].unpack() == "Toggle manual recording"
    assert rec_opts["preferred_trigger"].unpack() == "CTRL+ALT+r"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_hotkeys.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tea_clipper.hotkeys'`

- [ ] **Step 3: Create `src/tea_clipper/hotkeys.py` with the pure part**

```python
"""Global shortcuts via org.freedesktop.portal.GlobalShortcuts.

Layering (mirrors portal.py):
  * pure helper (this section) — build the BindShortcuts payload, no D-Bus, unit-tested.
  * HotkeyService — orchestration over a GlobalShortcutsPortal collaborator, unit-tested
    with a fake portal.
  * GlobalShortcutsPortal — the raw Gio/GDBus wrapper, verified on real hardware by
    src/tea_clipper/hotkey_probe.py (not part of the automated suite).
"""

from __future__ import annotations

from gi.repository import GLib

# Shortcut action ids (also the keys consumers register listeners under).
SAVE_CLIP = "save_clip"
TOGGLE_RECORD = "toggle_record"

# (id, human description, preferred default trigger). The compositor owns the real binding;
# the trigger here is only a suggested default the user may change in System Settings.
_SHORTCUTS = [
    (SAVE_CLIP, "Save clip (last N seconds)", "CTRL+ALT+c"),
    (TOGGLE_RECORD, "Toggle manual recording", "CTRL+ALT+r"),
]


def build_shortcuts_list() -> list[tuple[str, dict[str, GLib.Variant]]]:
    """Build the a(sa{sv}) payload for BindShortcuts, in a fixed action order."""
    return [
        (
            sid,
            {
                "description": GLib.Variant("s", description),
                "preferred_trigger": GLib.Variant("s", trigger),
            },
        )
        for sid, description, trigger in _SHORTCUTS
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_hotkeys.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/hotkeys.py tests/test_hotkeys.py
git commit -m "feat: hotkey constants and pure build_shortcuts_list helper"
```

---

## Task 2: HotkeyService orchestration

**Files:**
- Modify: `src/tea_clipper/hotkeys.py` (add `HotkeyService`)
- Test: `tests/test_hotkeys.py` (add orchestration tests with a fake portal)

`HotkeyService` sequences the portal steps through an injectable `GlobalShortcutsPortal`.
Tests inject a fake and use `run_loop=False`, so no real bus or thread is touched.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_hotkeys.py`)

```python
from tea_clipper.hotkeys import HotkeyService


class FakeShortcutsPortal:
    """Records calls and lets tests fire activations, standing in for GlobalShortcutsPortal."""

    def __init__(self):
        self.calls = []
        self.closed = []
        self._activated = None

    def create_session(self):
        self.calls.append("create")
        return "/gs/session/1"

    def bind_shortcuts(self, session, shortcuts, parent_window=""):
        self.calls.append(("bind", session, [s[0] for s in shortcuts]))

    def connect_activated(self, callback):
        self._activated = callback

    def fire(self, shortcut_id):
        assert self._activated is not None, "connect_activated was never called"
        self._activated(shortcut_id)

    def close_session(self, session):
        self.closed.append(session)


def test_start_binds_expected_shortcuts():
    fake = FakeShortcutsPortal()
    svc = HotkeyService(portal=fake)
    svc.start(run_loop=False)
    bind = next(c for c in fake.calls if c[0] == "bind")
    assert bind[2] == [SAVE_CLIP, TOGGLE_RECORD]
    assert svc.is_running


def test_activated_dispatches_to_matching_listener():
    fake = FakeShortcutsPortal()
    svc = HotkeyService(portal=fake)
    saves, records = [], []
    svc.add_listener(SAVE_CLIP, lambda: saves.append(1))
    svc.add_listener(TOGGLE_RECORD, lambda: records.append(1))
    svc.start(run_loop=False)
    fake.fire(SAVE_CLIP)
    assert saves == [1]
    assert records == []


def test_multiple_listeners_all_fire():
    fake = FakeShortcutsPortal()
    svc = HotkeyService(portal=fake)
    hits = []
    svc.add_listener(SAVE_CLIP, lambda: hits.append("a"))
    svc.add_listener(SAVE_CLIP, lambda: hits.append("b"))
    svc.start(run_loop=False)
    fake.fire(SAVE_CLIP)
    assert hits == ["a", "b"]


def test_unknown_shortcut_id_is_ignored():
    fake = FakeShortcutsPortal()
    svc = HotkeyService(portal=fake)
    fired = []
    svc.add_listener(SAVE_CLIP, lambda: fired.append(1))
    svc.start(run_loop=False)
    fake.fire("bogus")  # no registered listener; must not raise
    assert fired == []


def test_stop_closes_session():
    fake = FakeShortcutsPortal()
    svc = HotkeyService(portal=fake)
    svc.start(run_loop=False)
    svc.stop()
    assert fake.closed == ["/gs/session/1"]
    assert not svc.is_running
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_hotkeys.py -v`
Expected: FAIL with `ImportError: cannot import name 'HotkeyService'`

- [ ] **Step 3: Add imports and `HotkeyService` to `src/tea_clipper/hotkeys.py`**

Change the import block at the top of the file from:

```python
from __future__ import annotations

from gi.repository import GLib
```

to:

```python
from __future__ import annotations

import threading
from typing import Callable

from gi.repository import GLib
```

Then append the class (after `build_shortcuts_list`, before any `GlobalShortcutsPortal`
added later):

```python
class HotkeyService:
    """Binds global shortcuts and fans their activations out to per-action listeners.

    Listeners are zero-argument callables registered under an action id (SAVE_CLIP /
    TOGGLE_RECORD). On an Activated(shortcut_id) signal, every listener for that id runs.
    Owns a long-lived GLib main loop on a daemon thread so activations arrive for the whole
    app lifetime; pass ``run_loop=False`` if a caller already drives a main loop.
    """

    def __init__(self, portal=None) -> None:
        self._portal = portal  # None -> create a real GlobalShortcutsPortal lazily in start()
        self._listeners: dict[str, list[Callable[[], None]]] = {}
        self._session = None
        self._context = None
        self._loop = None
        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def add_listener(self, action: str, callback: Callable[[], None]) -> None:
        self._listeners.setdefault(action, []).append(callback)

    def _dispatch(self, shortcut_id: str) -> None:
        for cb in list(self._listeners.get(shortcut_id, [])):
            cb()

    def start(self, run_loop: bool = True) -> None:
        if self._portal is None:
            self._portal = GlobalShortcutsPortal()
        self._session = self._portal.create_session()
        self._portal.bind_shortcuts(self._session, build_shortcuts_list())
        self._running = True
        if run_loop:
            # Subscribe to Activated on the loop thread's own context so signals dispatch
            # there, independent of any other GLib loop in the process.
            self._context = GLib.MainContext()
            self._loop = GLib.MainLoop(self._context)
            started = threading.Event()

            def run():
                self._context.push_thread_default()
                self._portal.connect_activated(self._dispatch)
                started.set()
                self._loop.run()
                self._context.pop_thread_default()

            self._thread = threading.Thread(target=run, daemon=True)
            self._thread.start()
            started.wait(timeout=2)
        else:
            # Caller drives a loop (or it's a test); subscribe on the current context.
            self._portal.connect_activated(self._dispatch)

    def stop(self) -> None:
        self._running = False
        if self._loop is not None:
            self._loop.quit()
            self._loop = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._session is not None and self._portal is not None:
            self._portal.close_session(self._session)
            self._session = None
```

> Note: `GlobalShortcutsPortal` is referenced lazily inside `start()`, so this task's tests
> (which inject `portal=` and use `run_loop=False`) never touch the real class — it's added
> in Task 3, and the module imports cleanly until then.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_hotkeys.py -v`
Expected: 7 passed (2 from Task 1 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/hotkeys.py tests/test_hotkeys.py
git commit -m "feat: HotkeyService binds shortcuts and dispatches activations to listeners"
```

---

## Task 3: GlobalShortcutsPortal — the raw Gio/GDBus wrapper

**Files:**
- Modify: `src/tea_clipper/hotkeys.py` (add `GlobalShortcutsPortal`)

The only code that talks to the real bus. It cannot be unit-tested headlessly (needs a live
portal + a human pressing keys), so it has **no automated test** — verified by the probe in
Task 4. The code below is complete.

- [ ] **Step 1: Add the Gio/uuid/exception imports**

Change the import block at the top of `src/tea_clipper/hotkeys.py` from:

```python
from __future__ import annotations

import threading
from typing import Callable

from gi.repository import GLib
```

to:

```python
from __future__ import annotations

import threading
from typing import Callable
from uuid import uuid4

from gi.repository import Gio, GLib

from tea_clipper.portal import (
    PortalCancelledError,
    PortalFailedError,
    PortalUnavailableError,
)
```

- [ ] **Step 2: Append `GlobalShortcutsPortal` to `src/tea_clipper/hotkeys.py`**

```python
_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_GLOBALSHORTCUTS_IFACE = "org.freedesktop.portal.GlobalShortcuts"
_REQUEST_IFACE = "org.freedesktop.portal.Request"
_SESSION_IFACE = "org.freedesktop.portal.Session"


class GlobalShortcutsPortal:
    """Thin synchronous wrapper over the GlobalShortcuts portal D-Bus interface.

    create_session/bind_shortcuts use the Request/Response handshake (block on a private
    GLib loop until the response arrives). connect_activated subscribes to the long-lived
    Activated signal and forwards the shortcut id to a callback.
    """

    def __init__(self, connection=None) -> None:
        self._bus = connection or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._require_portal()
        self._sender = self._bus.get_unique_name()[1:].replace(".", "_")
        self._shortcuts = Gio.DBusProxy.new_sync(
            self._bus, Gio.DBusProxyFlags.NONE, None,
            _PORTAL_BUS, _PORTAL_PATH, _GLOBALSHORTCUTS_IFACE, None,
        )
        self._activated_sub = None

    def _require_portal(self) -> None:
        try:
            self._bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", "GetNameOwner",
                GLib.Variant("(s)", (_PORTAL_BUS,)),
                None, Gio.DBusCallFlags.NONE, -1, None,
            )
        except GLib.Error as exc:
            raise PortalUnavailableError(
                "org.freedesktop.portal.Desktop is not available on the session bus"
            ) from exc

    @staticmethod
    def _token() -> str:
        return "tea" + uuid4().hex

    def _await_response(self, token: str, call_fn) -> dict:
        request_path = f"{_PORTAL_PATH}/request/{self._sender}/{token}"
        loop = GLib.MainLoop()
        box: dict = {}

        def on_response(_conn, _sender, _path, _iface, _signal, params):
            box["code"], box["results"] = params.unpack()
            loop.quit()

        sub = self._bus.signal_subscribe(
            _PORTAL_BUS, _REQUEST_IFACE, "Response", request_path, None,
            Gio.DBusSignalFlags.NONE, on_response,
        )
        try:
            call_fn()
            loop.run()
        finally:
            self._bus.signal_unsubscribe(sub)

        code = box.get("code", 2)
        if code == 1:
            raise PortalCancelledError("global-shortcuts request was cancelled")
        if code != 0:
            raise PortalFailedError(f"global-shortcuts request failed (response code {code})")
        return box["results"]

    def create_session(self) -> str:
        token = self._token()
        opts = {
            "handle_token": GLib.Variant("s", token),
            "session_handle_token": GLib.Variant("s", self._token()),
        }
        results = self._await_response(token, lambda: self._shortcuts.call_sync(
            "CreateSession", GLib.Variant("(a{sv})", (opts,)),
            Gio.DBusCallFlags.NONE, -1, None,
        ))
        return results["session_handle"]

    def bind_shortcuts(self, session, shortcuts, parent_window="") -> None:
        token = self._token()
        opts = {"handle_token": GLib.Variant("s", token)}
        self._await_response(token, lambda: self._shortcuts.call_sync(
            "BindShortcuts",
            GLib.Variant("(oa(sa{sv})sa{sv})", (session, shortcuts, parent_window, opts)),
            Gio.DBusCallFlags.NONE, -1, None,
        ))

    def connect_activated(self, callback) -> None:
        def on_activated(_conn, _sender, _path, _iface, _signal, params):
            _session, shortcut_id, _timestamp, _opts = params.unpack()
            callback(shortcut_id)

        self._activated_sub = self._bus.signal_subscribe(
            _PORTAL_BUS, _GLOBALSHORTCUTS_IFACE, "Activated", _PORTAL_PATH, None,
            Gio.DBusSignalFlags.NONE, on_activated,
        )

    def close_session(self, session) -> None:
        if self._activated_sub is not None:
            self._bus.signal_unsubscribe(self._activated_sub)
            self._activated_sub = None
        Gio.DBusProxy.new_sync(
            self._bus, Gio.DBusProxyFlags.NONE, None,
            _PORTAL_BUS, session, _SESSION_IFACE, None,
        ).call_sync("Close", None, Gio.DBusCallFlags.NONE, -1, None)
```

- [ ] **Step 3: Verify the module imports and the suite is unaffected**

Run: `.venv/bin/python -c "import tea_clipper.hotkeys"`
Expected: no output, exit 0 (imports cleanly; no bus connection at import time).

Run: `.venv/bin/pytest tests/test_hotkeys.py -v`
Expected: 7 passed (unchanged — these never instantiate `GlobalShortcutsPortal`).

- [ ] **Step 4: Commit**

```bash
git add src/tea_clipper/hotkeys.py
git commit -m "feat: GlobalShortcutsPortal Gio/GDBus wrapper with Activated signal listener"
```

---

## Task 4: hotkey_probe — real-hardware verification script

**Files:**
- Create: `src/tea_clipper/hotkey_probe.py`

A runnable script (not part of pytest) that proves real shortcut delivery on the
KDE/Wayland target: register the shortcuts, then log activations as the user presses keys.

- [ ] **Step 1: Create `src/tea_clipper/hotkey_probe.py`**

```python
"""Manual real-hardware probe for global shortcuts.

Run on the KDE/Wayland target:  .venv/bin/python -m tea_clipper.hotkey_probe
If the keys don't fire, bind them in System Settings > Shortcuts, then press them.
"""

from __future__ import annotations

import sys
import time

from tea_clipper.hotkeys import SAVE_CLIP, TOGGLE_RECORD, HotkeyService
from tea_clipper.portal import PortalError


def main(argv: list[str] | None = None) -> int:
    svc = HotkeyService()
    svc.add_listener(SAVE_CLIP, lambda: print("  >> save_clip activated"))
    svc.add_listener(TOGGLE_RECORD, lambda: print("  >> toggle_record activated"))

    print("Registering global shortcuts...")
    try:
        svc.start()
    except PortalError as exc:
        print(f"Portal error: {exc}", file=sys.stderr)
        return 1

    print("Registered. Suggested triggers: Ctrl+Alt+C (save), Ctrl+Alt+R (record).")
    print("If they don't fire, bind them in System Settings > Shortcuts, then press them.")
    print("Listening for 30s...")
    try:
        time.sleep(30)
    finally:
        svc.stop()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-check the script imports (no portal)**

Run: `.venv/bin/python -c "import tea_clipper.hotkey_probe"`
Expected: no output, exit 0.

- [ ] **Step 3: Manual hardware run (on the KDE/Wayland desktop, not CI)**

Run: `.venv/bin/python -m tea_clipper.hotkey_probe`
Expected: prints "Registered…"; the two shortcuts appear in System Settings > Shortcuts
(under the tea-clipper / portal application). Pressing the bound keys logs
`save_clip activated` / `toggle_record activated`.

> If this step can't run now (headless session), leave it unchecked and note in the commit
> that hardware verification is pending. The automated suite stays green regardless.

- [ ] **Step 4: Commit**

```bash
git add src/tea_clipper/hotkey_probe.py
git commit -m "feat: hotkey_probe script for real-hardware global-shortcut verification"
```

---

## Task 5: Docs + full-suite verification + finish

**Files:**
- Modify: `CLAUDE.md` (status update)

- [ ] **Step 1: Run the entire suite**

Run: `.venv/bin/pytest -m "engine or not engine"`
Expected: all green — including the new `tests/test_hotkeys.py` (9 tests) alongside
settings/encoders/replay-buffer/portal unit tests and the engine integration tests.

- [ ] **Step 2: Add a HotkeyService status section to `CLAUDE.md`**

After the PortalManager status section, add a short "Status — HotkeyService" section noting:
implemented (TDD) on the `hotkey-service` branch; `hotkeys.HotkeyService` binds `save_clip`
+ `toggle_record` via `org.freedesktop.portal.GlobalShortcuts` and dispatches activations to
zero-arg listeners; standalone `GlobalShortcutsPortal` (ScreenCast untouched); pure helper +
orchestration unit-tested with a fake portal; hardware verification via
`python -m tea_clipper.hotkey_probe` (pending if not yet run). Reference the spec
(`docs/superpowers/specs/2026-06-12-hotkeyservice-design.md`) and this plan. Note that
`Controller` (wiring shortcut callbacks to `ReplayBuffer.save_last` / `ManualRecorder`),
real desktop+mic audio, and the PySide6 UI remain deferred. Match the existing format.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record HotkeyService (global shortcuts) in CLAUDE.md status"
```

- [ ] **Step 4: Finish the branch**

Use superpowers:finishing-a-development-branch to verify tests, present integration
options, and complete the work (PR into `main`, like portal-manager).

---

## Done criteria

- `pytest` green: new `tests/test_hotkeys.py` (pure helper + orchestration with a fake
  portal) alongside all existing tests.
- `HotkeyService.start()` binds the two shortcuts and routes `Activated(id)` to the
  listeners registered for that id; `stop()` closes the session.
- `python -m tea_clipper.hotkey_probe` registers the shortcuts and logs activations on the
  KDE/Wayland target (manual verification).

## Deliberately deferred (later plans)

- `Controller` wiring `save_clip → ReplayBuffer.save_last` and
  `toggle_record → ManualRecorder.start/stop`, owning the app main loop.
- Additional shortcuts (pause buffer, mute mic), real desktop+mic audio, the PySide6 UI.
