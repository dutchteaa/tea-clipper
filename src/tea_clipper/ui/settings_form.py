"""Settings <-> Qt widget mapping with a load/collect round-trip."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from tea_clipper.audio import AudioDevice
from tea_clipper.settings import Settings
from tea_clipper.ui.audio_picker import AudioPicker


def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setValue(value)
    return box


class SettingsForm(QWidget):
    """Edit the user-facing Settings fields. Fields not shown here (segment_seconds,
    buffer_dir, source_restore_token) are preserved across load -> collect."""

    def __init__(
        self,
        codecs: list[str] | None = None,
        devices: list[AudioDevice] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if codecs is None:
            from tea_clipper.encoders import EncoderRegistry

            codecs = EncoderRegistry().available_codecs()
        self._base = Settings()

        self.clip_length = _spin(1, 600, self._base.clip_length_seconds)
        self.codec = QComboBox()
        self.codec.addItems(codecs)
        self.hardware = QCheckBox("Use hardware encoder (VAAPI)")
        self.bitrate = _spin(500, 200000, self._base.bitrate_kbps)
        self.fps = _spin(1, 240, self._base.fps)
        self.output_dir = QLineEdit(self._base.output_dir)
        self.audio = AudioPicker(devices=devices)

        layout = QFormLayout(self)
        layout.addRow("Clip length (s)", self.clip_length)
        layout.addRow("Codec", self.codec)
        layout.addRow("", self.hardware)
        layout.addRow("Bitrate (kbps)", self.bitrate)
        layout.addRow("FPS", self.fps)
        layout.addRow("Output folder", self.output_dir)
        layout.addRow("Audio sources", self.audio)

    def _select_codec(self, codec: str) -> None:
        idx = self.codec.findText(codec)
        if idx < 0:
            self.codec.addItem(codec)
            idx = self.codec.findText(codec)
        self.codec.setCurrentIndex(idx)

    def load(self, settings: Settings) -> None:
        self._base = settings
        self.clip_length.setValue(settings.clip_length_seconds)
        self._select_codec(settings.codec)
        self.hardware.setChecked(settings.hardware)
        self.bitrate.setValue(settings.bitrate_kbps)
        self.fps.setValue(settings.fps)
        self.output_dir.setText(settings.output_dir)
        self.audio.set_selection(settings.audio_devices)

    def collect(self) -> Settings:
        return replace(
            self._base,
            clip_length_seconds=self.clip_length.value(),
            codec=self.codec.currentText(),
            hardware=self.hardware.isChecked(),
            bitrate_kbps=self.bitrate.value(),
            fps=self.fps.value(),
            output_dir=self.output_dir.text(),
            audio_devices=self.audio.selected_entries(),
        )
