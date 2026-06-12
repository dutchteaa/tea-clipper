# HotkeyService Design — Global Shortcuts via xdg-desktop-portal

**Date:** 2026-06-12
**Status:** Approved (user delegated remaining decisions)
**Follows:** the PortalManager plan; reuses the same portal Request/Response machinery.

## Goal

Register global shortcuts through `org.freedesktop.portal.GlobalShortcuts` so the user can
trigger the two core actions — **save the last N seconds** (`save_clip`) and **start/stop
manual recording** (`toggle_record`) — from anywhere, including inside a fullscreen game.
`HotkeyService` negotiates and binds the shortcuts, listens for activations, and dispatches
them to zero-argument callbacks that the future `Controller` wires to the engine.

## Scope

**In scope**
- `HotkeyService` — session negotiation, shortcut binding, a long-lived `Activated`
  listener, and a pub/sub dispatch to per-action callbacks.
- `GlobalShortcutsPortal` — a standalone raw Gio/GDBus wrapper (its own copy of the
  session/await-response machinery; `ScreenCastPortal` is left untouched, per the chosen
  approach).
- `build_shortcuts_list()` — a pure helper producing the BindShortcuts argument.
- `hotkey_probe` — a runnable script for real-hardware verification.
- Mocked unit tests for the pure helper and orchestration.

**Out of scope (deferred)**
- Additional actions (pause buffer, mute mic) — only `save_clip` + `toggle_record` now.
- In-app key capture / rebinding UI — the compositor (KDE) owns binding; users rebind in
  System Settings.
- The `Controller` that wires shortcut callbacks to `ReplayBuffer`/`ManualRecorder`.
- Persisting triggers in `Settings` — ids/descriptions/triggers are code constants.

## Decisions

- **D-Bus access:** `gi.repository.Gio` (GDBus), no new dependency — mirrors `ScreenCastPortal`.
- **Code organization:** standalone `hotkeys.py`; duplicate the ~40 lines of session
  machinery rather than refactor the untested-but-working `ScreenCastPortal` (extract a
  shared base only if a third portal consumer appears).
- **Binding model:** portal-native. The app declares id + description + preferred trigger;
  KDE owns the live binding and rebinding. No in-app key capture.
- **Default triggers:** `save_clip` → `CTRL+ALT+c`, `toggle_record` → `CTRL+ALT+r`
  (suggestions only; the user may change them in KDE).
- **Lifetime:** `HotkeyService` owns a long-lived `GLib.MainLoop` on a daemon thread (its
  own `GMainContext`), since shortcut activations arrive for the whole app lifetime. A
  `run_loop=False` flag lets a caller that already runs a main loop (the `Controller`) skip
  the extra thread and dispatch on its own loop.
- **Errors:** reuse `portal.py`'s exception types (`PortalUnavailableError`,
  `PortalCancelledError`, `PortalFailedError`) — the only coupling to `portal.py`.
- **Testing:** mocked D-Bus unit tests + a manual `hotkey_probe` (mirrors PortalManager).

## Architecture

```
HotkeyService (orchestration, unit-tested with a fake portal)
  └─ GlobalShortcutsPortal (raw Gio/GDBus, probe-verified only)
       CreateSession ──► BindShortcuts([save_clip, toggle_record])
       subscribe "Activated" ──► shortcut_id ──► HotkeyService._dispatch
  build_shortcuts_list()  (pure, no bus, unit-tested)
```

### Components

**`HotkeyService` (orchestration, unit-tested)**
```python
SAVE_CLIP = "save_clip"
TOGGLE_RECORD = "toggle_record"

class HotkeyService:
    def __init__(self, portal=None) -> None: ...
    def add_listener(self, action: str, callback: Callable[[], None]) -> None: ...
    def start(self, run_loop: bool = True) -> None: ...
    def stop(self) -> None: ...
    @property
    def is_running(self) -> bool: ...
```
Holds `{SAVE_CLIP: [...], TOGGLE_RECORD: [...]}` listener lists. `start()` lazily creates a
real `GlobalShortcutsPortal` (when `portal is None`), negotiates a session, binds the
shortcuts, registers `_dispatch` as the activation callback, and (if `run_loop`) starts the
loop thread. `_dispatch(shortcut_id)` calls every listener for that id; unknown ids are
ignored. `stop()` quits/joins the loop and closes the session.

**`GlobalShortcutsPortal` (raw D-Bus, hardware-verified)** — its own bus connection,
sender, `_token()`, and `_await_response()` (duplicated from `ScreenCastPortal`). Methods:
`create_session()`, `bind_shortcuts(session, shortcuts, parent_window="")`,
`connect_activated(callback)` (subscribes to the `Activated(o, s, t, a{sv})` signal and
calls `callback(shortcut_id)`), and `close_session(session)`.

**`build_shortcuts_list()` (pure)** — returns the `a(sa{sv})` payload: a list of
`(id, {"description": Variant("s", …), "preferred_trigger": Variant("s", …)})` for the two
actions, in a fixed order.

**`hotkey_probe` (`src/tea_clipper/hotkey_probe.py`, `__main__`)** — registers print
listeners for both actions, starts the service, and runs ~30s so the user can press the
keys (binding them in KDE first if prompted) and watch activations log. Not in the suite.

## Data flow

1. `start()` → `create_session()` → `bind_shortcuts(build_shortcuts_list())`.
2. `connect_activated(self._dispatch)` subscribes to `Activated`.
3. User presses a bound key → portal emits `Activated(session, shortcut_id, ts, opts)` →
   wrapper calls `_dispatch(shortcut_id)`.
4. `_dispatch` runs the listeners registered for that id.
5. `stop()` quits the loop, joins the thread, closes the session.

## Error handling

`GlobalShortcutsPortal.__init__` raises `PortalUnavailableError` if
`org.freedesktop.portal.Desktop` is absent. The Request/Response handshake raises
`PortalCancelledError` (code 1) or `PortalFailedError` (other non-zero), reusing the types
from `portal.py`. Callers (probe; later the Controller/UI) surface these rather than crash.

## Testing

**Unit (`tests/test_hotkeys.py`, CI, no real bus):**
- `build_shortcuts_list()` → asserts the two ids in order, their descriptions, and preferred
  triggers (via `GLib.Variant.unpack()`).
- Orchestration with a `FakeShortcutsPortal` and `start(run_loop=False)`:
  - `start()` binds exactly `[save_clip, toggle_record]`.
  - a faked `Activated(save_clip)` fires only the `save_clip` listeners.
  - multiple listeners on one action all fire.
  - an unknown shortcut id is a no-op (no error).
  - `stop()` closes the session.

**Manual (`hotkey_probe`):** on the KDE/Wayland target, confirm the shortcuts appear in
System Settings, and pressing them logs `save_clip` / `toggle_record` activations.

## File structure

```
src/tea_clipper/hotkeys.py        # SAVE_CLIP/TOGGLE_RECORD, build_shortcuts_list,
                                  # GlobalShortcutsPortal, HotkeyService
src/tea_clipper/hotkey_probe.py   # __main__ real-hardware probe
tests/test_hotkeys.py             # pure helper + orchestration tests (fake portal)
```
