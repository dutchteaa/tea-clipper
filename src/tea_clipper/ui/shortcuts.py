"""Open the compositor's global-shortcut editor.

Global shortcuts are owned by the compositor (we only suggest defaults via the
GlobalShortcuts portal), so "change keybinds" means opening KDE's own editor.
Editors are tried in order; the first one found on PATH is launched.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("tea_clipper")

_SHORTCUT_EDITORS = (
    ["systemsettings", "kcm_keys"],
    ["kcmshell6", "kcm_keys"],
    ["systemsettings5", "kcm_keys"],
)


def open_shortcuts_editor() -> bool:
    """Launch the system shortcut editor. Returns True if one was started."""
    for cmd in _SHORTCUT_EDITORS:
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd)
                return True
            except OSError:
                log.exception("failed to launch %s", cmd[0])
    return False
