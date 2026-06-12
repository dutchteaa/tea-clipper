from pathlib import Path

import pytest

from conftest import HAVE_FFMPEG, ffprobe_codecs, ffprobe_duration, make_segment
from tea_clipper.replay_buffer import ReplayBuffer


pytestmark = pytest.mark.skipif(not HAVE_FFMPEG, reason="needs ffmpeg")


def test_segments_for_returns_tail_covering_duration(tmp_path: Path):
    rb = ReplayBuffer(segment_seconds=2)
    segs = [tmp_path / f"segment_{i:05d}.mkv" for i in range(5)]
    for s in segs:
        s.touch()
    for s in segs:
        rb.on_segment_finalized(s)
    # want last 5s -> ceil(5/2)=3 segments, the three most recent
    chosen = rb.segments_for(5)
    assert chosen == segs[-3:]


def test_segments_for_caps_at_available(tmp_path: Path):
    rb = ReplayBuffer(segment_seconds=2)
    segs = [tmp_path / f"segment_{i:05d}.mkv" for i in range(2)]
    for s in segs:
        s.touch()
        rb.on_segment_finalized(s)
    assert rb.segments_for(60) == segs


def test_stitch_produces_playable_clip(tmp_path: Path):
    rb = ReplayBuffer(segment_seconds=2)
    segs = [make_segment(tmp_path / f"segment_{i:05d}.mkv", seconds=2.0) for i in range(3)]
    out = tmp_path / "clip.mkv"
    rb.stitch(segs, out)
    assert out.exists()
    assert {"video", "audio"} <= ffprobe_codecs(out)
    assert ffprobe_duration(out) == pytest.approx(6.0, abs=0.5)
