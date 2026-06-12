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
