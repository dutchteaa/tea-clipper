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
- GStreamer 1.22+ with the `pipewire`, `va`, and base/good/bad plugin sets
- PyGObject (GStreamer/GLib bindings) and PySide6 (Qt UI)
- ffmpeg (used to losslessly stitch saved clips)

> A full dependency list and install instructions will land here as the app takes shape.

## Status

🚧 **Early development.** The architecture and design are settled; implementation is
starting now. Expect things to change quickly.

## How it works (in one breath)

A single GStreamer pipeline captures the screen (`pipewiresrc`) and audio, encodes once
on the GPU, and feeds two sinks via a `tee`: a rolling segment buffer (instant replay)
and an on-demand manual recorder. Saving a clip just stitches the relevant segments with
`ffmpeg -c copy` — instant, no re-encode.

## Contributing

The project is written in plain Python on purpose: easy to read, easy to maintain, easy
to extend. Contributions welcome once the core lands.

## License

TBD.
