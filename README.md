# 🍵 tea-clipper

A lightweight game-clipping tool for Linux — a Medal-style "instant replay" clipper
built for modern Wayland desktops.

tea-clipper continuously records your gameplay into a small, self-cleaning background
buffer. When something cool happens, hit a hotkey and the **last N seconds** are saved
as a clip. It also supports plain manual start/stop recording. All of it is configured
through a simple, no-nonsense UI.

> Repository: https://github.com/dutchteaa/tea-clipper

## Why?

There's no good Medal alternative on Linux. tea-clipper aims to cover the basics well:
instant clips, the settings that actually matter (clip length, encoder, bitrate), and an
easy UI to change them — nothing more, nothing less.

## Features

- **Instant replay buffer** — always recording in the background; press a hotkey to save
  the last *N* seconds.
- **Manual recording** — press to start, press to stop; the whole take becomes a clip.
- **Self-cleaning buffer** — the rolling buffer is bounded and auto-deletes old segments,
  so leaving it running for hours never fills your disk. Only clips *you* save are kept.
- **Hardware encoding** — VAAPI H.264 / H.265 / AV1 on supported GPUs, with a software
  fallback.
- **Audio** — desktop/game audio + microphone, mixed into the clip.
- **Simple UI** — pick your monitor once, set clip length, encoder, bitrate, and hotkeys.

## Requirements

tea-clipper targets **Wayland** desktops (developed on **KDE Plasma**) and captures via
the standard desktop portal, so it works without root or kernel hacks.

- Python 3.12+
- PipeWire + `xdg-desktop-portal` (with a backend, e.g. `xdg-desktop-portal-kde`)
- GStreamer 1.22+ (developed on 1.28) and PyGObject, with these plugin sets:
  - **`gst-plugins-good`** — ships `splitmuxsink` + `matroskamux`, the rolling-buffer core
    (**hard requirement**; the buffer cannot run without it)
  - **`gst-plugins-base`** — `opusenc`, `videoconvert`, audio elements
  - **`gst-plugin-pipewire`** — `pipewiresrc` (portal screen capture)
  - **`gst-plugin-va`** — VAAPI hardware encoders (`vah264enc` / `vah265enc` / `vaav1enc`)
  - **`gst-plugins-ugly`** — `x264enc` (software encode fallback)
- PySide6 (Qt UI — used by the forthcoming settings UI; not needed for the engine)
- ffmpeg (used to losslessly stitch saved clips)

On Arch/CachyOS, the plugin sets above map to:
`sudo pacman -S gst-plugins-good gst-plugins-base gst-plugin-pipewire gst-plugin-va gst-plugins-ugly ffmpeg`

## Status

🚧 **Early development — engine + capture + hotkeys done; app wiring next.**

Every capture-side piece is built, unit-tested, and verified against real hardware on
KDE/Wayland (AMD RDNA3):

- ✅ Settings (TOML), encoder probing/selection (VAAPI with software fallback)
- ✅ Rolling, self-pruning segment buffer + per-segment finalize events
- ✅ Lossless clip stitching (`ffmpeg -c copy`)
- ✅ Save-last-N-seconds clips and manual full-take recording
- ✅ Real screen capture via `xdg-desktop-portal` ScreenCast (`pipewiresrc`, persistent
  restore token) — hardware-verified producing a real H.264 clip
- ✅ Global hotkeys via the GlobalShortcuts portal (`save_clip` / `toggle_record`) —
  hardware-verified firing on KDE
- 🔜 **Controller** — wire portal + pipeline + buffer + recorder + hotkeys into a runnable
  daemon (next milestone, the headless MVP)
- 🔜 Real desktop + microphone audio mixing (capture is currently video-only)
- 🔜 PySide6 settings/status UI

The engine is also proven **headlessly** using GStreamer test sources, so the whole
capture → buffer → stitch path is exercised in CI without a real screencast.

## Development

```bash
# venv must see the system PyGObject + GStreamer (don't pip-build PyGObject):
python -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/pytest                          # unit tests only
.venv/bin/pytest -m "engine or not engine"  # + real-pipeline integration tests
```

Engine integration tests are marked `@pytest.mark.engine` and auto-skip when
GStreamer/ffmpeg are unavailable.

## How it works (in one breath)

A single GStreamer pipeline captures the screen (`pipewiresrc`) and audio, encodes once
on the GPU, and feeds two sinks via a `tee`: a rolling segment buffer (instant replay)
and an on-demand manual recorder. Saving a clip just stitches the relevant segments with
`ffmpeg -c copy` — instant, no re-encode.

## Contributing

The project is written in plain Python on purpose: easy to read, easy to maintain, easy
to extend. Contributions welcome once the core lands.

## License

[MIT](LICENSE) © dutchteaa
