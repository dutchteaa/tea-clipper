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
from uuid import uuid4

from gi.repository import Gio, GLib

from tea_clipper.portal import (
    PortalCancelledError,
    PortalFailedError,
    PortalUnavailableError,
)

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
