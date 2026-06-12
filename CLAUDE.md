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

Executing the engine-core plan task-by-task (TDD). **Done & committed on `engine-core`:**

- ✅ Task 1 — skeleton (`pyproject.toml`, `gst_init.ensure_gst`, `conftest` test harness)
- ✅ Task 2 — `settings.Settings` (dataclass + TOML)
- ✅ Task 3 — `encoders.EncoderRegistry` (probe + map codec→element; hw→sw fallback warns)
- ✅ Task 4 — `replay_buffer.ReplayBuffer` (segment selection + lossless ffmpeg `-c copy` stitch;
  uses a unique temp concat-list file and surfaces ffmpeg stderr on failure)
- ✅ Task 5 — `pipeline.CapturePipeline` (real GStreamer pipeline: test sources → x264enc →
  rolling auto-pruned `splitmuxsink` segments + `format-location-full` finalize pub/sub +
  `force_split()`; integration test proves it headlessly)

### NEXT SESSION — resume here (Tasks 6 & 7)

Both tasks have full code/tests in the plan file; follow them as written, but apply the same
real-pipeline adjustments already made in Task 5 (they should now just work since Task 5's
pipeline is correct).

- ⬜ **Task 6 — `ReplayBuffer.save_last`**: add `save_last(seconds, output_path, pipeline)` that
  calls `pipeline.force_split()` then `stitch(self.segments_for(seconds), output_path)`. Add the
  end-to-end engine test (`tests/test_pipeline_integration.py`): record ~6s, `save_last(4, ...)`,
  assert the clip exists, has video+audio, and ffprobe duration ≈ 4s. **Note:** `force_split`'s
  `_split_event` handshake is implemented in `pipeline.py` and ready to use — Task 6 is its first
  real exercise; verify it doesn't deadlock (it waits up to 3s).
- ⬜ **Task 7 — `manual_recorder.ManualRecorder`**: collects finalized segments while active,
  `start()` (force_split to begin on a clean boundary) / `stop(out)` (force_split + stitch the
  collected segments). Integration test: record ~5s, assert full-take clip. The plan intentionally
  duplicates the stitch logic here — fine for now (YAGNI); extract a shared helper only if a third
  consumer appears.

After Tasks 6 & 7: run `.venv/bin/pytest -m "engine or not engine"` (all green), then consider a
final review pass and `superpowers:finishing-a-development-branch`. **Deferred to later plans**
(not engine-core): `PortalManager` (real `pipewiresrc` capture via xdg-desktop-portal + restore
token, replacing `test_source_bin()`), real desktop+mic audio mixing (`audiomixer` of two
`pipewiresrc`), `HotkeyService` (GlobalShortcuts portal), `Controller`, and the PySide6 UI.
