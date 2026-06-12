from tea_clipper.encoders import EncoderRegistry, EncoderSpec


def test_resolve_software_h264_always_available():
    reg = EncoderRegistry()
    # libx264-backed x264enc ships with gst-plugins-ugly/good and is our fallback
    spec = reg.resolve(codec="h264", hardware=False, bitrate_kbps=8000, fps=60, segment_seconds=2)
    assert isinstance(spec, EncoderSpec)
    assert spec.element == "x264enc"
    assert spec.properties["bitrate"] == 8000      # x264enc bitrate is kbps
    assert spec.properties["key-int-max"] == 120   # fps * segment_seconds
    assert spec.parser == "h264parse"


def test_resolve_unknown_codec_raises():
    reg = EncoderRegistry()
    try:
        reg.resolve(codec="rle", hardware=False, bitrate_kbps=8000, fps=60, segment_seconds=2)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_available_codecs_is_subset_of_known():
    reg = EncoderRegistry()
    assert set(reg.available_codecs()) <= {"h264", "hevc", "av1"}
