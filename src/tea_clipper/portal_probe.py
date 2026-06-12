"""Manual real-hardware probe: capture the screen via the portal and save a clip.

Run on the KDE/Wayland target:  .venv/bin/python -m tea_clipper.portal_probe
First run shows the monitor picker; later runs reuse the saved restore token.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from tea_clipper.encoders import EncoderRegistry
from tea_clipper.pipeline import CapturePipeline
from tea_clipper.portal import PortalError, PortalManager
from tea_clipper.replay_buffer import ReplayBuffer
from tea_clipper.settings import Settings


def main(argv: list[str] | None = None) -> int:
    config = Path.home() / ".config" / "tea-clipper" / "config.toml"
    settings = Settings.load(config)

    portal = PortalManager(settings)
    print("Negotiating screen-cast (a monitor picker may appear)...")
    try:
        video = portal.open()
    except PortalError as exc:
        print(f"Portal error: {exc}", file=sys.stderr)
        return 1
    settings.save(config)  # persist the (possibly new) restore token

    spec = EncoderRegistry().resolve(
        settings.codec, hardware=settings.hardware, bitrate_kbps=settings.bitrate_kbps,
        fps=settings.fps, segment_seconds=settings.segment_seconds,
    )
    buffer_dir = Path(tempfile.mkdtemp(prefix="tea-clipper-probe-"))
    pipe = CapturePipeline(
        source_desc=(video, None), encoder=spec, buffer_dir=buffer_dir,
        segment_seconds=settings.segment_seconds, max_segments=64,
    )
    rb = ReplayBuffer(segment_seconds=settings.segment_seconds)
    pipe.add_segment_listener(rb.on_segment_finalized)

    out = Path.cwd() / "portal_probe_clip.mkv"
    try:
        print(f"Recording 6s into {buffer_dir} ...")
        pipe.start()
        time.sleep(6)
        clip = rb.save_last(5, out, pipeline=pipe)
    finally:
        pipe.stop()
        portal.close()

    print(f"Saved clip: {clip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
