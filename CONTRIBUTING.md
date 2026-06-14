# Contributing to tea-clipper

Thanks for your interest in helping out! tea-clipper is intentionally small in scope —
a Medal-style instant-replay clipper for Linux/Wayland — and the goal is to keep it that
way: easy to read, easy to maintain, easy to extend. This guide covers how to get set up,
how we work, and what we expect from a change.

> **Scope first:** before building a feature, check it fits the project's purpose (instant
> clips, the settings that matter, an easy UI). We apply **YAGNI** ruthlessly. If you're
> unsure whether something belongs, open an issue to discuss before writing code.

## Project layout

The engine is plain Python orchestrating C-level GStreamer elements (frames never enter
Python — Python only builds the pipeline and handles events). Each module is small and
single-purpose:

| Module | Responsibility |
| --- | --- |
| `src/tea_clipper/gst_init.py` | One-time `Gst.init()` + version guard (`ensure_gst()`) |
| `src/tea_clipper/settings.py` | `Settings` dataclass + TOML load/save |
| `src/tea_clipper/encoders.py` | `EncoderRegistry`: probe installed encoders, map codec → element (VAAPI, software fallback) |
| `src/tea_clipper/pipeline.py` | `CapturePipeline`: builds/owns the GStreamer pipeline, rolling segment buffer, segment-finalized pub/sub, `force_split()` |
| `src/tea_clipper/replay_buffer.py` | `ReplayBuffer`: track finalized segments, `save_last(seconds, out, pipeline)`, lossless `ffmpeg -c copy` stitch |
| `src/tea_clipper/manual_recorder.py` | `ManualRecorder`: collect segments while active, stitch a full take on `stop()` |
| `src/tea_clipper/portal.py` | `PortalManager` + `ScreenCastPortal`: ScreenCast portal negotiation, restore-token persistence, `pipewiresrc` video fragment (fps-limited) |
| `src/tea_clipper/hotkeys.py` | `HotkeyService` + `GlobalShortcutsPortal`: register global shortcuts, dispatch activations to listeners |
| `src/tea_clipper/audio.py` | audio device discovery (`pactl`), `@desktop@`/`@mic@` resolution, `audiomixer` launch-fragment builder |
| `src/tea_clipper/controller.py` | `Controller` + `build_controller`: wire capture + buffer + recorder + hotkeys into a runnable daemon, route hotkeys |
| `src/tea_clipper/ui/` | PySide6 tray + settings/status app: `EngineHost` (engine on a GLib worker thread), `SettingsForm`, `AudioPicker`, `MainWindow`, `TrayIcon`, `app` |

The architecture (one shared pipeline, `tee` to a rolling replay buffer + a manual sink)
is documented in [`CLAUDE.md`](CLAUDE.md). Specs and implementation plans live under
`docs/superpowers/`.

## Development setup

PyGObject is painful to build into a clean venv, so the venv must see the **system**
PyGObject + GStreamer:

```bash
python -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"
```

### System dependencies

Capture and encode run through GStreamer plugins that must be installed system-wide.
On Arch/CachyOS:

```bash
sudo pacman -S gst-plugins-good gst-plugins-base gst-plugin-pipewire \
               gst-plugin-va gst-plugins-ugly ffmpeg
```

`gst-plugins-good` is a **hard requirement** — it ships `splitmuxsink` and `matroskamux`,
the heart of the rolling buffer. Without it the engine cannot run (and its integration
tests will skip).

## Running tests

```bash
.venv/bin/pytest                            # unit tests only (fast, no GStreamer pipeline)
.venv/bin/pytest -m "engine or not engine"  # also run the real-pipeline integration tests
```

Integration tests that spin up a live GStreamer pipeline are marked `@pytest.mark.engine`
and automatically skip (via the `requires_engine` marker) when GStreamer or ffmpeg are
missing. They run **headlessly** by swapping the real screen capture (`pipewiresrc`) for
GStreamer test sources (`videotestsrc`/`audiotestsrc`), so the full
capture → buffer → stitch path is exercised without a real screencast.

Qt UI tests instantiate widgets under `QT_QPA_PLATFORM=offscreen` (set automatically by the
`qapp` conftest fixture), so they need no display. Code that must touch a live portal, D-Bus,
real devices, or a visible tray is **not** unit-tested — it's verified by the `*_probe.py`
scripts and by running `python -m tea_clipper.ui` on hardware. Keep that split: unit-test the
pure/orchestration logic with fakes, probe the rest.

## How we work

- **Test-Driven Development.** Write a failing test first, watch it fail, then write the
  minimal code to make it pass. Tests must verify real behavior — for the engine that means
  asserting on actual output files (e.g. ffprobe duration / codecs), not mocked internals.
- **Small, single-purpose modules.** If a file is growing past one clear responsibility,
  that's a signal to split it. Prefer clear interfaces over cleverness.
- **Match the surrounding style.** Readable Python over micro-optimizations — the hot path
  is in GStreamer, not Python.
- **Surface failures, don't crash.** Portal denial, encoder init failure, disk full, a
  missing mic — report them and fall back where sensible (software encode, video-only if
  the mic is absent) rather than letting the app die.
- **Keep commits focused** and use [Conventional Commits](https://www.conventionalcommits.org/)
  prefixes, matching the existing history: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`,
  `test:`.

## Submitting changes

1. Branch off `main` (all milestones are merged there now). Use a short descriptive branch name.
2. Make your change with tests; ensure `.venv/bin/pytest -m "engine or not engine"` is
   fully green.
3. Push and open a pull request describing **what** changed and **why**. Link any related
   issue.
4. Keep the PR scoped to one concern — small PRs get reviewed and merged faster.

## Reporting bugs and ideas

Open a GitHub issue at https://github.com/dutchteaa/tea-clipper/issues. For bugs, include
your distro, desktop/compositor (e.g. KDE Plasma on Wayland), GPU, GStreamer version
(`gst-launch-1.0 --version`), and the exact steps to reproduce. For feature ideas, describe
the use case — remember the project deliberately stays small, so the bar is "does this serve
instant clipping well?"

Happy clipping. 🍵
