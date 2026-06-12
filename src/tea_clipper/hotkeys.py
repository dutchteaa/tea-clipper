"""Global shortcuts via org.freedesktop.portal.GlobalShortcuts.

Layering (mirrors portal.py):
  * pure helper (this section) — build the BindShortcuts payload, no D-Bus, unit-tested.
  * HotkeyService — orchestration over a GlobalShortcutsPortal collaborator, unit-tested
    with a fake portal.
  * GlobalShortcutsPortal — the raw Gio/GDBus wrapper, verified on real hardware by
    src/tea_clipper/hotkey_probe.py (not part of the automated suite).
"""

from __future__ import annotations

import threading
from typing import Callable

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
