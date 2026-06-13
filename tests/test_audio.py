from tea_clipper.audio import (
    AudioDevice,
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


def test_unavailable_entries_are_skipped():
    out = resolve_audio_devices(_S(["mic.a", "ghost.device"]), _available())
    assert out == ["mic.a"]


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
