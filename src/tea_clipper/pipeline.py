"""The GStreamer capture pipeline: encode once, segment into a rolling buffer,
and emit a 'segment finalized' event consumers can subscribe to."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from tea_clipper.gst_init import ensure_gst  # registers gi version first

from gi.repository import GLib, Gst

from tea_clipper.encoders import EncoderSpec


def test_source_bin() -> tuple[str, str]:
    """A (video, audio) pair of launch fragments producing live test A/V, for headless tests."""
    return (
        "videotestsrc is-live=true pattern=ball ! "
        "video/x-raw,width=640,height=360,framerate=30/1 ! videoconvert ! "
        "queue name=venc_in"
    ), (
        "audiotestsrc is-live=true ! audioconvert ! audioresample ! "
        "queue name=aenc_in"
    )


class CapturePipeline:
    """Owns the GStreamer pipeline and the segment-finalized pub/sub.

    Encodes the source once, writes short keyframe-aligned segments via
    ``splitmuxsink`` (which auto-prunes old segments via ``max-files``), and
    notifies listeners with the ``Path`` of each segment as it is finalized.
    """

    def __init__(
        self,
        source_desc: tuple[str, str | None],
        encoder: EncoderSpec,
        buffer_dir: Path,
        segment_seconds: int,
        max_segments: int,
    ) -> None:
        ensure_gst()
        self.buffer_dir = Path(buffer_dir)
        self.buffer_dir.mkdir(parents=True, exist_ok=True)
        self.segment_seconds = segment_seconds
        self._listeners: list[Callable[[Path], None]] = []
        self._pending: Path | None = None          # file currently being written
        self._split_event = threading.Event()
        self._loop: GLib.MainLoop | None = None
        self._loop_thread: threading.Thread | None = None

        video_src, audio_src = source_desc
        enc = encoder.element
        props = " ".join(f"{k}={v}" for k, v in encoder.properties.items())
        seg_ns = segment_seconds * Gst.SECOND
        # NOTE: splitmuxsink takes the muxer by factory name via `muxer-factory`
        # (the `muxer` property expects an element instance, not a name).
        launch = (
            f"{video_src} ! {enc} {props} ! {encoder.parser} ! "
            f"splitmuxsink name=replaymux muxer-factory=matroskamux "
            f"max-size-time={seg_ns} max-files={max_segments} send-keyframe-requests=true"
        )
        # Audio is optional: a None audio fragment yields a video-only pipeline
        # (real portal capture is video-only; the test source still supplies audio).
        if audio_src is not None:
            launch += f" {audio_src} ! opusenc ! replaymux.audio_0"
        self.pipeline = Gst.parse_launch(launch)
        self.splitmux = self.pipeline.get_by_name("replaymux")
        # format-location-full lets us name files AND learn when the previous one closed.
        self.splitmux.connect("format-location-full", self._on_format_location)

    # --- pub/sub -------------------------------------------------------------
    def add_segment_listener(self, cb: Callable[[Path], None]) -> None:
        self._listeners.append(cb)

    def _emit_finalized(self, path: Path) -> None:
        for cb in list(self._listeners):
            cb(path)

    def _on_format_location(self, _splitmux, fragment_id, _first_sample) -> str:
        # The previously-returned path is now finalized (closed) as a new one opens.
        if self._pending is not None:
            self._emit_finalized(self._pending)
            self._split_event.set()
        next_path = self.buffer_dir / f"segment_{fragment_id:05d}.mkv"
        self._pending = next_path
        return str(next_path)

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        self._loop = GLib.MainLoop()
        self._loop_thread = threading.Thread(target=self._loop.run, daemon=True)
        self._loop_thread.start()
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            self.stop()
            raise RuntimeError("failed to start capture pipeline")

    def stop(self) -> None:
        # Send EOS so the final segment is flushed/finalized cleanly.
        self.pipeline.send_event(Gst.Event.new_eos())
        bus = self.pipeline.get_bus()
        msg = bus.timed_pop_filtered(
            3 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR
        )
        self.pipeline.set_state(Gst.State.NULL)
        if self._loop is not None:
            self._loop.quit()
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=2)
        if msg is not None and msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            raise RuntimeError(f"pipeline error: {err.message} ({debug})")

    def force_split(self, timeout: float = 3.0) -> None:
        """Finalize the in-progress segment now and block until it's emitted."""
        self._split_event.clear()
        self.splitmux.emit("split-now")
        self._split_event.wait(timeout=timeout)
