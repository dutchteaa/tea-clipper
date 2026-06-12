import pytest
from unittest.mock import patch

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
    with pytest.raises(ValueError, match="unknown codec"):
        reg.resolve(codec="rle", hardware=False, bitrate_kbps=8000, fps=60, segment_seconds=2)


def test_available_codecs_is_subset_of_known():
    reg = EncoderRegistry()
    assert set(reg.available_codecs()) <= {"h264", "hevc", "av1"}


def test_resolve_warns_and_falls_back_when_hardware_missing():
    reg = EncoderRegistry()
    # Pretend only the software encoder exists.
    with patch("tea_clipper.encoders._element_exists", side_effect=lambda name: name == "x264enc"):
        with pytest.warns(UserWarning, match="falling back to software"):
            spec = reg.resolve(codec="h264", hardware=True, bitrate_kbps=8000, fps=60, segment_seconds=2)
    assert spec.element == "x264enc"
