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

## Status

Design is settled; implementation is just starting. There is no build/run command yet —
add one here (and to the README) once an entry point exists.
