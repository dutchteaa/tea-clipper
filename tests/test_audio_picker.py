from tea_clipper.audio import AudioDevice
from tea_clipper.ui.audio_picker import AudioPicker


def _devices():
    return [
        AudioDevice("alsa.sink.hdmi", "HDMI Out", is_monitor=True, is_default=True),
        AudioDevice("alsa.sink.spk", "Speakers", is_monitor=True, is_default=False),
        AudioDevice("alsa.src.jbl", "JBL Mic", is_monitor=False, is_default=True),
    ]


def test_selected_entries_tokens_and_nodes(qapp):
    picker = AudioPicker(devices=_devices())
    picker.set_selection(["@desktop@", "alsa.src.jbl"])
    assert picker.selected_entries() == ["@desktop@", "alsa.src.jbl"]


def test_selected_entries_order_is_special_then_devices(qapp):
    picker = AudioPicker(devices=_devices())
    picker.set_selection(["alsa.sink.spk", "@mic@"])
    # special rows are emitted before concrete device rows, top-to-bottom
    assert picker.selected_entries() == ["@mic@", "alsa.sink.spk"]


def test_empty_selection_is_video_only(qapp):
    picker = AudioPicker(devices=_devices())
    picker.set_selection([])
    assert picker.selected_entries() == []


def test_round_trip_default_tokens(qapp):
    picker = AudioPicker(devices=_devices())
    picker.set_selection(["@desktop@", "@mic@"])
    assert picker.selected_entries() == ["@desktop@", "@mic@"]
