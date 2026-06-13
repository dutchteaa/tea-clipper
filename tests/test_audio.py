from tea_clipper.audio import build_audio_fragment


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


def test_multiple_devices_each_link_into_the_mixer():
    frag = build_audio_fragment(["mic.node", "sink.monitor"])
    assert frag.count("pipewiresrc") == 2
    assert frag.count("! amix.") == 2
    assert "target-object=mic.node" in frag
    assert "target-object=sink.monitor" in frag
    assert "audiomixer name=amix" in frag
    assert frag.rstrip().endswith("queue name=aenc_in")
