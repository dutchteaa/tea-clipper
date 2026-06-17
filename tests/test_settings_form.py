from tea_clipper.audio import AudioDevice
from tea_clipper.settings import Settings
from tea_clipper.ui.settings_form import SettingsForm


def _form():
    return SettingsForm(
        codecs=["h264", "hevc", "av1"],
        devices=[AudioDevice("alsa.src.jbl", "JBL", is_monitor=False, is_default=True)],
    )


def test_round_trip_edited_fields(qapp):
    s = Settings(
        clip_length_seconds=45, codec="hevc", hardware=False, bitrate_kbps=12000,
        fps=30, output_dir="/tmp/out", audio_devices=["@mic@"],
    )
    form = _form()
    form.load(s)
    out = form.collect()
    assert out.clip_length_seconds == 45
    assert out.codec == "hevc"
    assert out.hardware is False
    assert out.bitrate_kbps == 12000
    assert out.fps == 30
    assert out.output_dir == "/tmp/out"
    assert out.audio_devices == ["@mic@"]


def test_untouched_fields_preserved(qapp):
    s = Settings(segment_seconds=3, buffer_dir="/tmp/buf", source_restore_token="tok")
    form = _form()
    form.load(s)
    out = form.collect()
    assert out.segment_seconds == 3
    assert out.buffer_dir == "/tmp/buf"
    assert out.source_restore_token == "tok"


def test_unknown_codec_in_settings_is_selectable(qapp):
    # codec not in the probed list should still appear and round-trip
    s = Settings(codec="av1")
    form = _form()
    form.load(s)
    assert form.collect().codec == "av1"


def test_noise_gate_round_trip(qapp):
    s = Settings(mic_noise_gate_enabled=True, mic_noise_gate_db=-30.0)
    form = _form()
    form.load(s)
    out = form.collect()
    assert out.mic_noise_gate_enabled is True
    assert out.mic_noise_gate_db == -30.0


def test_gate_db_disabled_when_gate_off(qapp):
    s = Settings(mic_noise_gate_enabled=False)
    form = _form()
    form.load(s)
    assert form.gate_db.isEnabled() is False


def test_threshold_marker_follows_spinbox(qapp):
    form = _form()
    form.gate_db.setValue(-25)
    assert form.meter._threshold_db == -25.0


def test_start_metering_uses_factory(qapp):
    from PySide6.QtCore import QObject, Signal

    created = {}

    # The fake must expose a real Qt Signal so `level_changed.connect(...)` works.
    class FakeMonitor(QObject):
        level_changed = Signal(float)

        def __init__(self, mics, parent=None):
            super().__init__(parent)
            created["mics"] = mics
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

    form = SettingsForm(
        codecs=["h264"],
        devices=[AudioDevice("mic.x", "Mic X", is_monitor=False, is_default=True)],
        monitor_factory=FakeMonitor,
    )
    form.load(Settings(audio_devices=["@mic@"]))
    form.start_metering()
    assert created["mics"][0].node_name == "mic.x"
    assert form._monitor.started is True
    form.stop_metering()
    assert form._monitor is None
