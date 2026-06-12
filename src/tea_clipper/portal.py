"""Real screen capture via org.freedesktop.portal.ScreenCast.

Layering:
  * pure helpers (this section) — option/result/fragment logic, no D-Bus, unit-tested.
  * PortalManager — orchestration over a ScreenCastPortal collaborator, unit-tested
    with a fake portal.
  * ScreenCastPortal — the raw Gio/GDBus wrapper, verified on real hardware by
    src/tea_clipper/portal_probe.py (not part of the automated suite).
"""

from __future__ import annotations

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
