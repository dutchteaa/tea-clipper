"""Background update check + dialog for the GUI (python -m tea_clipper.ui)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from tea_clipper.update_check import (
    CURRENT_VERSION,
    UpdateInfo,
    fetch_latest_release,
    should_prompt,
)


def decide_update_action(info: UpdateInfo | None, settings) -> str:
    """'prompt' if a newer, un-skipped release exists; else 'ignore'. Pure."""
    if info is None:
        return "ignore"
    if should_prompt(info.version, CURRENT_VERSION, settings.skipped_update_version):
        return "prompt"
    return "ignore"


class _FetchWorker(QObject):
    done = Signal(object)  # UpdateInfo | None

    def run(self) -> None:
        self.done.emit(fetch_latest_release())


class UpdateChecker(QObject):
    """Run the fetch on a worker thread; show the dialog on the main thread."""

    def __init__(self, settings, config_path, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._config_path = Path(config_path)
        self._thread = QThread()
        self._worker = _FetchWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)

    def start(self) -> None:
        self._thread.start()

    def _on_done(self, info) -> None:
        self._thread.quit()
        if decide_update_action(info, self._settings) == "prompt":
            self._show_dialog(info)

    def _show_dialog(self, info: UpdateInfo) -> None:
        box = QMessageBox()
        box.setWindowTitle("tea-clipper update available")
        box.setText(f"A new version is available: {info.version}")
        box.setInformativeText(info.notes or "See the release page for details.")
        update = box.addButton("Update", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is update:
            QDesktopServices.openUrl(QUrl(info.url))
        elif clicked is skip:
            self._settings.skipped_update_version = info.version
            self._settings.save(self._config_path)
