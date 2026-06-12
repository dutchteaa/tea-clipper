import time
from pathlib import Path

import pytest

from conftest import requires_engine, ffprobe_codecs
from tea_clipper.encoders import EncoderRegistry
from tea_clipper.pipeline import CapturePipeline, test_source_bin


@requires_engine
@pytest.mark.engine
def test_pipeline_writes_and_prunes_segments(tmp_path: Path):
    buffer_dir = tmp_path / "buffer"
    spec = EncoderRegistry().resolve("h264", hardware=False, bitrate_kbps=4000, fps=30, segment_seconds=1)
    finalized: list[Path] = []

    pipe = CapturePipeline(
        source_desc=test_source_bin(),
        encoder=spec,
        buffer_dir=buffer_dir,
        segment_seconds=1,
        max_segments=4,   # keep the ring small so we can observe pruning
    )
    pipe.add_segment_listener(finalized.append)
    pipe.start()
    time.sleep(7)        # ~7 one-second segments produced
    pipe.stop()

    # We were notified about multiple finalized segments...
    assert len(finalized) >= 4
    # ...but the ring kept only ~max_segments on disk.
    on_disk = list(buffer_dir.glob("segment_*.mkv"))
    assert len(on_disk) <= 5
    # finalized segments are real A/V files
    assert {"video", "audio"} <= ffprobe_codecs(finalized[0])


from tea_clipper.replay_buffer import ReplayBuffer


@requires_engine
@pytest.mark.engine
def test_save_last_produces_clip_of_expected_length(tmp_path: Path):
    import pytest as _pytest  # local alias for approx
    from conftest import ffprobe_duration

    buffer_dir = tmp_path / "buffer"
    spec = EncoderRegistry().resolve("h264", hardware=False, bitrate_kbps=4000, fps=30, segment_seconds=1)
    pipe = CapturePipeline(
        source_desc=test_source_bin(), encoder=spec, buffer_dir=buffer_dir,
        segment_seconds=1, max_segments=20,
    )
    rb = ReplayBuffer(segment_seconds=1)
    pipe.add_segment_listener(rb.on_segment_finalized)

    pipe.start()
    time.sleep(6)
    out = tmp_path / "clip.mkv"
    clip = rb.save_last(4, out, pipeline=pipe)   # force_split + stitch last ~4s
    pipe.stop()

    assert clip.exists()
    assert {"video", "audio"} <= ffprobe_codecs(clip)
    assert ffprobe_duration(clip) == _pytest.approx(4.0, abs=1.2)


from tea_clipper.manual_recorder import ManualRecorder


@requires_engine
@pytest.mark.engine
def test_manual_record_captures_full_take(tmp_path: Path):
    import pytest as _pytest
    from conftest import ffprobe_duration

    buffer_dir = tmp_path / "buffer"
    spec = EncoderRegistry().resolve("h264", hardware=False, bitrate_kbps=4000, fps=30, segment_seconds=1)
    pipe = CapturePipeline(
        source_desc=test_source_bin(), encoder=spec, buffer_dir=buffer_dir,
        segment_seconds=1, max_segments=20,
    )
    rec = ManualRecorder(pipeline=pipe)
    pipe.add_segment_listener(rec.on_segment_finalized)

    pipe.start()
    time.sleep(1)
    rec.start()
    time.sleep(5)            # record ~5s
    out = tmp_path / "manual.mkv"
    clip = rec.stop(out)
    pipe.stop()

    assert clip.exists()
    assert {"video", "audio"} <= ffprobe_codecs(clip)
    assert ffprobe_duration(clip) == _pytest.approx(5.0, abs=1.5)
