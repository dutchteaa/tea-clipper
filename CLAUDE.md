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
  (H.264 2560×1440 + Opus), and a hotkey-saved clip measured mean −31 dB / max −6 dB of real
  stereo signal.
- ✅ **Merged:** PR #5 (`audio` → `main`, commit `e3aec69`).

## Status — PySide6 UI (tray + window)

Spec: `docs/superpowers/specs/2026-06-14-ui-design.md` · Plan:
`docs/superpowers/plans/2026-06-14-ui.md`. Implemented (TDD) on the `ui` branch (stacked on
`main`). Medal-style: capture runs in the background, the window is a view into it.

- **Threading model (the key decision):** Qt owns the main thread (`QApplication.exec()`); a
  daemon worker thread owns the engine's `GLib.MainLoop` + `Controller`. `build_controller()`
  blocks on portal negotiation, so it *must* run off the UI thread. UI→engine actions marshal
  via `GLib.idle_add`; engine→UI updates come back as thread-safe Qt signals.
- ✅ `ui/engine_host.py` — `EngineHost(QObject)`: the **only** place threading lives. Builds/
  starts/stops the `Controller` on the worker thread, persists the restore token, re-emits
  engine events as Qt signals `state_changed(state, detail)` / `clip_saved(path)`. State
  machine: `Idle → Starting → Recording`, `Recording → Restarting → Recording` (Apply/Re-pick),
  any → `Error(detail)`. `apply_settings`/`repick_source` restart capture; `save_clip`/
  `toggle_record` dispatch to the controller. **Unit-tested** with a fake builder/controller
  (`tests/test_engine_host.py`); the worker thread + real loop is probe-verified.
- ✅ `ui/settings_form.py` — `SettingsForm(QWidget)`: pure `Settings` ↔ widget mapping
  (clip length, codec combo, hardware, bitrate, fps, output dir, audio picker). `load`/`collect`
  round-trip preserves fields it doesn't edit (`segment_seconds`, `buffer_dir`,
  `source_restore_token`). **Unit-tested offscreen** (`tests/test_settings_form.py`).
- ✅ `ui/audio_picker.py` — `AudioPicker(QWidget)`: checkable grouped list (Default desktop/mic
  tokens + concrete sinks/mics from `discover_audio_devices()`) → `settings.audio_devices`
  (tokens or `node_name`s; empty = video-only). **Unit-tested** (`tests/test_audio_picker.py`).
- ✅ `ui/main_window.py` — status dot + form + **Apply** (confirmation dialog warns capture
  restarts) / **Open clips folder** / **Re-pick source**; window close hides to tray.
- ✅ `ui/tray.py` — `QSystemTrayIcon` menu (Open settings · Save clip now · Toggle recording ·
  Open clips folder · Quit); tooltip reflects state.
- ✅ `ui/app.py` + `ui/__main__.py` — **`python -m tea_clipper.ui`** wires it all and auto-starts
  capture. The headless daemon (`python -m tea_clipper`) is **kept** untouched.
- ✅ `ui/icons.py` + `ui/shortcuts.py` — `app_icon()` resolves a freedesktop theme icon
  (`media-record` → fallbacks) so KDE shows a real tray/window icon (app metadata set in
  `app.py`); `open_shortcuts_editor()` launches KDE's shortcut editor (`systemsettings kcm_keys`),
  shared by the tray menu and a window button. Global shortcuts are compositor-owned (we only
  suggest defaults), so "change keybinds" = open the system editor, not an in-app key field.
- Post-MVP refinements on this branch: **Save clip + checkable Record toggle** buttons in the
  window; **Configure shortcuts…** in both the tray menu and the window.
- Suite is **78 passing** (`.venv/bin/pytest`). PySide6 added to `pyproject` (`dev`/`gui` extras);
  unit tests run with `QT_QPA_PLATFORM=offscreen` via a `qapp` conftest fixture.
- ✅ **Hardware-verified** on KDE/Wayland (AMD RDNA3): `python -m tea_clipper.ui` launches the
  tray + window, auto-starts capture (restore token reused, no picker), and the rolling buffer
  fills continuously; a hotkey-triggered save produced a valid 14s H.264+Opus clip and the
  window's "Last clip" updated. Tray icon confirmed visible.

## Status — fps fix (capture framerate)

`settings.fps` previously fed **only** the encoder keyframe interval (`key-int-max`), never the
real capture rate — `pipewiresrc` delivered at the monitor's native refresh (165 Hz on the
target), so clips were 165 fps regardless of the setting. Fixed on the `ui` branch:
`portal.build_video_fragment(fd, node_id, fps)` now inserts `videorate ! video/x-raw,framerate=
<fps>/1`, driven by `settings.fps`. **Hardware-verified:** with `fps=60`, fresh buffer segments
report `r_frame_rate=60/1` (was 165). Unit-tested in `tests/test_portal.py` (pure fragment +
`PortalManager.open` passes `settings.fps`). The test source's hardcoded `framerate=30/1` is
untouched.

## Status — packaging (AUR build)

The **first installable build is done and released as `v0.1.0`** (tag pushed; `main` at
`2062a30`). Chose the **AUR PKGBUILD** format — native fit for the Arch/CachyOS target; it
**declares** the native GStreamer/PyGObject/PySide6/ffmpeg/pactl stack as deps rather than
bundling it (a self-contained PyInstaller/Nuitka binary is painful: gi typelibs + GStreamer
plugin registry + VAAPI). Flatpak is the deferred option for cross-distro distribution.

- ✅ `pyproject.toml` — `version` `0.0.1`→`0.1.0`; `[project.scripts]` console entry points
  `tea-clipper = tea_clipper.ui.app:main` + `tea-clipper-daemon = tea_clipper.__main__:main`;
  SPDX `license = "MIT"`, readme, URLs. **Gotcha hit:** with the SPDX `license` field, modern
  setuptools (PEP 639) **forbids** the old `License :: OSI Approved` classifier — the wheel build
  aborts until it's removed. Don't re-add it.
- ✅ `assets/tea-clipper.svg` — real app icon (teacup + red record dot; legible at 32px),
  installed into the hicolor theme as `tea-clipper`. `ui/icons.app_icon()` now prefers the bundled
  `tea-clipper` name, then `media-record`→fallbacks, then the Qt glyph (so a source checkout still
  shows *something*).
- ✅ `tea-clipper.desktop` — `Exec=tea-clipper`, `Icon=tea-clipper` (matches
  `app.setDesktopFileName("tea-clipper")`), `AudioVideo;Recorder`; passes `desktop-file-validate`.
- ✅ `PKGBUILD` — `depends` = `python python-gobject python-tomli-w gstreamer gst-plugins-base
  gst-plugins-good gst-plugin-pipewire gst-plugin-va gst-plugins-ugly pyside6 ffmpeg libpulse
  xdg-desktop-portal` (the portal **frontend** is a hard dep — the app calls ScreenCast +
  GlobalShortcuts over D-Bus; all confirmed in official Arch/CachyOS repos — **no AUR-only deps**);
  `optdepends` `xdg-desktop-portal-kde` (the **backend**, DE-specific); `makedepends`
  `python-build python-installer python-wheel python-setuptools` (setuptools = the build backend).
  `build()`/`package()` follow the official PEP 517 snippet (`python -m build --wheel
  --no-isolation` → `python -m installer --destdir=…`); the `.desktop`/icon/LICENSE are installed
  **by the PKGBUILD directly**, not via setuptools.
- ✅ **Standards-audited** against the live Arch Wiki *Python package guidelines* + *AUR submission
  guidelines* (2026-06): maintainer email obfuscated; `arch=any` (pure-Python); upstream source
  tarball per RFC0020; no `check()` (the suite needs offscreen Qt + the package importable and is
  split unit-vs-hardware-probe — can't be validated in a clean chroot from here; it's a SHOULD, not
  a MUST). The **AUR repo** also ships a 0BSD `LICENSE` for the packaging sources + a `.gitignore`
  (`*` then force-add `PKGBUILD`/`.SRCINFO`/`LICENSE`) so `makepkg` artifacts never get committed.
- ✅ **Verified:** wheel builds clean; `installer` via the system interpreter lands
  `/usr/bin/tea-clipper{,-daemon}` + `/usr/lib/python3.x/site-packages/tea_clipper/` + the
  hicolor icon + desktop + license; `makepkg --verifysource` passes against the published
  `v0.1.0` tarball (checksum pinned via `updpkgsums`). **Runtime-verified** by `pip install .`
  into the venv → the packaged `tea-clipper` console script auto-started capture (restore token
  reused, no picker) and filled the rolling buffer with H.264 2560×1440@60 + Opus-stereo segments.

- ✅ **Full `makepkg -si` hardware-verified** by the user on the dev box (Arch/CachyOS + KDE
  Wayland): the package builds from the recipe, installs cleanly, and the installed **tea-clipper**
  launches and works. (A cold-start save right after launch can produce a short/empty clip — the
  buffer isn't full yet; this is expected, not a bug.)
- ✅ **Released:** GitHub Release `v0.1.0` (https://github.com/dutchteaa/tea-clipper/releases/tag/v0.1.0).

## Status — UI feedback (clip-saved toast + record-state sync)

Spec: `docs/superpowers/specs/2026-06-16-ui-feedback-design.md` · Plan:
`docs/superpowers/plans/2026-06-16-ui-feedback.md`. Implemented (TDD, subagent-driven) on the
`ui-feedback` branch (stacked on `main`). Routes engine events through the existing
`Controller` callback → `EngineHost` Qt signal → UI pattern (same worker→main queued-signal
path as `clip_saved`).

- ✅ `Controller.recording_changed_cb` — fired **only** on a successful start/stop transition
  (never when the recorder raises), so the UI never shows a state the engine didn't reach.
  `build_controller` threads it through. Mirrors the existing `clip_saved_cb`/`_notify_saved`.
- ✅ `EngineHost.recording_changed = Signal(bool)` — re-emits the callback as a thread-safe Qt
  signal.
- ✅ `MainWindow` Record button now reflects **engine truth**: switched from `toggled`-drives-
  action to `clicked`-requests-toggle, with checked-state + label set only from
  `recording_changed`. Because `QPushButton.clicked` doesn't fire on programmatic `setChecked`,
  there's no feedback loop — **this fixes the latent staleness bug** (the deferred-polish item).
- ✅ `TrayIcon` — clip-saved desktop **toast** (`showMessage("Clip saved", <basename>)`, covers
  both instant clips and finished recordings since both fire `clip_saved`); the toggle menu
  action relabels Start/Stop on `recording_changed` and toasts "Recording started" on start
  (no toast on stop — the clip-saved toast already covers it, avoiding a double notification).
- Suite **101 passing** post-merge (`.venv/bin/pytest`); new `tests/test_main_window.py` +
  `tests/test_tray.py` plus extended controller/engine-host tests. Per-task spec+quality review
  and a final integration review all passed.
- ✅ **Hardware-verified** (2026-06-17) on KDE/Wayland: `python -m tea_clipper.ui` — hotkey/tray/
  window-button stay in sync and the clip-saved + "Recording started" toasts appear. Merged to
  `main`.

## Status — startup update check (GitHub Releases)

Spec: `docs/superpowers/specs/2026-06-16-update-check-design.md` · Plan:
`docs/superpowers/plans/2026-06-16-update-check.md`. Implemented (TDD, subagent-driven) on the
`update-check` branch (stacked on `main`). AUR isn't published yet (registration disabled), so
GitHub Releases is the source; **"update" only opens the release page** — no self-install (that
would fight pacman). GUI only — the headless daemon is untouched.

- ✅ `__init__.__version__` bumped `0.0.1`→`0.1.0` to match `pyproject.toml` (now the version
  source of truth; keep both in sync on a `pkgver` bump).
- ✅ `Settings.skipped_update_version: str = ""` — persists a permanently-skipped release tag.
  `Settings.load` already drops unknown keys, so old configs are forward-compatible.
- ✅ `update_check.py` — stdlib-only (`urllib`+`json`, **no new dep**): `parse_version` (tolerant,
  never raises), `is_newer`, `should_prompt`, `UpdateInfo`, and `fetch_latest_release()` which
  returns `None` on **any** network/HTTP/JSON error (never raises into the UI). `CURRENT_VERSION =
  tea_clipper.__version__`.
- ✅ `ui/update_prompt.py` — pure `decide_update_action(info, settings)` (unit-tested) + a
  `QThread`-based `UpdateChecker`: the blocking fetch runs on a worker thread, the result marshals
  back via a Qt signal, and a `QMessageBox` (Update → open release page / Skip this version →
  persist / Not now) shows on the main thread. `app.py` starts it after `host.start()` and retains
  the reference (`app._tea_updater`) so the running QThread isn't GC'd.
- Suite **101 passing** post-merge (`.venv/bin/pytest`); new `tests/test_update_check.py` +
  `tests/test_update_prompt.py` + extended settings tests. Per-task + final integration review
  passed. With the live release at `v0.1.0` and the running version `0.1.0`, `should_prompt` is
  False → **no dialog** (correct "you're up to date" path).
- **Deliberate YAGNI deviation from the spec:** the spec mentioned an `importlib.metadata`
  fallback for `CURRENT_VERSION`; dropped because `__version__` always exists. The plain import is
  the simpler correct choice.
- ✅ **Hardware-verified** (2026-06-17) on KDE/Wayland: launched `python -m tea_clipper.ui` and
  confirmed the "up to date" path (no dialog at `v0.1.0`). Merged to `main`. The forced-dialog
  probe (temporarily lowering `__version__` to confirm the notes + 3 buttons) remains the way to
  exercise the dialog UI if it changes.

## Status — single-instance lock

Spec: `docs/superpowers/specs/2026-06-21-single-instance-design.md` · Plan:
`docs/superpowers/plans/2026-06-21-single-instance.md`. Implemented (TDD, subagent-driven) on the
`single-instance` branch (stacked on `main`). Prevents a second `tea-clipper` from launching across
**both** entrypoints (a second instance would open a second screencast session + rolling buffer and
fight over the hotkeys). Two cleanly separated layers:

- ✅ `single_instance.py` — **stdlib-only, no Qt** (the GLib daemon imports it): `lock_path()`
  (`$XDG_RUNTIME_DIR/tea-clipper.lock`, fallback `tempfile.gettempdir()`) + `InstanceLock`
  (`fcntl.flock(LOCK_EX|LOCK_NB)`; `acquire()->bool` is **True** when held *or when the lock file is
  unusable* — degrade gracefully, never block launch — and **False** only on contention;
  `release()` idempotent). The OS auto-releases the lock on process exit/crash, so there is **no
  stale-PID cleanup**. Unit-tested (`tests/test_single_instance.py`).
- ✅ `ui/instance_server.py` — **Qt, GUI-only** activation channel over a `QLocalServer`/`QLocalSocket`
  named `"tea-clipper"`: `serve(on_activate)` (calls `removeServer()` before `listen()` to clear a
  stale socket from a crash; returns the server so the caller keeps it alive) + `try_activate()->bool`.
  Round-trip unit-tested offscreen (`tests/test_instance_server.py`, socket name monkeypatched
  per-PID so the suite never collides with a live instance).
- ✅ `MainWindow.bring_to_front()` — `showNormal()`+`show()`+`raise_()`+`activateWindow()` (un-hide
  from tray + focus). Unit-tested offscreen.
- ✅ Wiring: `ui/app.py` acquires the lock right after `QApplication` (before `EngineHost`); on
  contention it `try_activate()`s the running GUI's window and `return 0`; on success it
  `serve(window.bring_to_front)` (ref kept on `app._tea_instance_server`) and releases in a
  `finally`. `__main__.py` acquires before `build_controller()`; on contention it prints
  "tea-clipper is already running." to stderr and `return 1`; success releases in a `finally`. The
  lock is **shared** across both entrypoints, so GUI+daemon also can't coexist.
- Exit codes when blocked: **GUI → 0** (it raised the existing window), **daemon → 1**.
- Suite **109 passing** (`.venv/bin/pytest`). Final whole-branch review: ready to merge (no
  Critical/Important; two minor findings fixed — callback guard + test-socket isolation).
- ⏳ **Hardware verification pending** (needs two real launches on the KDE box): (1) launch the GUI
  twice → the 2nd raises the 1st's window and exits 0; (2) GUI-then-daemon and daemon-then-GUI →
  the 2nd is blocked and opens no second portal session. **Not merged to `main`.**

## NEXT SESSION — handoff

**State:** **feature-complete**, suite **101 passing** (`.venv/bin/pytest`). Two post-`v0.1.0`
features — **UI feedback** (toast + record-state sync) and **startup update check** — are merged
to **local `main`** and **hardware-verified** (see their status sections above). ⚠️ **Local `main`
is ahead of `origin/main` (`2062a30`) by these merges and is NOT pushed yet** — push when ready
(first push may need to be interactive via KWallet; see `[[git-auth-kwallet]]`). The released tag
is still `v0.1.0`; bump + re-tag if these go out as a release. Runs from a checkout
(`python -m tea_clipper.ui` / `python -m tea_clipper`).

**NEXT SESSION — planned work (two features):**
1. **Microphone volume gate (noise gate).** Add a gate on the mic branch so quiet background noise
   below a threshold is silenced. The mic enters the pipeline in `audio.build_audio_fragment` (one
   `pipewiresrc target-object=<mic> … ! amix.` chain per device, mixed via `audiomixer name=amix`).
   GStreamer ships no stock noise-gate element, so the likely approach is the **`audiodynamic`**
   element in `mode=cutoff` (a downward gate that zeroes signal below `threshold`) inserted on the
   mic chain before `amix.`, with the threshold exposed as a `Settings` field (and a UI control).
   Brainstorm first (element choice + whether the gate is mic-only or post-mix; default mic-only).
2. ~~**Single-instance lock.**~~ — **DONE** on the `single-instance` branch (flock lock +
   Qt local-socket window-raise; see "Status — single-instance lock" above). **Remaining: hardware-
   verify the two-launch behavior on the KDE box, then merge `single-instance` → `main`.**

**Other candidate work (lower priority):** finish the AUR push (below); a `tea-clipper-git` VCS
package; remaining deferred polish (below).

**AUR submission — prepared & standards-audited, push pending:** a ready-to-push AUR repo lives at
`~/Projects/aur-tea-clipper/` (`PKGBUILD` + generated `.SRCINFO` + 0BSD `LICENSE` + `.gitignore`,
committed on `master`; remote `ssh://aur@aur.archlinux.org/tea-clipper.git`; name is free on AUR).
An ed25519 deploy key was generated at `~/.ssh/aur` (+ `~/.ssh/config` host entry). **Remaining
(user-only):** register `~/.ssh/aur.pub` on the AUR account, then `cd ~/Projects/aur-tea-clipper
&& git push -u origin master`. On a future `pkgver` bump: edit `PKGBUILD`, `updpkgsums`, `makepkg --printsrcinfo >
.SRCINFO`, commit, push.

**Deferred polish (optional, YAGNI):**
- ~~Window Record button doesn't sync when recording is toggled via hotkey/tray~~ — **done**
  on the `ui-feedback` branch (see "Status — UI feedback" above).
- "Configure shortcuts…" launches `systemsettings`; could instead call the GlobalShortcuts
  portal's `ConfigureShortcuts` D-Bus method through `HotkeyService`.
- In-app log viewer; multi-monitor source picker; per-setting live apply (no restart).

**Gotchas worth remembering:**
- `pipewiresrc` has cold-start latency — a clip saved within the first few seconds of launch is
  short because the buffer isn't full yet. Irrelevant once it's been running a while.
- Engine/portal/hotkey/audio real-D-Bus & device-enumeration code is **not** unit-tested (can't
  run headlessly); it's verified by the `*_probe.py` scripts and `python -m tea_clipper`. Keep
  that split — unit-test the pure/orchestration logic with fakes, probe the rest on hardware.
- Audio default-device detection shells out to `pactl` (PipeWire's PulseAudio-compat CLI) — a
  runtime dep in the same spirit as the `ffmpeg` subprocess and the `gst-plugins-good` requirement.
  It degrades gracefully if absent (the `@desktop@`/`@mic@` tokens just resolve to nothing).
- UI threading: never call `build_controller()` / `EngineHost.start()` on the Qt main thread — it
  blocks on portal negotiation. The engine lives on the worker thread; touch Qt widgets only from
  the main thread and the engine only via `EngineHost` (which marshals both ways).
- Git push auth on this machine goes through KWallet (see agent memory `git-auth-kwallet`); first
  push for a new token must be interactive.
