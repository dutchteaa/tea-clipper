from tea_clipper.audio import (
    AudioDevice,
    _parse_pactl_sources,
    build_audio_fragment,
    resolve_audio_devices,
)


def test_empty_list_returns_none():
    assert build_audio_fragment([]) is None


def test_single_device_builds_one_source_into_mixer():
    frag = build_audio_fragment(["mic.node"])
    assert frag is not None
    assert frag.count("pipewiresrc") == 1
    assert "target-object=mic.node" in frag
    assert "audiomixer name=amix" in frag
    # the fragment must end on the pad the pipeline links opusenc onto
    assert frag.rstrip().endswith("queue name=aenc_in")
    assert "! amix." in frag


def test_multiple_devices_each_link_into_the_mixer():
    frag = build_audio_fragment(["mic.node", "sink.monitor"])
    assert frag.count("pipewiresrc") == 2
    assert frag.count("! amix.") == 2
    assert "target-object=mic.node" in frag
    assert "target-object=sink.monitor" in frag
    assert "audiomixer name=amix" in frag
    assert frag.rstrip().endswith("queue name=aenc_in")
    assert "audioconvert" in frag


class _S:
    """Minimal stand-in for Settings carrying only audio_devices."""

    def __init__(self, audio_devices):
        self.audio_devices = audio_devices


def _available():
    return [
        AudioDevice("sink.a.monitor", "Speakers Monitor", is_monitor=True, is_default=True),
        AudioDevice("sink.b.monitor", "HDMI Monitor", is_monitor=True, is_default=False),
        AudioDevice("mic.a", "Default Mic", is_monitor=False, is_default=True),
        AudioDevice("mic.b", "USB Mic", is_monitor=False, is_default=False),
    ]


def test_tokens_expand_to_defaults():
    out = resolve_audio_devices(_S(["@desktop@", "@mic@"]), _available())
    assert out == ["sink.a.monitor", "mic.a"]


def test_literal_names_pass_through():
    out = resolve_audio_devices(_S(["mic.b", "sink.b.monitor"]), _available())
    assert out == ["mic.b", "sink.b.monitor"]


def test_unavailable_entries_are_skipped(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="tea_clipper"):
        out = resolve_audio_devices(_S(["mic.a", "ghost.device"]), _available())
    assert out == ["mic.a"]
    assert "ghost.device" in caplog.text


def test_order_preserved_and_deduped():
    out = resolve_audio_devices(_S(["@mic@", "mic.a", "@desktop@"]), _available())
    assert out == ["mic.a", "sink.a.monitor"]


def test_empty_selection_yields_empty():
    assert resolve_audio_devices(_S([]), _available()) == []


def test_missing_default_token_is_skipped():
    no_default_mic = [
        AudioDevice("sink.a.monitor", "Speakers Monitor", is_monitor=True, is_default=True),
        AudioDevice("mic.b", "USB Mic", is_monitor=False, is_default=False),
    ]
    out = resolve_audio_devices(_S(["@mic@", "@desktop@"]), no_default_mic)
    assert out == ["sink.a.monitor"]


# --- _parse_pactl_sources (the discovery parser) -------------------------------

# Representative `pactl list sources` output: a monitor and a mic, with the kind of
# interleaved fields pactl actually emits between Name/Description (must be ignored).
_PACTL_SOURCES = """\
Source #52
\tState: RUNNING
\tName: alsa_output.usb-Speakers.analog-stereo.monitor
\tDescription: Monitor of USB Speakers Analog Stereo
\tDriver: PipeWire
Source #53
\tState: SUSPENDED
\tName: alsa_input.usb-Mic.analog-stereo
\tDescription: USB Mic Analog Stereo
\tDriver: PipeWire
"""


def test_parse_pactl_sources_reads_name_and_description():
    out = _parse_pactl_sources(_PACTL_SOURCES, default_sink=None, default_source=None)
    assert [d.node_name for d in out] == [
        "alsa_output.usb-Speakers.analog-stereo.monitor",
        "alsa_input.usb-Mic.analog-stereo",
    ]
    assert out[0].display_name == "Monitor of USB Speakers Analog Stereo"
    assert out[1].display_name == "USB Mic Analog Stereo"


def test_parse_pactl_sources_flags_monitors():
    out = _parse_pactl_sources(_PACTL_SOURCES, default_sink=None, default_source=None)
    assert out[0].is_monitor is True   # the .monitor source
    assert out[1].is_monitor is False  # the input mic


def test_parse_pactl_sources_flags_defaults():
    # default sink → its <sink>.monitor is the default desktop device; default source → the mic
    out = _parse_pactl_sources(
        _PACTL_SOURCES,
        default_sink="alsa_output.usb-Speakers.analog-stereo",
        default_source="alsa_input.usb-Mic.analog-stereo",
    )
    assert out[0].is_default is True
    assert out[1].is_default is True


def test_parse_pactl_sources_empty_output():
    assert _parse_pactl_sources("", default_sink=None, default_source=None) == []
