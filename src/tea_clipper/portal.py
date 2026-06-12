"""Real screen capture via org.freedesktop.portal.ScreenCast.

Layering:
  * pure helpers (this section) — option/result/fragment logic, no D-Bus, unit-tested.
  * PortalManager — orchestration over a ScreenCastPortal collaborator, unit-tested
    with a fake portal.
  * ScreenCastPortal — the raw Gio/GDBus wrapper, verified on real hardware by
    src/tea_clipper/portal_probe.py (not part of the automated suite).
"""

from __future__ import annotations

import os
from uuid import uuid4

from gi.repository import Gio, GLib

# SelectSources option values (xdg-desktop-portal ScreenCast).
MONITOR = 1          # source type: whole monitor
CURSOR_EMBEDDED = 2  # draw the cursor into the captured frames
PERSIST_MODE = 2     # persist permissions until explicitly revoked


class PortalError(Exception):
    """Base class for screen-cast portal failures."""


class PortalUnavailableError(PortalError):
    """The desktop portal (org.freedesktop.portal.Desktop) is not on the bus."""


class PortalCancelledError(PortalError):
    """The user dismissed the screen-cast picker."""


class PortalFailedError(PortalError):
    """The portal reported a failure or returned no usable stream."""


def build_select_sources_options(
    restore_token: str = "",
    *,
    types: int = MONITOR,
    cursor_mode: int = CURSOR_EMBEDDED,
    persist_mode: int = PERSIST_MODE,
) -> dict[str, GLib.Variant]:
    """Build the a{sv} options for SelectSources. Omits an empty restore token."""
    opts: dict[str, GLib.Variant] = {
        "types": GLib.Variant("u", types),
        "cursor_mode": GLib.Variant("u", cursor_mode),
        "persist_mode": GLib.Variant("u", persist_mode),
    }
    if restore_token:
        opts["restore_token"] = GLib.Variant("s", restore_token)
    return opts


def parse_start_results(results: dict) -> tuple[int, str]:
    """Extract (node_id, restore_token) from a Start response's results dict."""
    streams = results.get("streams") or []
    if not streams:
        raise PortalFailedError("portal returned no screen-cast streams")
    node_id = streams[0][0]
    return node_id, results.get("restore_token", "")


def build_video_fragment(fd: int, node_id: int) -> str:
    """The pipewiresrc launch fragment CapturePipeline consumes as its video source."""
    return f"pipewiresrc fd={fd} path={node_id} ! videoconvert ! queue name=venc_in"


class PortalManager:
    """Negotiates a ScreenCast session and yields a pipewiresrc video fragment.

    Reuses ``settings.source_restore_token`` when present and writes a fresh token
    back onto the Settings instance (persisting to disk is the caller's job).
    Keeps the portal session + PipeWire fd alive until ``close()``.
    """

    def __init__(self, settings, portal=None) -> None:
        self._settings = settings
        self._portal = portal  # None -> create a real ScreenCastPortal lazily in open()
        self._session = None
        self._fd: int | None = None

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def open(self) -> str:
        if self._portal is None:
            self._portal = ScreenCastPortal()
        session = self._portal.create_session()
        try:
            self._portal.select_sources(
                session,
                types=MONITOR,
                cursor_mode=CURSOR_EMBEDDED,
                persist_mode=PERSIST_MODE,
                restore_token=self._settings.source_restore_token,
            )
            results = self._portal.start(session)
            node_id, restore_token = parse_start_results(results)
            if restore_token:
                self._settings.source_restore_token = restore_token
            fd = self._portal.open_pipewire_remote(session)
        except Exception:
            self._portal.close_session(session)
            raise
        self._session = session
        self._fd = fd
        return build_video_fragment(fd, node_id)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._session is not None and self._portal is not None:
            self._portal.close_session(self._session)
            self._session = None


_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
_REQUEST_IFACE = "org.freedesktop.portal.Request"
_SESSION_IFACE = "org.freedesktop.portal.Session"


class ScreenCastPortal:
    """Thin synchronous wrapper over the ScreenCast portal D-Bus interface.

    Each request-style method subscribes to its Request's ``Response`` signal, invokes
    the method, and blocks on a private GLib main loop until the response arrives,
    translating the response code into a return value or a PortalError.
    """

    def __init__(self, connection=None) -> None:
        self._bus = connection or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._require_portal()
        # Request object paths are /…/request/<SENDER>/<TOKEN>, where SENDER is our
        # unique bus name without the leading ':' and with '.' replaced by '_'.
        self._sender = self._bus.get_unique_name()[1:].replace(".", "_")
        self._screencast = Gio.DBusProxy.new_sync(
            self._bus, Gio.DBusProxyFlags.NONE, None,
            _PORTAL_BUS, _PORTAL_PATH, _SCREENCAST_IFACE, None,
        )

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
            call_fn()      # the portal method returns the Request path; we ignore it
            loop.run()
        finally:
            self._bus.signal_unsubscribe(sub)

        code = box.get("code", 2)
        if code == 1:
            raise PortalCancelledError("user dismissed the screen-cast picker")
        if code != 0:
            raise PortalFailedError(f"portal request failed (response code {code})")
        return box["results"]

    def create_session(self) -> str:
        token = self._token()
        opts = {
            "handle_token": GLib.Variant("s", token),
            "session_handle_token": GLib.Variant("s", self._token()),
        }
        results = self._await_response(token, lambda: self._screencast.call_sync(
            "CreateSession", GLib.Variant("(a{sv})", (opts,)),
            Gio.DBusCallFlags.NONE, -1, None,
        ))
        return results["session_handle"]

    def select_sources(self, session, *, types, cursor_mode, persist_mode, restore_token="") -> None:
        token = self._token()
        opts = build_select_sources_options(
            restore_token, types=types, cursor_mode=cursor_mode, persist_mode=persist_mode
        )
        opts["handle_token"] = GLib.Variant("s", token)
        self._await_response(token, lambda: self._screencast.call_sync(
            "SelectSources", GLib.Variant("(oa{sv})", (session, opts)),
            Gio.DBusCallFlags.NONE, -1, None,
        ))

    def start(self, session, parent_window="") -> dict:
        token = self._token()
        opts = {"handle_token": GLib.Variant("s", token)}
        return self._await_response(token, lambda: self._screencast.call_sync(
            "Start", GLib.Variant("(osa{sv})", (session, parent_window, opts)),
            Gio.DBusCallFlags.NONE, -1, None,
        ))

    def open_pipewire_remote(self, session) -> int:
        ret, fd_list = self._screencast.call_with_unix_fd_list_sync(
            "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (session, {})),
            Gio.DBusCallFlags.NONE, -1, None, None,
        )
        (fd_index,) = ret.unpack()
        return fd_list.get(fd_index)

    def close_session(self, session) -> None:
        Gio.DBusProxy.new_sync(
            self._bus, Gio.DBusProxyFlags.NONE, None,
            _PORTAL_BUS, session, _SESSION_IFACE, None,
        ).call_sync("Close", None, Gio.DBusCallFlags.NONE, -1, None)
