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

from tea_clipper.audio import AudioDevice, discover_audio_devices, resolve_audio_devices
from tea_clipper.settings import Settings
from tea_clipper.ui.audio_picker import AudioPicker
from tea_clipper.ui.level_meter import LevelMeterBar, MicLevelMonitor


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
        monitor_factory=MicLevelMonitor,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if codecs is None:
            from tea_clipper.encoders import EncoderRegistry

            codecs = EncoderRegistry().available_codecs()
        if devices is None:
            devices = discover_audio_devices()
        self._devices = devices
        self._monitor_factory = monitor_factory
        self._monitor = None
        self._base = Settings()

        self.clip_length = _spin(1, 600, self._base.clip_length_seconds)
        self.codec = QComboBox()
        self.codec.addItems(codecs)
        self.hardware = QCheckBox("Use hardware encoder (VAAPI)")
        self.bitrate = _spin(500, 200000, self._base.bitrate_kbps)
        self.fps = _spin(1, 240, self._base.fps)
        self.output_dir = QLineEdit(self._base.output_dir)
        self.audio = AudioPicker(devices=devices)

        self.gate_enabled = QCheckBox("Enable noise gate (mic)")
        self.gate_db = _spin(-60, -10, int(round(self._base.mic_noise_gate_db)))
        self.meter = LevelMeterBar()
        self.gate_enabled.toggled.connect(self.gate_db.setEnabled)
        self.gate_db.valueChanged.connect(
            lambda v: self.meter.set_threshold(float(v))
        )
        self.gate_db.setEnabled(self.gate_enabled.isChecked())
        self.meter.set_threshold(float(self.gate_db.value()))

        layout = QFormLayout(self)
        layout.addRow("Clip length (s)", self.clip_length)
        layout.addRow("Codec", self.codec)
        layout.addRow("", self.hardware)
        layout.addRow("Bitrate (kbps)", self.bitrate)
        layout.addRow("FPS", self.fps)
        layout.addRow("Output folder", self.output_dir)
        layout.addRow("Audio sources", self.audio)
        layout.addRow("", self.gate_enabled)
        layout.addRow("Gate threshold (dB)", self.gate_db)
        layout.addRow("Mic level", self.meter)

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
        self.gate_enabled.setChecked(settings.mic_noise_gate_enabled)
        self.gate_db.setValue(int(round(settings.mic_noise_gate_db)))
        self.gate_db.setEnabled(settings.mic_noise_gate_enabled)
        self.meter.set_threshold(float(self.gate_db.value()))

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
            mic_noise_gate_enabled=self.gate_enabled.isChecked(),
            mic_noise_gate_db=float(self.gate_db.value()),
        )

    def start_metering(self) -> None:
        """Begin live mic metering for the currently-selected mics (no-op if running)."""
        if self._monitor is not None:
            return
        mics = [
            d for d in resolve_audio_devices(self._base, self._devices)
            if not d.is_monitor
        ]
        self._monitor = self._monitor_factory(mics)
        self._monitor.level_changed.connect(self.meter.set_level)
        self._monitor.start()

    def stop_metering(self) -> None:
        """Tear down the metering pipeline (no-op if not running)."""
        if self._monitor is None:
            return
        self._monitor.stop()
        self._monitor = None
