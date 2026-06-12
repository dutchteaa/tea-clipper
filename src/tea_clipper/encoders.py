"""Probe available GStreamer encoders and map a codec choice to pipeline elements."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

from tea_clipper.gst_init import ensure_gst  # registers gi version first

from gi.repository import Gst

# codec -> (hardware element, software element, parser)
_CODEC_TABLE = {
    "h264": ("vah264enc", "x264enc", "h264parse"),
    "hevc": ("vah265enc", "x265enc", "h265parse"),
    "av1":  ("vaav1enc",  "svtav1enc", "av1parse"),
}


@dataclass
class EncoderSpec:
    element: str
    properties: dict[str, int] = field(default_factory=dict)
    parser: str = ""


def _element_exists(name: str) -> bool:
    return Gst.ElementFactory.find(name) is not None


class EncoderRegistry:
    def __init__(self) -> None:
        ensure_gst()

    def available_codecs(self) -> list[str]:
        out = []
        for codec, (hw, sw, _parser) in _CODEC_TABLE.items():
            if _element_exists(hw) or _element_exists(sw):
                out.append(codec)
        return out

    def resolve(
        self, codec: str, hardware: bool, bitrate_kbps: int, fps: int, segment_seconds: int
    ) -> EncoderSpec:
        if codec not in _CODEC_TABLE:
            raise ValueError(f"unknown codec: {codec}")
        hw, sw, parser = _CODEC_TABLE[codec]
        if hardware and _element_exists(hw):
            element = hw
        else:
            element = sw
            if hardware:
                warnings.warn(
                    f"hardware encoder {hw!r} unavailable; falling back to software {sw!r}",
                    stacklevel=2,
                )
        if not _element_exists(element):
            raise ValueError(f"no encoder available for codec {codec} (tried {hw}, {sw})")
        key_int_max = fps * segment_seconds
        # Both x264enc/x265enc and the VAAPI encoders accept `bitrate` in kbps and
        # `key-int-max` for keyframe interval, so segments stay independently concatenable.
        props = {"bitrate": bitrate_kbps, "key-int-max": key_int_max}
        return EncoderSpec(element=element, properties=props, parser=parser)
