"""System-tray icon + menu for tea-clipper."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from tea_clipper.ui.engine_host import EngineHost
from tea_clipper.ui.icons import app_icon
from tea_clipper.ui.main_window import MainWindow

log = logging.getLogger("tea_clipper")

# Global shortcuts are owned by the compositor (we only suggest defaults), so "change
# keybinds" means opening KDE's own shortcut editor. Tried in order; first found wins.
_SHORTCUT_EDITORS = (
    ["systemsettings", "kcm_keys"],
    ["kcmshell6", "kcm_keys"],
    ["systemsettings5", "kcm_keys"],
)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, host: EngineHost, window: MainWindow, settings, parent=None) -> None:
        super().__init__(app_icon(), parent)
        self._host = host
        self._window = window
        self._settings = settings

        menu = QMenu()
        menu.addAction(self._action("Open settings", self._open_settings))
        menu.addAction(self._action("Save clip now", host.save_clip))
        menu.addAction(self._action("Toggle recording", host.toggle_record))
        menu.addAction(self._action("Open clips folder", self._open_folder))
        menu.addAction(self._action("Configure shortcuts…", self._open_shortcuts))
        menu.addSeparator()
        menu.addAction(self._action("Quit", self._quit))
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

        host.state_changed.connect(self._on_state)
        self._on_state(host.state, "")

    def _action(self, label: str, slot) -> QAction:
        action = QAction(label, self)
        action.triggered.connect(slot)
        return action

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._open_settings()

    def _open_settings(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _open_folder(self) -> None:
        out = self._settings.output_dir
        Path(out).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def _open_shortcuts(self) -> None:
        for cmd in _SHORTCUT_EDITORS:
            if shutil.which(cmd[0]):
                try:
                    subprocess.Popen(cmd)
                    return
                except OSError:
                    log.exception("failed to launch %s", cmd[0])
        self.showMessage(
            "Configure shortcuts",
            "Open KDE System Settings → Shortcuts to rebind tea-clipper "
            "(Save clip / Toggle recording).",
        )

    def _on_state(self, state: str, detail: str) -> None:
        tip = f"tea-clipper — {state}"
        if detail:
            tip += f" ({detail})"
        self.setToolTip(tip)

    def _quit(self) -> None:
        self._host.stop()
        QApplication.quit()
