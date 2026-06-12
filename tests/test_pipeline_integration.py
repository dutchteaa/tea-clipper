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
