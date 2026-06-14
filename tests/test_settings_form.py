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
