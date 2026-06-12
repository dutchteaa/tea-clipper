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

from gi.repository import GLib

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
