from pathlib import Path

from tea_clipper.settings import Settings


def test_defaults_are_sensible():
    s = Settings()
    assert s.clip_length_seconds == 30
    assert s.codec == "h264"
    assert s.hardware is True
    assert s.bitrate_kbps == 30000
    assert s.fps == 60
    assert s.segment_seconds == 2


def test_toml_round_trip(tmp_path: Path):
    s = Settings(clip_length_seconds=45, codec="hevc", hardware=False, bitrate_kbps=12000)
    cfg = tmp_path / "config.toml"
    s.save(cfg)
    loaded = Settings.load(cfg)
    assert loaded == s


def test_load_missing_file_returns_defaults(tmp_path: Path):
    loaded = Settings.load(tmp_path / "nope.toml")
    assert loaded == Settings()


def test_audio_devices_default_is_desktop_and_mic():
    s = Settings()
    assert s.audio_devices == ["@desktop@", "@mic@"]


def test_audio_devices_round_trip(tmp_path: Path):
    s = Settings(audio_devices=["@mic@", "alsa_input.usb-Blue_Yeti.analog-stereo"])
    cfg = tmp_path / "config.toml"
    s.save(cfg)
    assert Settings.load(cfg).audio_devices == [
        "@mic@",
        "alsa_input.usb-Blue_Yeti.analog-stereo",
    ]


def test_audio_devices_empty_means_no_audio(tmp_path: Path):
    s = Settings(audio_devices=[])
    cfg = tmp_path / "config.toml"
    s.save(cfg)
    assert Settings.load(cfg).audio_devices == []


def test_skipped_update_version_default_is_empty():
    assert Settings().skipped_update_version == ""


def test_skipped_update_version_round_trip(tmp_path: Path):
    s = Settings(skipped_update_version="v0.2.0")
    cfg = tmp_path / "config.toml"
    s.save(cfg)
    assert Settings.load(cfg).skipped_update_version == "v0.2.0"
