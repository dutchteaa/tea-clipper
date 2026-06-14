"""Checkable grouped audio-device picker mapping to settings.audio_devices."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from tea_clipper.audio import DESKTOP_TOKEN, MIC_TOKEN, AudioDevice, discover_audio_devices

_ENTRY_ROLE = Qt.ItemDataRole.UserRole


class AudioPicker(QWidget):
    """Pick which audio sources to mix. Rows: default-desktop/default-mic tokens, then
    concrete sinks (desktop) and sources (mics). Checked rows -> settings.audio_devices."""

    def __init__(self, devices: list[AudioDevice] | None = None, parent=None) -> None:
        super().__init__(parent)
        if devices is None:
            devices = discover_audio_devices()
        self._list = QListWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)
        self._populate(devices)

    def _add_row(self, label: str, entry: str) -> None:
        item = QListWidgetItem(label, self._list)
        item.setData(_ENTRY_ROLE, entry)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)

    def _populate(self, devices: list[AudioDevice]) -> None:
        self._add_row("Default desktop audio", DESKTOP_TOKEN)
        self._add_row("Default microphone", MIC_TOKEN)
        for d in devices:
            if d.is_monitor:
                suffix = " [default]" if d.is_default else ""
                self._add_row(f"Desktop: {d.display_name}{suffix}", d.node_name)
        for d in devices:
            if not d.is_monitor:
                suffix = " [default]" if d.is_default else ""
                self._add_row(f"Mic: {d.display_name}{suffix}", d.node_name)

    def set_selection(self, entries: list[str]) -> None:
        wanted = set(entries)
        for i in range(self._list.count()):
            item = self._list.item(i)
            checked = item.data(_ENTRY_ROLE) in wanted
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def selected_entries(self) -> list[str]:
        out: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(_ENTRY_ROLE))
        return out
