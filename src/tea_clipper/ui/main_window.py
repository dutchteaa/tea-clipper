"""Settings/status window: status indicator + SettingsForm + action buttons."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tea_clipper.ui.engine_host import EngineHost
from tea_clipper.ui.settings_form import SettingsForm
from tea_clipper.ui.shortcuts import open_shortcuts_editor

_STATE_COLORS = {
    "Idle": "#888", "Starting": "#e0a800", "Recording": "#2e9e2e",
    "Restarting": "#e0a800", "Error": "#c0392b",
}


class MainWindow(QMainWindow):
    def __init__(self, host: EngineHost, settings, parent=None) -> None:
        super().__init__(parent)
        self._host = host
        self.setWindowTitle("tea-clipper")

        self._status = QLabel()
        self._last_clip = QLabel("Last clip: —")
        self._form = SettingsForm()
        self._form.load(settings)

        save_btn = QPushButton("Save clip")
        save_btn.clicked.connect(host.save_clip)
        self._record_btn = QPushButton("● Record")
        self._record_btn.setCheckable(True)
        self._record_btn.clicked.connect(self._on_record_clicked)

        capture = QHBoxLayout()
        capture.addWidget(save_btn)
        capture.addWidget(self._record_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._on_apply)
        folder_btn = QPushButton("Open clips folder")
        folder_btn.clicked.connect(self._on_open_folder)
        repick_btn = QPushButton("Re-pick source")
        repick_btn.clicked.connect(self._on_repick)
        shortcuts_btn = QPushButton("Configure shortcuts…")
        shortcuts_btn.clicked.connect(self._on_shortcuts)

        buttons = QHBoxLayout()
        buttons.addWidget(apply_btn)
        buttons.addWidget(folder_btn)
        buttons.addWidget(repick_btn)
        buttons.addWidget(shortcuts_btn)

        layout = QVBoxLayout()
        layout.addWidget(self._status)
        layout.addWidget(self._last_clip)
        layout.addLayout(capture)
        layout.addWidget(self._form)
        layout.addLayout(buttons)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        host.state_changed.connect(self._on_state)
        host.clip_saved.connect(self._on_clip_saved)
        host.recording_changed.connect(self._on_recording_changed)
        self._on_state(host.state, "")

    def _on_state(self, state: str, detail: str) -> None:
        color = _STATE_COLORS.get(state, "#888")
        text = f"<b>Status:</b> <span style='color:{color}'>● {state}</span>"
        if detail:
            text += f" — {detail}"
        self._status.setText(text)

    def _on_clip_saved(self, path: str) -> None:
        self._last_clip.setText(f"Last clip: {path}")

    def _on_record_clicked(self) -> None:
        # User intent only; the real checked state is driven by recording_changed.
        self._host.toggle_record()

    def _on_recording_changed(self, recording: bool) -> None:
        self._record_btn.setChecked(recording)
        self._record_btn.setText("■ Stop recording" if recording else "● Record")

    def _on_apply(self) -> None:
        confirm = QMessageBox.question(
            self, "Apply settings?",
            "Applying restarts capture: the replay buffer resets and there is a brief gap. "
            "Continue?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._host.apply_settings(self._form.collect())

    def _on_repick(self) -> None:
        confirm = QMessageBox.question(
            self, "Re-pick capture source?",
            "This restarts capture and re-opens the screen picker. Continue?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._host.repick_source()

    def _on_shortcuts(self) -> None:
        if not open_shortcuts_editor():
            QMessageBox.information(
                self, "Configure shortcuts",
                "Couldn't find a system settings editor. Open KDE System Settings → "
                "Shortcuts to rebind tea-clipper (Save clip / Toggle recording).",
            )

    def _on_open_folder(self) -> None:
        out = self._form.collect().output_dir
        Path(out).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._form.start_metering()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._form.stop_metering()

    def closeEvent(self, event) -> None:
        # Hide to tray instead of quitting; capture keeps running.
        event.ignore()
        self.hide()
