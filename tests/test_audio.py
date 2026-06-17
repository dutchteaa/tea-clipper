from tea_clipper.audio import (
    AudioDevice,
    _parse_pactl_devices,
    build_audio_fragment,
    gate_threshold_linear,
    resolve_audio_devices,
    resolve_gate_threshold,
)


def _mic(name, display="Mic", default=False):
    return AudioDevice(name, display, is_monitor=False, is_default=default)


def _sink(name, display="Speakers", default=False):
    return AudioDevice(name, display, is_monitor=True, is_default=default)


# --- build_audio_fragment ------------------------------------------------------


def test_empty_list_returns_none():
    assert build_audio_fragment([]) is None


def test_single_mic_builds_one_source_into_mixer():
    frag = build_audio_fragment([_mic("mic.node")])
    assert frag is not None
    assert frag.count("pipewiresrc") == 1
    assert "target-object=mic.node" in frag
    assert "audiomixer name=amix" in frag
    assert "! amix." in frag
    # the fragment must end on the pad the pipeline links opusenc onto
    assert frag.rstrip().endswith("queue name=aenc_in")


def test_mic_chain_has_no_capture_sink_property():
    frag = build_audio_fragment([_mic("mic.node")])
    assert "stream.capture.sink" not in frag


def test_desktop_sink_chain_sets_capture_sink_true():
    # desktop audio = capture the SINK node with stream.capture.sink=true (PipeWire has no
    # .monitor node; targeting a sink normally would capture silence).
    frag = build_audio_fragment([_sink("sink.node")])
    assert "target-object=sink.node" in frag
    assert "stream.capture.sink=true" in frag


def test_multiple_devices_each_link_into_the_mixer():
    frag = build_audio_fragment([_sink("sink.node"), _mic("mic.node")])
    assert frag.count("pipewiresrc") == 2
    assert frag.count("! amix.") == 2
    assert "target-object=sink.node" in frag
    assert "target-object=mic.node" in frag
    assert "audioconvert" in frag
    # only the sink gets the capture-sink property
    assert frag.count("stream.capture.sink=true") == 1


def test_mixer_output_is_pinned_to_stereo():
    frag = build_audio_fragment([_mic("mic.node")])
    assert "audio/x-raw,channels=2" in frag


# --- resolve_audio_devices -----------------------------------------------------


class _S:
    """Minimal stand-in for Settings carrying only audio_devices."""

    def __init__(self, audio_devices):
        self.audio_devices = audio_devices


def _available():
    return [
        _sink("sink.a", "Speakers", default=True),
        _sink("sink.b", "HDMI", default=False),
        _mic("mic.a", "Default Mic", default=True),
        _mic("mic.b", "USB Mic", default=False),
    ]


def _names(devices):
    return [d.node_name for d in devices]


def test_tokens_expand_to_defaults():
    out = resolve_audio_devices(_S(["@desktop@", "@mic@"]), _available())
    assert _names(out) == ["sink.a", "mic.a"]


def test_desktop_token_resolves_to_a_sink_device():
    out = resolve_audio_devices(_S(["@desktop@"]), _available())
    assert out[0].is_monitor is True   # so the builder adds stream.capture.sink=true


def test_literal_names_pass_through():
    out = resolve_audio_devices(_S(["mic.b", "sink.b"]), _available())
    assert _names(out) == ["mic.b", "sink.b"]


def test_unavailable_entries_are_skipped(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="tea_clipper"):
        out = resolve_audio_devices(_S(["mic.a", "ghost.device"]), _available())
    assert _names(out) == ["mic.a"]
    assert "ghost.device" in caplog.text


def test_order_preserved_and_deduped():
    out = resolve_audio_devices(_S(["@mic@", "mic.a", "@desktop@"]), _available())
    assert _names(out) == ["mic.a", "sink.a"]


def test_empty_selection_yields_empty():
    assert resolve_audio_devices(_S([]), _available()) == []


def test_missing_default_token_is_skipped():
    no_default_mic = [
        _sink("sink.a", "Speakers", default=True),
        _mic("mic.b", "USB Mic", default=False),
    ]
    out = resolve_audio_devices(_S(["@mic@", "@desktop@"]), no_default_mic)
    assert _names(out) == ["sink.a"]


# --- _parse_pactl_devices (the discovery parser) -------------------------------

# Representative `pactl list sinks` output (interleaved fields must be ignored).
_PACTL_SINKS = """\
Sink #52
\tState: RUNNING
\tName: alsa_output.usb-Speakers.analog-stereo
\tDescription: USB Speakers Analog Stereo
\tDriver: PipeWire
Sink #51
\tState: SUSPENDED
\tName: alsa_output.pci-hdmi.stereo
\tDescription: HDMI Audio
"""

# `pactl list sources` includes both real mics AND pulse-compat <sink>.monitor names.
_PACTL_SOURCES = """\
Source #52
\tState: RUNNING
\tName: alsa_output.usb-Speakers.analog-stereo.monitor
\tDescription: Monitor of USB Speakers Analog Stereo
Source #53
\tState: SUSPENDED
\tName: alsa_input.usb-Mic.analog-stereo
\tDescription: USB Mic Analog Stereo
"""


def test_parse_sinks_become_desktop_devices():
    out = _parse_pactl_devices(_PACTL_SINKS, "", default_sink=None, default_source=None)
    assert _names(out) == [
        "alsa_output.usb-Speakers.analog-stereo",
        "alsa_output.pci-hdmi.stereo",
    ]
    assert all(d.is_monitor for d in out)
    assert out[0].display_name == "USB Speakers Analog Stereo"


def test_parse_drops_pulse_monitor_sources_keeps_real_mics():
    out = _parse_pactl_devices("", _PACTL_SOURCES, default_sink=None, default_source=None)
    # the <sink>.monitor pulse fiction is dropped; only the real mic remains
    assert _names(out) == ["alsa_input.usb-Mic.analog-stereo"]
    assert out[0].is_monitor is False


def test_parse_flags_defaults():
    out = _parse_pactl_devices(
        _PACTL_SINKS,
        _PACTL_SOURCES,
        default_sink="alsa_output.usb-Speakers.analog-stereo",
        default_source="alsa_input.usb-Mic.analog-stereo",
    )
    sink = next(d for d in out if d.node_name == "alsa_output.usb-Speakers.analog-stereo")
    mic = next(d for d in out if d.node_name == "alsa_input.usb-Mic.analog-stereo")
    assert sink.is_default is True and sink.is_monitor is True
    assert mic.is_default is True and mic.is_monitor is False


def test_parse_empty_output():
    assert _parse_pactl_devices("", "", default_sink=None, default_source=None) == []


# --- gate_threshold_linear / resolve_gate_threshold / gate insertion -----------


def test_gate_threshold_linear_known_points():
    assert gate_threshold_linear(0.0) == 1.0
    assert abs(gate_threshold_linear(-40.0) - 0.01) < 1e-6
    assert abs(gate_threshold_linear(-20.0) - 0.1) < 1e-6


def test_gate_threshold_linear_clamped():
    assert gate_threshold_linear(60.0) == 1.0        # never above 1.0
    assert gate_threshold_linear(-1000.0) >= 0.0     # never below 0.0


def test_resolve_gate_threshold_disabled_is_zero():
    s = _S([])
    s.mic_noise_gate_enabled = False
    s.mic_noise_gate_db = -40.0
    assert resolve_gate_threshold(s) == 0.0


def test_resolve_gate_threshold_enabled_is_linear():
    s = _S([])
    s.mic_noise_gate_enabled = True
    s.mic_noise_gate_db = -40.0
    assert abs(resolve_gate_threshold(s) - 0.01) < 1e-6


def test_gate_inserted_on_mic_chain_only():
    frag = build_audio_fragment([_mic("mic.node")], gate_threshold=0.01)
    assert "audiodynamic mode=expander" in frag
    assert "ratio=2" in frag


def test_gate_not_inserted_on_sink_chain():
    frag = build_audio_fragment([_sink("sink.node")], gate_threshold=0.01)
    assert "audiodynamic" not in frag


def test_gate_absent_when_threshold_zero():
    frag = build_audio_fragment([_mic("mic.node")], gate_threshold=0.0)
    assert "audiodynamic" not in frag


def test_gate_only_on_mic_in_mixed_set():
    frag = build_audio_fragment(
        [_sink("sink.node"), _mic("mic.node")], gate_threshold=0.05
    )
    assert frag.count("audiodynamic") == 1
