# Engine Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the headless capture engine that continuously records into a rolling, self-pruning buffer and saves the last *N* seconds (or a manual recording) as a clip — provable end-to-end with GStreamer test sources, no portal or UI.

**Architecture:** One GStreamer pipeline captures a source + audio, encodes once, and writes short keyframe-aligned segments via `splitmuxsink` (which auto-deletes old segments via `max-files`). A pub/sub "segment finalized" event lets two consumers reuse the same segments: `ReplayBuffer` (stitch the last *N* seconds on demand) and `ManualRecorder` (collect segments while active, stitch on stop). Stitching is a lossless `ffmpeg -c copy` concat. Tests run the real pipeline with `videotestsrc`/`audiotestsrc` and a software encoder so they pass headlessly.

**Tech Stack:** Python 3.12+ · GStreamer via PyGObject (`gi`) · ffmpeg/ffprobe (subprocess) · pytest · TOML (`tomllib` read, `tomli-w` write).

---

## File Structure

```
pyproject.toml                          # package metadata, deps, pytest config
src/tea_clipper/__init__.py
src/tea_clipper/gst_init.py             # one-time Gst.init + version guard
src/tea_clipper/settings.py             # Settings dataclass + TOML load/save
src/tea_clipper/encoders.py             # EncoderRegistry: probe installed encoders, map codec->element+props
src/tea_clipper/pipeline.py             # CapturePipeline: build/start/stop, segment-finalized pub/sub, force_split
src/tea_clipper/replay_buffer.py        # ReplayBuffer: track recent segments, save_last(), stitch() via ffmpeg
src/tea_clipper/manual_recorder.py      # ManualRecorder: collect segments while active, stitch on stop
tests/conftest.py                       # shared fixtures: skip markers, make_segment(), ffprobe helpers
tests/test_settings.py
tests/test_encoders.py
tests/test_replay_buffer.py             # pure stitch logic with fake segments
tests/test_pipeline_integration.py      # real pipeline + test sources: buffer, save_last, manual
```

**Boundaries:**
- `pipeline.py` owns all GStreamer knowledge and emits a clean `Path` event when a segment finalizes. It knows nothing about clips.
- `replay_buffer.py` and `manual_recorder.py` are pure consumers of finalized-segment paths + ffmpeg; they hold no GStreamer references except calling `pipeline.force_split()`.
- `encoders.py` and `settings.py` are leaf modules with no project dependencies.

---

## Task 1: Project skeleton + GStreamer init

**Files:**
- Create: `pyproject.toml`
- Create: `src/tea_clipper/__init__.py`
- Create: `src/tea_clipper/gst_init.py`
- Create: `tests/conftest.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "tea-clipper"
version = "0.0.1"
description = "Medal-style instant-replay game clipper for Linux/Wayland"
requires-python = ">=3.12"
dependencies = [
    "PyGObject>=3.46",
    "tomli-w>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"
markers = [
    "engine: integration tests that run a real GStreamer pipeline (need gstreamer + ffmpeg)",
]
```

- [ ] **Step 2: Create the package and `gst_init.py`**

`src/tea_clipper/__init__.py`:

```python
"""tea-clipper: instant-replay game clipper for Linux/Wayland."""

__version__ = "0.0.1"
```

`src/tea_clipper/gst_init.py`:

```python
"""One-time GStreamer initialization with a version guard."""

from __future__ import annotations

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

_initialized = False

MIN_VERSION = (1, 22, 0)


def ensure_gst() -> None:
    """Initialize GStreamer once. Idempotent. Raises if the version is too old."""
    global _initialized
    if _initialized:
        return
    Gst.init(None)
    major, minor, micro, _ = Gst.version()
    if (major, minor, micro) < MIN_VERSION:
        raise RuntimeError(
            f"GStreamer {MIN_VERSION} required, found {major}.{minor}.{micro}"
        )
    _initialized = True
```

- [ ] **Step 3: Create `tests/conftest.py` with shared helpers**

```python
"""Shared test fixtures and helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

try:
    from tea_clipper.gst_init import ensure_gst

    ensure_gst()
    HAVE_GST = True
except Exception:
    HAVE_GST = False

requires_engine = pytest.mark.skipif(
    not (HAVE_FFMPEG and HAVE_GST),
    reason="needs gstreamer + ffmpeg",
)


def ffprobe_duration(path: Path) -> float:
    """Return container duration in seconds via ffprobe."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def ffprobe_codecs(path: Path) -> set[str]:
    """Return the set of codec_type values (e.g. {'video', 'audio'}) in the file."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return {s["codec_type"] for s in json.loads(out.stdout)["streams"]}


def make_segment(path: Path, seconds: float = 2.0) -> Path:
    """Write a tiny real MKV (h264 + opus) test segment with ffmpeg."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=30:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-g", "30", "-pix_fmt", "yuv420p",
            "-c:a", "libopus",
            str(path),
        ],
        check=True,
    )
    return path
```

- [ ] **Step 4: Write the smoke test** `tests/test_smoke.py`

```python
from tea_clipper import __version__
from tea_clipper.gst_init import ensure_gst


def test_version_present():
    assert isinstance(__version__, str)


def test_ensure_gst_idempotent():
    ensure_gst()
    ensure_gst()  # second call must not raise
```

- [ ] **Step 5: Install in editable mode and run the smoke test**

Run:
```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/test_smoke.py
```
Expected: 2 passed. (If PyGObject wheels are unavailable, use the system Python that already has `gi`; document the chosen interpreter in the commit message.)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/tea_clipper/__init__.py src/tea_clipper/gst_init.py tests/conftest.py tests/test_smoke.py
git commit -m "feat: project skeleton with GStreamer init and test harness"
```

---

## Task 2: Settings (config dataclass + TOML round-trip)

**Files:**
- Create: `src/tea_clipper/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from tea_clipper.settings import Settings


def test_defaults_are_sensible():
    s = Settings()
    assert s.clip_length_seconds == 30
    assert s.codec == "h264"
    assert s.hardware is True
    assert s.bitrate_kbps == 30000
    assert s.fps == 60
    assert s.segment_seconds == 2


def test_toml_round_trip(tmp_path: Path):
    s = Settings(clip_length_seconds=45, codec="hevc", hardware=False, bitrate_kbps=12000)
    cfg = tmp_path / "config.toml"
    s.save(cfg)
    loaded = Settings.load(cfg)
    assert loaded == s


def test_load_missing_file_returns_defaults(tmp_path: Path):
    loaded = Settings.load(tmp_path / "nope.toml")
    assert loaded == Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tea_clipper.settings'`

- [ ] **Step 3: Write minimal implementation** `src/tea_clipper/settings.py`

```python
"""User-configurable settings with TOML persistence."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import tomli_w


@dataclass
class Settings:
    clip_length_seconds: int = 30
    codec: str = "h264"            # "h264" | "hevc" | "av1"
    hardware: bool = True          # prefer VAAPI; fall back to software
    bitrate_kbps: int = 30000
    fps: int = 60
    segment_seconds: int = 2       # rolling-buffer segment granularity
    desktop_audio: bool = True
    microphone: bool = True
    output_dir: str = field(default_factory=lambda: str(Path.home() / "Videos" / "tea-clipper"))
    buffer_dir: str = field(default_factory=lambda: str(Path.home() / ".cache" / "tea-clipper" / "buffer"))
    source_restore_token: str = ""

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            tomli_w.dump(asdict(self), fh)

    @classmethod
    def load(cls, path: Path) -> "Settings":
        path = Path(path)
        if not path.exists():
            return cls()
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/settings.py tests/test_settings.py
git commit -m "feat: Settings dataclass with TOML persistence"
```

---

## Task 3: EncoderRegistry (probe installed encoders, map codec → element)

**Files:**
- Create: `src/tea_clipper/encoders.py`
- Test: `tests/test_encoders.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_encoders.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tea_clipper.encoders'`

- [ ] **Step 3: Write minimal implementation** `src/tea_clipper/encoders.py`

```python
"""Probe available GStreamer encoders and map a codec choice to pipeline elements."""

from __future__ import annotations

from dataclasses import dataclass, field

from gi.repository import Gst

from tea_clipper.gst_init import ensure_gst

# codec -> (hardware element, software element, parser)
_CODEC_TABLE = {
    "h264": ("vah264enc", "x264enc", "h264parse"),
    "hevc": ("vah265enc", "x265enc", "h265parse"),
    "av1":  ("vaav1enc",  "svtav1enc", "av1parse"),
}


@dataclass
class EncoderSpec:
    element: str
    properties: dict = field(default_factory=dict)
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
        element = hw if (hardware and _element_exists(hw)) else sw
        if not _element_exists(element):
            raise ValueError(f"no encoder available for codec {codec} (tried {hw}, {sw})")
        key_int_max = fps * segment_seconds
        # Both x264enc/x265enc and the VAAPI encoders accept `bitrate` in kbps and
        # `key-int-max` for keyframe interval, so segments stay independently concatenable.
        props = {"bitrate": bitrate_kbps, "key-int-max": key_int_max}
        return EncoderSpec(element=element, properties=props, parser=parser)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_encoders.py -v`
Expected: 3 passed. (If `x264enc` is missing, install `gst-plugins-ugly`; note it in the commit.)

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/encoders.py tests/test_encoders.py
git commit -m "feat: EncoderRegistry probes and maps codecs to GStreamer elements"
```

---

## Task 4: ReplayBuffer stitching (pure ffmpeg concat)

**Files:**
- Create: `src/tea_clipper/replay_buffer.py`
- Test: `tests/test_replay_buffer.py`

This task builds and tests **only** the file-selection + stitch logic with fake segments. Pipeline wiring comes in Task 6.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_replay_buffer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tea_clipper.replay_buffer'`

- [ ] **Step 3: Write minimal implementation** `src/tea_clipper/replay_buffer.py`

```python
"""Track recently finalized segments and stitch the most recent ones into a clip."""

from __future__ import annotations

import math
import subprocess
from collections import deque
from pathlib import Path


class ReplayBuffer:
    """Consumes finalized-segment paths and stitches the last N seconds on demand."""

    def __init__(self, segment_seconds: int, max_tracked: int = 256) -> None:
        self.segment_seconds = segment_seconds
        self._segments: deque[Path] = deque(maxlen=max_tracked)

    def on_segment_finalized(self, path: Path) -> None:
        """Listener for CapturePipeline's segment-finalized event."""
        self._segments.append(Path(path))

    def segments_for(self, seconds: float) -> list[Path]:
        """Return the most recent segments (that still exist) covering `seconds`."""
        existing = [p for p in self._segments if p.exists()]
        count = max(1, math.ceil(seconds / self.segment_seconds))
        return existing[-count:]

    def stitch(self, segments: list[Path], output_path: Path) -> Path:
        """Losslessly concat `segments` into `output_path` via ffmpeg -c copy."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        list_file = output_path.with_suffix(".concat.txt")
        list_file.write_text(
            "".join(f"file '{p.resolve()}'\n" for p in segments)
        )
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", str(output_path),
                ],
                check=True,
            )
        finally:
            list_file.unlink(missing_ok=True)
        return output_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_replay_buffer.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/replay_buffer.py tests/test_replay_buffer.py
git commit -m "feat: ReplayBuffer segment selection and lossless stitch"
```

---

## Task 5: CapturePipeline (test source → encode → rolling segments + finalize events)

**Files:**
- Create: `src/tea_clipper/pipeline.py`
- Test: `tests/test_pipeline_integration.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline_integration.py -v`
Expected: FAIL with `ImportError: cannot import name 'CapturePipeline'`

- [ ] **Step 3: Write minimal implementation** `src/tea_clipper/pipeline.py`

```python
"""The GStreamer capture pipeline: encode once, segment into a rolling buffer,
and emit a 'segment finalized' event consumers can subscribe to."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from gi.repository import GLib, Gst

from tea_clipper.encoders import EncoderSpec
from tea_clipper.gst_init import ensure_gst


def test_source_bin() -> str:
    """A launch fragment producing live test video+audio, for headless tests."""
    return (
        "videotestsrc is-live=true pattern=ball ! "
        "video/x-raw,width=640,height=360,framerate=30/1 ! videoconvert ! "
        "queue name=venc_in"
    ), (
        "audiotestsrc is-live=true ! audioconvert ! audioresample ! "
        "queue name=aenc_in"
    )


class CapturePipeline:
    """Owns the GStreamer pipeline and the segment-finalized pub/sub."""

    def __init__(
        self,
        source_desc: tuple[str, str],
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
        launch = (
            f"{video_src} ! {enc} {props} ! {encoder.parser} ! "
            f"splitmuxsink name=replaymux muxer=matroskamux "
            f"max-size-time={seg_ns} max-files={max_segments} send-keyframe-requests=true "
            f"{audio_src} ! opusenc ! replaymux.audio_0"
        )
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

    def _on_format_location(self, _splitmux, _fragment_id, _first_sample) -> str:
        # The previously-returned path is now finalized (closed) as a new one opens.
        if self._pending is not None:
            self._emit_finalized(self._pending)
            self._split_event.set()
        next_path = self.buffer_dir / f"segment_{_fragment_id:05d}.mkv"
        self._pending = next_path
        return str(next_path)

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        self._loop = GLib.MainLoop()
        self._loop_thread = threading.Thread(target=self._loop.run, daemon=True)
        self._loop_thread.start()
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self) -> None:
        # Send EOS so the final segment is flushed/finalized cleanly.
        self.pipeline.send_event(Gst.Event.new_eos())
        bus = self.pipeline.get_bus()
        bus.timed_pop_filtered(3 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
        self.pipeline.set_state(Gst.State.NULL)
        if self._loop is not None:
            self._loop.quit()
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=2)

    def force_split(self, timeout: float = 3.0) -> None:
        """Finalize the in-progress segment now and block until it's emitted."""
        self._split_event.clear()
        self.splitmux.emit("split-now")
        self._split_event.wait(timeout=timeout)
```

> Note for the implementer: `test_source_bin()` returns a `(video, audio)` tuple of launch fragments; `CapturePipeline` joins them around the shared `splitmuxsink`. The named `queue` elements (`venc_in`/`aenc_in`) are harmless leaf names that keep each fragment a valid standalone branch.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_pipeline_integration.py -v -m engine`
Expected: 1 passed. (This runs a real ~7s pipeline. If it errors on `opusenc`/`matroskamux`, install `gst-plugins-base`/`gst-plugins-good`; note in commit.)

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/pipeline.py tests/test_pipeline_integration.py
git commit -m "feat: CapturePipeline with rolling segments and finalize events"
```

---

## Task 6: Wire ReplayBuffer.save_last to the pipeline (record → save → verify clip)

**Files:**
- Modify: `src/tea_clipper/replay_buffer.py` (add `save_last`)
- Modify: `tests/test_pipeline_integration.py` (add end-to-end test)

- [ ] **Step 1: Write the failing test** (append to `tests/test_pipeline_integration.py`)

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline_integration.py::test_save_last_produces_clip_of_expected_length -v -m engine`
Expected: FAIL with `AttributeError: 'ReplayBuffer' object has no attribute 'save_last'`

- [ ] **Step 3: Add `save_last` to `src/tea_clipper/replay_buffer.py`**

Add this method to the `ReplayBuffer` class (after `stitch`):

```python
    def save_last(self, seconds: float, output_path: Path, pipeline) -> Path:
        """Finalize the in-progress segment, then stitch the last `seconds` into a clip."""
        pipeline.force_split()           # ensure up-to-now footage is on disk
        segments = self.segments_for(seconds)
        if not segments:
            raise RuntimeError("no buffered segments available to save")
        return self.stitch(segments, output_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_pipeline_integration.py::test_save_last_produces_clip_of_expected_length -v -m engine`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/replay_buffer.py tests/test_pipeline_integration.py
git commit -m "feat: ReplayBuffer.save_last stitches the rolling buffer into a clip"
```

---

## Task 7: ManualRecorder (collect segments while active, stitch on stop)

**Files:**
- Create: `src/tea_clipper/manual_recorder.py`
- Modify: `tests/test_pipeline_integration.py` (add manual-record test)

Manual recording reuses the segment stream: while active it collects every finalized segment, and on stop it forces a split and stitches them — no dynamic GStreamer pad surgery.

- [ ] **Step 1: Write the failing test** (append to `tests/test_pipeline_integration.py`)

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline_integration.py::test_manual_record_captures_full_take -v -m engine`
Expected: FAIL with `ModuleNotFoundError: No module named 'tea_clipper.manual_recorder'`

- [ ] **Step 3: Write minimal implementation** `src/tea_clipper/manual_recorder.py`

```python
"""Manual start/stop recording built on the shared segment stream."""

from __future__ import annotations

import subprocess
from pathlib import Path


class ManualRecorder:
    """While active, collects finalized segments; on stop, stitches them into one file."""

    def __init__(self, pipeline) -> None:
        self._pipeline = pipeline
        self._active = False
        self._segments: list[Path] = []

    @property
    def is_recording(self) -> bool:
        return self._active

    def on_segment_finalized(self, path: Path) -> None:
        if self._active:
            self._segments.append(Path(path))

    def start(self) -> None:
        if self._active:
            return
        # Begin a fresh segment boundary so the take starts cleanly on a keyframe.
        self._pipeline.force_split()
        self._segments = []
        self._active = True

    def stop(self, output_path: Path) -> Path:
        if not self._active:
            raise RuntimeError("manual recorder is not active")
        self._pipeline.force_split()     # flush the final in-progress segment
        self._active = False
        segments = [p for p in self._segments if p.exists()]
        if not segments:
            raise RuntimeError("no segments captured for manual recording")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        list_file = output_path.with_suffix(".concat.txt")
        list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in segments))
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", str(output_path),
                ],
                check=True,
            )
        finally:
            list_file.unlink(missing_ok=True)
        return output_path
```

> Note: the stitch logic here duplicates `ReplayBuffer.stitch`. That duplication is intentional for this first slice (the two consumers are independent). If a third consumer appears, extract a shared `stitch(segments, out)` helper into a small `clips.py` module — do not pre-extract now (YAGNI).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_pipeline_integration.py::test_manual_record_captures_full_take -v -m engine`
Expected: 1 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest`
Expected: all tests pass (unit tests always; `-m engine` tests pass where gstreamer+ffmpeg exist).

- [ ] **Step 6: Commit**

```bash
git add src/tea_clipper/manual_recorder.py tests/test_pipeline_integration.py
git commit -m "feat: ManualRecorder captures full takes from the segment stream"
```

---

## Done criteria

- `pytest` is green: settings + encoders + replay-buffer unit tests, plus the `engine`-marked
  integration tests that run a real GStreamer pipeline with test sources.
- The engine proves, headlessly, all three core behaviors: a **self-pruning rolling buffer**,
  **save-last-N-seconds** clips, and **manual full-take** recording — each producing a playable
  A/V file via lossless `ffmpeg -c copy`.

## What this plan deliberately defers (next plans)

- `PortalManager` (real `pipewiresrc` capture via xdg-desktop-portal + restore token) — swaps in
  for `test_source_bin()`.
- `HotkeyService` (GlobalShortcuts portal) and the `Controller` wiring hotkeys → engine actions.
- Desktop+mic device selection (the test uses a single `audiotestsrc`; real audio mixes two
  `pipewiresrc` via `audiomixer`).
- PySide6 settings/status UI.
