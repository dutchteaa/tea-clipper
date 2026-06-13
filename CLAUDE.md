# CLAUDE.md

Guidance for Claude Code when working in this repository.

> **Repository:** https://github.com/dutchteaa/tea-clipper

## What this is

**tea-clipper** is a Medal-style game-clipping tool for Linux/Wayland. It keeps a rolling
"instant replay" buffer of recent gameplay and saves the last *N* seconds to a clip on a
hotkey, and also supports manual start/stop recording. Scope is deliberately small:
instant clips, the settings that matter (clip length, encoder, bitrate, hotkeys), and an
easy UI. Resist scope creep — YAGNI.

## Tech stack

- **Language:** Python (3.12+). Chosen for maintainability and low contributor barrier.
- **Capture/encode engine:** GStreamer via **PyGObject** (`gi`). Frames never enter
  Python — the pipeline runs entirely in C-level GStreamer elements, so Python only
  builds the pipeline and handles events. This is why Python is fast enough here.
- **UI:** **PySide6** (Qt 6). Native fit for KDE.
- **Clip stitching:** **ffmpeg** subprocess (`-c copy`, lossless, no re-encode).
- **OS integration:** D-Bus desktop portals (`org.freedesktop.portal.ScreenCast` for
  capture, `org.freedesktop.portal.GlobalShortcuts` for hotkeys).

## Target environment

Developed and tested on **Wayland + KDE Plasma** with PipeWire and an **AMD RDNA3 GPU**
(VAAPI encode: `vah264enc` / `vah265enc` / `vaav1enc`). Do not assume X11 or direct
framebuffer access — capture must go through the portal + PipeWire. Provide a software
encoder fallback (`x264enc`) for unsupported GPUs.

## Architecture

One shared GStreamer pipeline: capture + encode **once**, then `tee` to two sinks so the
GPU isn't taxed twice.

```
 pipewiresrc (monitor) ─► vapostproc ─┐
                                      ├─► vaENCODER ─► tee ─┬─► replay splitmuxsink (rolling segments, auto-pruned)
 desktop audio ─┐                     │                    └─► manual sink (single file, toggled on hotkey)
                ├─► audiomixer ─► opusenc ┘
 microphone ────┘
```

- **Replay buffer:** `splitmuxsink` writes ~2s segments into a temp ring dir with
  `max-files` set so old segments auto-delete. Buffer disk use is bounded
  (`≈ bitrate × clip_length`) — running for hours never fills the disk. Encoder keyframe
  interval is pinned to segment length so segments are independently concatenable.
- **Save clip:** stitch the last *N* segments with `ffmpeg -c copy` into the clips folder.
- **Manual record:** the second tee branch; a sink dynamically linked on start and
  finalized on stop, independent of the rolling ring.
- **Only saved clips persist.** Buffer segments are throwaway.

### Planned components (each isolated, single-purpose)

- `PortalManager` — D-Bus ScreenCast negotiation, monitor selection, restore-token
  persistence; GlobalShortcuts registration.
- `CapturePipeline` — builds/owns the GStreamer pipeline; start/stop/state.
- `ReplayBuffer` — rolling segment dir management + `save_last(seconds)` via ffmpeg.
- `ManualRecorder` — manual branch start/stop + file finalize.
- `HotkeyService` — global shortcuts → signals (`save_clip`, `toggle_record`).
- `EncoderRegistry` — probe available encoders, map UI choice → element + properties.
- `Settings` — load/save config (source token, clip length, encoder, bitrate, fps,
  audio devices, hotkeys, output dir).
- `Controller` — wires it all together; owns app lifecycle.
- `UI` (PySide6) — settings form + status indicator + open-folder/re-pick-source.

## Testing approach

- Swap `pipewiresrc` for `videotestsrc`/`audiotestsrc` to exercise the full
  tee → splitmuxsink → ffmpeg-concat path **headlessly**, no real screencast needed.
- Unit-test `Settings`, `EncoderRegistry` parsing, and `ReplayBuffer` concat logic with
  fake segment files. Mock D-Bus for `PortalManager`.
- Use TDD where practical (see superpowers `test-driven-development`).

## Conventions

- Keep modules small and single-purpose; prefer clear interfaces over cleverness.
- Match the surrounding code's style; readable Python over micro-optimizations (the hot
  path is in GStreamer, not Python).
- Surface failures to the UI (portal denial, encoder init failure, disk full) rather than
  crashing; fall back where sensible (software encode, video-only if mic missing).

## Development

- **Branch:** engine-core work lives on the `engine-core` branch (not yet merged to default).
- **Venv:** created with `python -m venv --system-site-packages .venv` so it can see the
  **system** PyGObject + GStreamer 1.28 (PyGObject is painful to pip-build into a clean venv).
  pytest + tomli-w are pip-installed into the venv.
- **Run tests:** `.venv/bin/pytest` (unit only) or `.venv/bin/pytest -m "engine or not engine"`
  to include the real-pipeline integration tests. Engine tests are marked `@pytest.mark.engine`
  and auto-skip via the `requires_engine` marker when GStreamer/ffmpeg are absent.
- **System dependency discovered:** the rolling-buffer design needs `splitmuxsink` +
  `matroskamux`, which ship in **`gst-plugins-good`** (Arch: `sudo pacman -S gst-plugins-good`).
  This was missing initially and blocked Task 5 until installed. It is a hard runtime dep.
- **GStreamer specifics that bit us (keep in mind):** use `muxer-factory=matroskamux` on
  `splitmuxsink` (the `muxer=` property wants an element instance, not a name). `test_source_bin()`
  returns a `(video, audio)` tuple of launch fragments.

## Status — engine core (plan: docs/superpowers/plans/2026-06-12-engine-core.md)

Engine-core is **complete** (Tasks 1–7) on `engine-core` (open PR #1 → `main`). TDD throughout;
`.venv/bin/pytest -m "engine or not engine"` is green. **Done & committed on `engine-core`:**

- ✅ Task 1 — skeleton (`pyproject.toml`, `gst_init.ensure_gst`, `conftest` test harness)
- ✅ Task 2 — `settings.Settings` (dataclass + TOML)
- ✅ Task 3 — `encoders.EncoderRegistry` (probe + map codec→element; hw→sw fallback warns)
- ✅ Task 4 — `replay_buffer.ReplayBuffer` (segment selection + lossless ffmpeg `-c copy` stitch;
  uses a unique temp concat-list file and surfaces ffmpeg stderr on failure)
- ✅ Task 5 — `pipeline.CapturePipeline` (real GStreamer pipeline: test sources → x264enc →
  rolling auto-pruned `splitmuxsink` segments + `format-location-full` finalize pub/sub +
  `force_split()`; integration test proves it headlessly)

- ✅ Task 6 — `ReplayBuffer.save_last(seconds, output_path, pipeline)` (force_split + stitch last
  *N* seconds; end-to-end engine test proves a ~4s playable A/V clip).
- ✅ Task 7 — `manual_recorder.ManualRecorder` (collect segments while active; `start()`/`stop(out)`
  force clean boundaries and stitch the full take; engine test proves a ~5s clip). The stitch logic
  is intentionally duplicated from `ReplayBuffer` (YAGNI) — extract a shared helper only if a third
  consumer appears.

## Status — PortalManager / real screen capture

Spec: `docs/superpowers/specs/2026-06-12-portalmanager-design.md` · Plan:
`docs/superpowers/plans/2026-06-12-portalmanager.md`. Implemented (TDD) on the
`portal-manager` branch (stacked on `engine-core`):

- ✅ `pipeline.CapturePipeline` now accepts a **video-only** source: `source_desc` audio fragment
  may be `None`, which omits the `opusenc ! replaymux.audio_0` branch.
- ✅ `portal.PortalManager` — negotiates `org.freedesktop.portal.ScreenCast`
  (CreateSession → SelectSources(MONITOR, embedded cursor, persist) → Start → OpenPipeWireRemote),
  reuses/saves `Settings.source_restore_token`, and returns a `pipewiresrc fd=… path=…` video
  fragment that replaces `test_source_bin()`'s video half. `close()` releases the fd + session.
- ✅ `portal.ScreenCastPortal` — raw Gio/GDBus wrapper (no new dep). Request/Response handshake on a
  private `GLib.MainLoop`; unix-fd handoff via `call_with_unix_fd_list_sync`. Not unit-tested
  (needs a live portal + human at the picker); verified by the probe.
- ✅ `portal_probe.py` (`python -m tea_clipper.portal_probe`) — real-hardware end-to-end check.
  **Hardware-verified** on KDE/Wayland (AMD RDNA3): produced a real 2560×1440 H.264 video-only
  clip. (Note: a cold-start probe clip runs a bit short due to `pipewiresrc` startup latency;
  irrelevant in normal use where the rolling buffer is always full.)
- Pure logic (`build_select_sources_options`, `parse_start_results`, `build_video_fragment`) and
  `PortalManager` orchestration are unit-tested with a fake portal (`tests/test_portal.py`).

## Status — HotkeyService / global shortcuts

Spec: `docs/superpowers/specs/2026-06-12-hotkeyservice-design.md` · Plan:
`docs/superpowers/plans/2026-06-12-hotkeyservice.md`. Implemented (TDD) on the
`hotkey-service` branch (standalone `hotkeys.py`; `ScreenCastPortal` untouched, per the
chosen approach):

- ✅ `hotkeys.HotkeyService` — binds `save_clip` + `toggle_record` via
  `org.freedesktop.portal.GlobalShortcuts` (CreateSession → BindShortcuts → subscribe
  `Activated`), and dispatches each activation to zero-arg listeners registered per action id.
  Owns a long-lived `GLib.MainLoop` on a daemon thread; `start(run_loop=False)` lets a caller
  (the future `Controller`) drive its own loop instead.
- ✅ `hotkeys.GlobalShortcutsPortal` — standalone raw Gio/GDBus wrapper (own copy of the
  session/await-response machinery; reuses `portal.py`'s exception classes only). Not
  unit-tested; verified by the probe.
- ✅ `hotkey_probe.py` (`python -m tea_clipper.hotkey_probe`) — real-hardware check.
  **Hardware-verified** on KDE/Wayland: both `save_clip` and `toggle_record` registered and
  fired on key press.
- Pure `build_shortcuts_list()` and `HotkeyService` orchestration are unit-tested with a fake
  portal (`tests/test_hotkeys.py`).
- Binding model is portal-native: the app suggests default triggers (`Ctrl+Alt+C` /
  `Ctrl+Alt+R`); KDE owns the real binding and the user rebinds in System Settings.

## Status — Controller / runnable MVP

Spec: `docs/superpowers/specs/2026-06-12-controller-design.md` · Plan:
`docs/superpowers/plans/2026-06-12-controller.md`. Implemented (TDD) on the `controller` branch:

- ✅ `controller.Controller` — owns the app `GLib.MainLoop` and routes hotkeys:
  `save_clip → ReplayBuffer.save_last(clip_length_seconds, …)` and `toggle_record →
  ManualRecorder.start()/stop()`, writing timestamped clips to `settings.output_dir`. Per-action
  failures are caught/logged so one bad clip never kills the daemon. The hotkey service runs with
  `run_loop=False` to share the Controller's loop.
- ✅ `controller.build_controller(settings)` — wires the real stack: `PortalManager.open()` →
  `EncoderRegistry.resolve` → video-only `CapturePipeline` → `ReplayBuffer` + `ManualRecorder` as
  segment listeners → `HotkeyService`.
- ✅ `__main__.py` — **the MVP is now runnable headless: `python -m tea_clipper`** (opens capture,
  keeps the buffer full, hotkeys save/record; persists the restore token; Ctrl-C exits cleanly).
  **Hardware-verified** on KDE/Wayland: the daemon reused the restore token (no picker), and both
  hotkeys wrote real 2560×1440 H.264 files (`clip_*.mkv`, `recording_*.mkv`) to `output_dir`.
- `compute_max_segments` + `Controller` handlers/lifecycle are unit-tested with fakes
  (`tests/test_controller.py`); `build_controller`/entrypoint are probe-verified.

**Last deferred milestone:** the PySide6 settings/status UI.

## Status — Audio capture / desktop + mic mixing

Spec: `docs/superpowers/specs/2026-06-13-audio-design.md` · Plan:
`docs/superpowers/plans/2026-06-13-audio.md`. Implemented (TDD) on the `audio` branch
(stacked on `main`):

- ✅ `audio.AudioDevice` + `audio.discover_audio_devices()` — enumerates **sinks** (desktop
  audio, `is_monitor=True`) + real non-monitor **sources** (mics) by parsing `pactl list sinks`
  and `pactl list sources` (Name = node.name, Description = display name), marking defaults via
  `pactl get-default-sink`/`-source`. Degrades gracefully to `[]` if `pactl` is missing. The
  pure parsers (`_parse_pactl_blocks`, `_parse_pactl_devices`) are **unit-tested**;
  `discover_audio_devices` (live `pactl` I/O) is **probe-verified**.
  **IMPORTANT — two PipeWire gotchas found during hardware verification:**
  1. `Gst.DeviceMonitor` does **not** surface sink monitors on the target hardware → we use
     `pactl` instead (its sink/source `Name`s are exactly what `pipewiresrc target-object=`
     accepts).
  2. There is **no `.monitor` node** in PipeWire — `<sink>.monitor` is a PulseAudio-compat
     fiction. `pipewiresrc target-object=<...monitor>` matches no node and captures **silence**.
     Desktop audio is captured by targeting the **sink** node with `stream.capture.sink=true`
     (taps the sink's monitor ports); mics target real source nodes normally. (The mic happened
     to work pre-fix only because it's the default source.)
- ✅ `audio.resolve_audio_devices(settings, available)` + `audio.build_audio_fragment(devices)` —
  pure, unit-tested. `resolve` expands the `@desktop@`/`@mic@` tokens to the default sink/mic,
  passes literal `node.name`s through, skips unavailable entries (logged), de-dupes, and returns
  **`AudioDevice` objects** (so the builder knows which need `stream.capture.sink`). `build`
  assembles one `pipewiresrc target-object=<name> … ! amix.` chain per device (sinks add
  `stream-properties="props,stream.capture.sink=true"`) into `audiomixer name=amix ! … !
  audio/x-raw,channels=2 ! queue name=aenc_in` (stereo-pinned), or `None` when empty
  (→ video-only). The pipeline already appends `! opusenc ! replaymux.audio_0`.
- ✅ `Settings.audio_devices: list[str]` (default `["@desktop@", "@mic@"]`) **replaces** the old
  `desktop_audio`/`microphone` booleans. `[]` = explicit no-audio. `Settings.load` drops unknown
  keys, so an old config silently falls back to the new default (no migration needed).
- ✅ `audio_probe.py` (`python -m tea_clipper.audio_probe`) — lists discoverable devices
  (node.name + display name + desktop/mic + default flags) so users know what to put in
  `audio_devices`; doubles as the hardware probe.
- ✅ `build_controller` now passes the resolved mixed audio fragment to `CapturePipeline`
  (`source_desc=(video, audio)` instead of `(video, None)`).
- Unit tests in `tests/test_audio.py` (resolve/build/`_parse_pactl_devices`) + the settings
  round-trip; `.venv/bin/pytest -m "engine or not engine"` is **60 passing**.
- ✅ **Hardware-verified** on KDE/Wayland (AMD RDNA3): `python -m tea_clipper.audio_probe` lists
  sinks `(desktop)` + mics with the JBL flagged `[default]`; the real
  `discover → resolve(@desktop@/@mic@) → build_audio_fragment` chain fed `! opusenc ! matroskamux`
  produced a **stereo** mixed-audio Opus clip with real desktop+mic signal (volumedetect
  mean −31 dB / max −14 dB; the broken `.monitor` version measured −50 dB silence). The live
  `python -m tea_clipper` daemon was also confirmed writing video+audio buffer segments
  (H.264 2560×1440 + Opus). Remaining nicety: a final by-ear `python -m tea_clipper` clip.

## NEXT SESSION — handoff

**State:** the four core milestones (engine-core, PortalManager, HotkeyService, Controller) are
merged to `main` and hardware-verified. The **audio** milestone is built, unit-tested, and
audio-path hardware-verified on the `audio` branch (suite **56 passing**,
`.venv/bin/pytest -m "engine or not engine"`); discovery was switched from GstDeviceMonitor to
`pactl` during verification (see the Audio capture status above). `python -m tea_clipper` runs a
working clipper today.

**Optional final confirm before/after merging `audio`:** a full `python -m tea_clipper` run —
play audio + speak, press save hotkey, Ctrl-C, then
`ffprobe "$(ls -t ~/Videos/tea-clipper/clip_*.mkv | head -1)"` should show an Opus audio stream
alongside the H.264 video. (The audio path is already proven in isolation; this just confirms
video+audio muxing together under the live portal/hotkeys.)

**One milestone remains:**

1. **PySide6 settings/status UI** (last). A small Qt form over `Settings` (clip length, codec,
   bitrate, fps, **`audio_devices` picker** driven by `audio.discover_audio_devices()`, output
   dir) + a status indicator + open-folder / re-pick-source buttons, driving a `Controller`.
   KDE-native fit.

**Gotchas worth remembering:**
- `pipewiresrc` has cold-start latency — a clip saved within the first few seconds of launch is
  short because the buffer isn't full yet. Irrelevant once it's been running a while.
- Engine/portal/hotkey/audio real-D-Bus & device-enumeration code is **not** unit-tested (can't
  run headlessly); it's verified by the `*_probe.py` scripts and `python -m tea_clipper`. Keep
  that split — unit-test the pure/orchestration logic with fakes, probe the rest on hardware.
- Audio default-device detection shells out to `pactl` (PipeWire's PulseAudio-compat CLI) — a
  runtime dep in the same spirit as the `ffmpeg` subprocess and the `gst-plugins-good` requirement.
  It degrades gracefully if absent (the `@desktop@`/`@mic@` tokens just resolve to nothing).
- Git push auth on this machine goes through KWallet (see agent memory `git-auth-kwallet`); first
  push for a new token must be interactive.
