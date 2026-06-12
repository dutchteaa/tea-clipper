# PortalManager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture the real screen via `org.freedesktop.portal.ScreenCast`, producing a `pipewiresrc` launch fragment that the existing `CapturePipeline` records into clips — replacing the headless `test_source_bin()` video source.

**Architecture:** A `PortalManager` orchestrates the ScreenCast handshake (CreateSession → SelectSources → Start → OpenPipeWireRemote) through a thin `ScreenCastPortal` Gio/GDBus wrapper, threading a persistent restore token through `Settings`. Pure helpers (option-building, result-parsing, fragment-building) carry the logic so they unit-test without a real bus; the raw D-Bus wrapper is verified by a runnable probe script on real hardware. The pipeline gains an optional (video-only) audio branch.

**Tech Stack:** Python 3.12+ · `gi.repository.Gio`/`GLib` (GDBus, no new dependency) · GStreamer `pipewiresrc` · pytest. Spec: `docs/superpowers/specs/2026-06-12-portalmanager-design.md`.

---

## File Structure

```
src/tea_clipper/pipeline.py        # MODIFY: optional (video-only) audio branch
src/tea_clipper/portal.py          # CREATE: exceptions, pure helpers, PortalManager, ScreenCastPortal
src/tea_clipper/portal_probe.py    # CREATE: __main__ real-hardware probe
tests/test_pipeline_integration.py # MODIFY: video-only build test
tests/test_portal.py               # CREATE: pure-helper + orchestration unit tests (no real bus)
```

**Boundaries:**
- `portal.py` owns all D-Bus knowledge. Pure helpers + `PortalManager` orchestration are unit-tested with a fake portal; `ScreenCastPortal` (raw Gio) is hardware-verified via the probe.
- `pipeline.py` only learns that the audio fragment may be `None`. It never learns about portals.
- The probe is the end-to-end proof; it is not part of the automated suite.

---

## Task 1: Optional audio branch in CapturePipeline

**Files:**
- Modify: `src/tea_clipper/pipeline.py`
- Test: `tests/test_pipeline_integration.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_pipeline_integration.py`)

```python
@requires_engine
@pytest.mark.engine
def test_video_only_pipeline_has_no_audio_track(tmp_path: Path):
    buffer_dir = tmp_path / "buffer"
    spec = EncoderRegistry().resolve("h264", hardware=False, bitrate_kbps=4000, fps=30, segment_seconds=1)
    video, _audio = test_source_bin()
    finalized: list[Path] = []
    pipe = CapturePipeline(
        source_desc=(video, None), encoder=spec, buffer_dir=buffer_dir,
        segment_seconds=1, max_segments=10,
    )
    pipe.add_segment_listener(finalized.append)
    pipe.start()
    time.sleep(4)
    pipe.stop()
    assert finalized
    codecs = ffprobe_codecs(finalized[0])
    assert "video" in codecs
    assert "audio" not in codecs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline_integration.py::test_video_only_pipeline_has_no_audio_track -v -m engine`
Expected: FAIL — with `source_desc=(video, None)` the current code does `f"{audio_src} ! opusenc ..."` producing a launch string containing `None`, so `Gst.parse_launch` raises (pipeline build error).

- [ ] **Step 3: Make the audio branch optional**

In `src/tea_clipper/pipeline.py`, replace the launch-string construction in `__init__`. Current code:

```python
        seg_ns = segment_seconds * Gst.SECOND
        # NOTE: splitmuxsink takes the muxer by factory name via `muxer-factory`
        # (the `muxer` property expects an element instance, not a name).
        launch = (
            f"{video_src} ! {enc} {props} ! {encoder.parser} ! "
            f"splitmuxsink name=replaymux muxer-factory=matroskamux "
            f"max-size-time={seg_ns} max-files={max_segments} send-keyframe-requests=true "
            f"{audio_src} ! opusenc ! replaymux.audio_0"
        )
        self.pipeline = Gst.parse_launch(launch)
```

Replace with:

```python
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
```

Also update the type hint on the `__init__` signature for clarity:

```python
        source_desc: tuple[str, str | None],
```

- [ ] **Step 4: Run the new test and the existing pipeline tests**

Run: `.venv/bin/pytest tests/test_pipeline_integration.py -v -m engine`
Expected: all pass (the new video-only test, plus the existing buffer/save_last/manual tests still exercising audio).

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/pipeline.py tests/test_pipeline_integration.py
git commit -m "feat: CapturePipeline supports a video-only (optional audio) source"
```

---

## Task 2: Portal exceptions + pure helpers

**Files:**
- Create: `src/tea_clipper/portal.py`
- Test: `tests/test_portal.py`

This task creates `portal.py` with only the bus-free pieces: constants, exceptions, and three pure helper functions. `PortalManager` and `ScreenCastPortal` come in Tasks 3–4.

- [ ] **Step 1: Write the failing test** `tests/test_portal.py`

```python
import pytest

from tea_clipper.portal import (
    CURSOR_EMBEDDED,
    MONITOR,
    PERSIST_MODE,
    PortalFailedError,
    build_select_sources_options,
    build_video_fragment,
    parse_start_results,
)


def test_build_select_sources_options_without_token():
    opts = build_select_sources_options("")
    assert opts["types"].unpack() == MONITOR
    assert opts["cursor_mode"].unpack() == CURSOR_EMBEDDED
    assert opts["persist_mode"].unpack() == PERSIST_MODE
    assert "restore_token" not in opts  # empty token is omitted


def test_build_select_sources_options_with_token():
    opts = build_select_sources_options("tok-123")
    assert opts["restore_token"].unpack() == "tok-123"


def test_parse_start_results_returns_node_and_token():
    results = {"streams": [(42, {})], "restore_token": "newtok"}
    node_id, token = parse_start_results(results)
    assert node_id == 42
    assert token == "newtok"


def test_parse_start_results_missing_token_is_empty():
    node_id, token = parse_start_results({"streams": [(7, {})]})
    assert node_id == 7
    assert token == ""


def test_parse_start_results_no_streams_raises():
    with pytest.raises(PortalFailedError):
        parse_start_results({"streams": []})


def test_build_video_fragment():
    frag = build_video_fragment(27, 42)
    assert frag == "pipewiresrc fd=27 path=42 ! videoconvert ! queue name=venc_in"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_portal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tea_clipper.portal'`

- [ ] **Step 3: Write the bus-free part of** `src/tea_clipper/portal.py`

```python
"""Real screen capture via org.freedesktop.portal.ScreenCast.

Layering:
  * pure helpers (this section) — option/result/fragment logic, no D-Bus, unit-tested.
  * PortalManager — orchestration over a ScreenCastPortal collaborator, unit-tested
    with a fake portal.
  * ScreenCastPortal — the raw Gio/GDBus wrapper, verified on real hardware by
    src/tea_clipper/portal_probe.py (not part of the automated suite).
"""

from __future__ import annotations

from gi.repository import GLib

# SelectSources option values (xdg-desktop-portal ScreenCast).
MONITOR = 1          # source type: whole monitor
CURSOR_EMBEDDED = 2  # draw the cursor into the captured frames
PERSIST_MODE = 2     # persist permissions until explicitly revoked


class PortalError(Exception):
    """Base class for screen-cast portal failures."""


class PortalUnavailableError(PortalError):
    """The desktop portal (org.freedesktop.portal.Desktop) is not on the bus."""


class PortalCancelledError(PortalError):
    """The user dismissed the screen-cast picker."""


class PortalFailedError(PortalError):
    """The portal reported a failure or returned no usable stream."""


def build_select_sources_options(
    restore_token: str = "",
    *,
    types: int = MONITOR,
    cursor_mode: int = CURSOR_EMBEDDED,
    persist_mode: int = PERSIST_MODE,
) -> dict[str, GLib.Variant]:
    """Build the a{sv} options for SelectSources. Omits an empty restore token."""
    opts: dict[str, GLib.Variant] = {
        "types": GLib.Variant("u", types),
        "cursor_mode": GLib.Variant("u", cursor_mode),
        "persist_mode": GLib.Variant("u", persist_mode),
    }
    if restore_token:
        opts["restore_token"] = GLib.Variant("s", restore_token)
    return opts


def parse_start_results(results: dict) -> tuple[int, str]:
    """Extract (node_id, restore_token) from a Start response's results dict."""
    streams = results.get("streams") or []
    if not streams:
        raise PortalFailedError("portal returned no screen-cast streams")
    node_id = streams[0][0]
    return node_id, results.get("restore_token", "")


def build_video_fragment(fd: int, node_id: int) -> str:
    """The pipewiresrc launch fragment CapturePipeline consumes as its video source."""
    return f"pipewiresrc fd={fd} path={node_id} ! videoconvert ! queue name=venc_in"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_portal.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/portal.py tests/test_portal.py
git commit -m "feat: portal constants, exceptions, and pure ScreenCast helpers"
```

---

## Task 3: PortalManager orchestration

**Files:**
- Modify: `src/tea_clipper/portal.py` (add `PortalManager`)
- Test: `tests/test_portal.py` (add orchestration tests with a fake portal)

`PortalManager` sequences the portal steps through an injectable `ScreenCastPortal`
collaborator. Tests inject a fake so orchestration is verified with no real bus.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_portal.py`)

```python
import os

from tea_clipper.portal import PortalManager, PortalCancelledError
from tea_clipper.settings import Settings


class FakePortal:
    """Records calls and returns canned values, standing in for ScreenCastPortal."""

    def __init__(self, start_results, fd=27):
        self._start_results = start_results
        self._fd = fd
        self.calls = []
        self.closed = []

    def create_session(self):
        self.calls.append(("create",))
        return "/org/session/1"

    def select_sources(self, session, *, types, cursor_mode, persist_mode, restore_token=""):
        self.calls.append(
            ("select", dict(types=types, cursor_mode=cursor_mode,
                            persist_mode=persist_mode, restore_token=restore_token))
        )

    def start(self, session, parent_window=""):
        self.calls.append(("start", session, parent_window))
        if isinstance(self._start_results, Exception):
            raise self._start_results
        return self._start_results

    def open_pipewire_remote(self, session):
        self.calls.append(("open", session))
        return self._fd

    def close_session(self, session):
        self.closed.append(session)


def _select_opts(fake):
    return next(c[1] for c in fake.calls if c[0] == "select")


def test_open_returns_fragment_and_saves_new_token():
    settings = Settings(source_restore_token="")
    fake = FakePortal({"streams": [(42, {})], "restore_token": "newtok"}, fd=27)
    mgr = PortalManager(settings, portal=fake)

    frag = mgr.open()

    assert frag == "pipewiresrc fd=27 path=42 ! videoconvert ! queue name=venc_in"
    assert settings.source_restore_token == "newtok"
    assert mgr.is_open
    opts = _select_opts(fake)
    assert opts["types"] == 1          # MONITOR
    assert opts["persist_mode"] == 2   # PERSIST_MODE
    assert opts["restore_token"] == "" # none saved yet


def test_open_reuses_existing_token_and_keeps_it_when_none_returned():
    settings = Settings(source_restore_token="saved-tok")
    fake = FakePortal({"streams": [(7, {})]}, fd=31)  # no restore_token in results
    mgr = PortalManager(settings, portal=fake)

    frag = mgr.open()

    assert "path=7" in frag
    assert _select_opts(fake)["restore_token"] == "saved-tok"
    assert settings.source_restore_token == "saved-tok"  # unchanged


def test_open_cancelled_propagates_and_closes_session():
    settings = Settings()
    fake = FakePortal(PortalCancelledError("user said no"))
    mgr = PortalManager(settings, portal=fake)

    with pytest.raises(PortalCancelledError):
        mgr.open()

    assert fake.closed == ["/org/session/1"]  # session cleaned up on failure
    assert not mgr.is_open


def test_close_closes_fd_and_session():
    settings = Settings()
    real_fd = os.open(os.devnull, os.O_RDONLY)  # a real fd so os.close succeeds
    fake = FakePortal({"streams": [(1, {})]}, fd=real_fd)
    mgr = PortalManager(settings, portal=fake)
    mgr.open()

    mgr.close()

    assert not mgr.is_open
    assert fake.closed == ["/org/session/1"]
    with pytest.raises(OSError):
        os.close(real_fd)  # already closed by PortalManager.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_portal.py -v`
Expected: FAIL with `ImportError: cannot import name 'PortalManager'`

- [ ] **Step 3: Add `PortalManager` to `src/tea_clipper/portal.py`**

Add an `import os` at the top of the file (below `from __future__ import annotations`):

```python
import os
```

Then append the class (after the pure helpers, before any `ScreenCastPortal` you add later):

```python
class PortalManager:
    """Negotiates a ScreenCast session and yields a pipewiresrc video fragment.

    Reuses ``settings.source_restore_token`` when present and writes a fresh token
    back onto the Settings instance (persisting to disk is the caller's job).
    Keeps the portal session + PipeWire fd alive until ``close()``.
    """

    def __init__(self, settings, portal=None) -> None:
        self._settings = settings
        self._portal = portal  # None -> create a real ScreenCastPortal lazily in open()
        self._session = None
        self._fd: int | None = None

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def open(self) -> str:
        if self._portal is None:
            self._portal = ScreenCastPortal()
        session = self._portal.create_session()
        try:
            self._portal.select_sources(
                session,
                types=MONITOR,
                cursor_mode=CURSOR_EMBEDDED,
                persist_mode=PERSIST_MODE,
                restore_token=self._settings.source_restore_token,
            )
            results = self._portal.start(session)
            node_id, restore_token = parse_start_results(results)
            if restore_token:
                self._settings.source_restore_token = restore_token
            fd = self._portal.open_pipewire_remote(session)
        except Exception:
            self._portal.close_session(session)
            raise
        self._session = session
        self._fd = fd
        return build_video_fragment(fd, node_id)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        if self._session is not None and self._portal is not None:
            self._portal.close_session(self._session)
            self._session = None
```

> Note: `ScreenCastPortal` is referenced lazily inside `open()`, so this task's tests
> (which always inject a fake `portal=`) never touch the real class — it's added in Task 4.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_portal.py -v`
Expected: 10 passed (6 from Task 2 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/portal.py tests/test_portal.py
git commit -m "feat: PortalManager orchestrates ScreenCast negotiation with token reuse"
```

---

## Task 4: ScreenCastPortal — the raw Gio/GDBus wrapper

**Files:**
- Modify: `src/tea_clipper/portal.py` (add `ScreenCastPortal`)

This is the only code that talks to the real bus. It cannot be unit-tested headlessly
(it needs a live portal + a human at the picker), so it has **no automated test** — it is
verified by the probe in Task 5. Write it carefully; the code below is complete.

- [ ] **Step 1: Add the Gio imports**

At the top of `src/tea_clipper/portal.py`, change the gi import line:

```python
from gi.repository import GLib
```

to:

```python
from uuid import uuid4

from gi.repository import Gio, GLib
```

(Keep `import os` and `from __future__ import annotations` as already present.)

- [ ] **Step 2: Append `ScreenCastPortal` to `src/tea_clipper/portal.py`**

```python
_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
_REQUEST_IFACE = "org.freedesktop.portal.Request"
_SESSION_IFACE = "org.freedesktop.portal.Session"


class ScreenCastPortal:
    """Thin synchronous wrapper over the ScreenCast portal D-Bus interface.

    Each request-style method subscribes to its Request's ``Response`` signal, invokes
    the method, and blocks on a private GLib main loop until the response arrives,
    translating the response code into a return value or a PortalError.
    """

    def __init__(self, connection=None) -> None:
        self._bus = connection or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._require_portal()
        # Request object paths are /…/request/<SENDER>/<TOKEN>, where SENDER is our
        # unique bus name without the leading ':' and with '.' replaced by '_'.
        self._sender = self._bus.get_unique_name()[1:].replace(".", "_")
        self._screencast = Gio.DBusProxy.new_sync(
            self._bus, Gio.DBusProxyFlags.NONE, None,
            _PORTAL_BUS, _PORTAL_PATH, _SCREENCAST_IFACE, None,
        )

    def _require_portal(self) -> None:
        try:
            self._bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", "GetNameOwner",
                GLib.Variant("(s)", (_PORTAL_BUS,)),
                None, Gio.DBusCallFlags.NONE, -1, None,
            )
        except GLib.Error as exc:
            raise PortalUnavailableError(
                "org.freedesktop.portal.Desktop is not available on the session bus"
            ) from exc

    @staticmethod
    def _token() -> str:
        return "tea" + uuid4().hex

    def _await_response(self, token: str, call_fn) -> dict:
        request_path = f"{_PORTAL_PATH}/request/{self._sender}/{token}"
        loop = GLib.MainLoop()
        box: dict = {}

        def on_response(_conn, _sender, _path, _iface, _signal, params):
            box["code"], box["results"] = params.unpack()
            loop.quit()

        sub = self._bus.signal_subscribe(
            _PORTAL_BUS, _REQUEST_IFACE, "Response", request_path, None,
            Gio.DBusSignalFlags.NONE, on_response,
        )
        try:
            call_fn()      # the portal method returns the Request path; we ignore it
            loop.run()
        finally:
            self._bus.signal_unsubscribe(sub)

        code = box.get("code", 2)
        if code == 1:
            raise PortalCancelledError("user dismissed the screen-cast picker")
        if code != 0:
            raise PortalFailedError(f"portal request failed (response code {code})")
        return box["results"]

    def create_session(self) -> str:
        token = self._token()
        opts = {
            "handle_token": GLib.Variant("s", token),
            "session_handle_token": GLib.Variant("s", self._token()),
        }
        results = self._await_response(token, lambda: self._screencast.call_sync(
            "CreateSession", GLib.Variant("(a{sv})", (opts,)),
            Gio.DBusCallFlags.NONE, -1, None,
        ))
        return results["session_handle"]

    def select_sources(self, session, *, types, cursor_mode, persist_mode, restore_token="") -> None:
        token = self._token()
        opts = build_select_sources_options(
            restore_token, types=types, cursor_mode=cursor_mode, persist_mode=persist_mode
        )
        opts["handle_token"] = GLib.Variant("s", token)
        self._await_response(token, lambda: self._screencast.call_sync(
            "SelectSources", GLib.Variant("(oa{sv})", (session, opts)),
            Gio.DBusCallFlags.NONE, -1, None,
        ))

    def start(self, session, parent_window="") -> dict:
        token = self._token()
        opts = {"handle_token": GLib.Variant("s", token)}
        return self._await_response(token, lambda: self._screencast.call_sync(
            "Start", GLib.Variant("(osa{sv})", (session, parent_window, opts)),
            Gio.DBusCallFlags.NONE, -1, None,
        ))

    def open_pipewire_remote(self, session) -> int:
        ret, fd_list = self._screencast.call_with_unix_fd_list_sync(
            "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (session, {})),
            Gio.DBusCallFlags.NONE, -1, None, None,
        )
        (fd_index,) = ret.unpack()
        return fd_list.get(fd_index)

    def close_session(self, session) -> None:
        Gio.DBusProxy.new_sync(
            self._bus, Gio.DBusProxyFlags.NONE, None,
            _PORTAL_BUS, session, _SESSION_IFACE, None,
        ).call_sync("Close", None, Gio.DBusCallFlags.NONE, -1, None)
```

- [ ] **Step 3: Verify the module imports and the existing suite is unaffected**

Run: `.venv/bin/python -c "import tea_clipper.portal"`
Expected: no output, exit 0 (module imports cleanly; no bus connection at import time).

Run: `.venv/bin/pytest tests/test_portal.py -v`
Expected: 10 passed (unchanged — these never instantiate `ScreenCastPortal`).

- [ ] **Step 4: Commit**

```bash
git add src/tea_clipper/portal.py
git commit -m "feat: ScreenCastPortal Gio/GDBus wrapper with unix-fd handoff"
```

---

## Task 5: portal_probe — real-hardware end-to-end script

**Files:**
- Create: `src/tea_clipper/portal_probe.py`

A runnable script (not part of pytest) that proves real capture on the KDE/Wayland target:
open the portal, record ~6s, save a 5s clip, tear down, persist the restore token.

- [ ] **Step 1: Create `src/tea_clipper/portal_probe.py`**

```python
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
```

- [ ] **Step 2: Smoke-check the script imports (no capture)**

Run: `.venv/bin/python -c "import tea_clipper.portal_probe"`
Expected: no output, exit 0.

- [ ] **Step 3: Manual hardware run (do on the KDE/Wayland desktop, not CI)**

Run: `.venv/bin/python -m tea_clipper.portal_probe`
Expected: a monitor picker appears on first run; after ~6s, prints `Saved clip: …/portal_probe_clip.mkv`.
Verify: `ffprobe -v error -show_entries stream=codec_type -of csv portal_probe_clip.mkv` lists `video` (no audio — this is video-only by design). A second run should NOT show the picker (restore token reused).

> If this step can't run now (headless session), leave it unchecked and note in the commit
> that hardware verification is pending. The automated suite stays green regardless.

- [ ] **Step 4: Commit**

```bash
git add src/tea_clipper/portal_probe.py
git commit -m "feat: portal_probe script for real-hardware screen-cast verification"
```

---

## Task 6: Docs + full-suite verification + finish

**Files:**
- Modify: `CLAUDE.md` (status update)

- [ ] **Step 1: Run the entire suite**

Run: `.venv/bin/pytest -m "engine or not engine"`
Expected: all green — settings/encoders/replay-buffer/portal unit tests plus engine
integration tests (including the new video-only test).

- [ ] **Step 2: Update the Status section of `CLAUDE.md`**

Under the engine-core status, add a PortalManager entry noting it is implemented
(real `pipewiresrc` capture via `ScreenCastPortal`, restore-token reuse, video-only),
with hardware verification via `python -m tea_clipper.portal_probe`, and that real
desktop+mic audio mixing, `HotkeyService`, `Controller`, and the UI remain deferred.
Reference the spec (`docs/superpowers/specs/2026-06-12-portalmanager-design.md`) and this
plan. Match the existing wording/format of that section.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record PortalManager (real screen capture) in CLAUDE.md status"
```

- [ ] **Step 4: Finish the branch**

Use superpowers:finishing-a-development-branch to verify tests, present integration
options, and complete the work (likely a PR into `main` like engine-core).

---

## Done criteria

- `pytest` green: new `tests/test_portal.py` (pure helpers + orchestration with a fake
  portal) and the video-only pipeline test, alongside all existing tests.
- `PortalManager.open()` returns a real `pipewiresrc` fragment, reuses/saves the restore
  token through `Settings`, and `close()` releases the fd + session.
- `python -m tea_clipper.portal_probe` captures the real screen into a playable clip on the
  KDE/Wayland target (manual verification).

## Deliberately deferred (later plans)

- Desktop + microphone audio capture/mixing (`audiomixer` over PipeWire sources).
- `HotkeyService` (GlobalShortcuts portal), `Controller`, and the PySide6 UI.
- Window/virtual source types and a custom monitor-selection UI (the portal's own picker
  suffices for now).
