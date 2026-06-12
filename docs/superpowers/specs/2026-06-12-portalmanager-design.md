# PortalManager Design — Real Screen Capture via xdg-desktop-portal

**Date:** 2026-06-12
**Status:** Approved (user delegated detailed decisions)
**Follows:** the engine-core plan (`docs/superpowers/plans/2026-06-12-engine-core.md`), which
deferred real `pipewiresrc` capture to this plan.

## Goal

Replace the headless `test_source_bin()` video source with **real monitor capture**
negotiated through `org.freedesktop.portal.ScreenCast`. `PortalManager` performs the D-Bus
handshake, obtains a live PipeWire stream (fd + node id), and returns a `pipewiresrc`
launch fragment that `CapturePipeline` consumes exactly like the test source today. The
result is a real on-screen clip produced end-to-end, proven by a runnable probe script.

## Scope

**In scope**
- `PortalManager` — ScreenCast session negotiation, monitor selection (via the portal's own
  picker), persistent restore-token reuse, PipeWire fd handoff, clean teardown.
- A small change to `CapturePipeline` to make the **audio branch optional** (video-only).
- `portal_probe` — a runnable script (`python -m tea_clipper.portal_probe`) that opens the
  portal, captures a few seconds, saves a clip, and tears down. The real-hardware proof.
- Mocked unit tests for the negotiation/orchestration logic.

**Out of scope (deferred to later plans)**
- Desktop + microphone audio capture/mixing (`audiomixer` of PipeWire sources).
- `HotkeyService` (GlobalShortcuts portal), `Controller`, and the PySide6 UI.
- Window/virtual source types — monitor capture only.

## Decisions

- **D-Bus access:** `gi.repository.Gio` (GDBus), already available via PyGObject — no new
  dependency. Full control over the unix-fd passing that `OpenPipeWireRemote` requires.
- **Audio:** video-only for this plan; the pipeline's audio branch becomes optional.
- **Source type:** `MONITOR` only.
- **Cursor:** embedded (`cursor_mode = 2`) so the pointer appears in clips.
- **Restore token:** request `persist_mode = 2` (persistent). Reuse
  `Settings.source_restore_token` when present; write the fresh token back onto the
  `Settings` instance. Persisting to disk is the caller's responsibility (the probe does it).
- **Testing:** mock the raw D-Bus layer; verify real capture with the committed probe script.

## Architecture

```
PortalManager.open()
  └─ ScreenCastPortal (thin Gio/GDBus wrapper)
       CreateSession ──► SelectSources(MONITOR, cursor=embedded,
                                       persist_mode=2, restore_token?) ──► Start (picker)
       └─ streams[0] -> node_id ;  results['restore_token'] -> saved to Settings
       OpenPipeWireRemote ──► unix fd
  returns:  "pipewiresrc fd=<fd> path=<node_id> ! videoconvert ! queue name=venc_in"

CapturePipeline(source_desc=(that_fragment, None), ...)   # audio branch omitted
```

### Components

**`ScreenCastPortal` (raw D-Bus, hardware-verified only)** — a thin wrapper over a
`Gio.DBusConnection` to `org.freedesktop.portal.Desktop`. One method per portal step:
`create_session()`, `select_sources(session, opts)`, `start(session, parent)`,
`open_pipewire_remote(session) -> int (fd)`. Each portal call returns a `Request` object
path; the wrapper subscribes to its `Response` signal and blocks on a short-lived private
`GLib.MainLoop` until it fires, translating the `(response_code, results)` into a return
value or raised error. `open_pipewire_remote` uses
`call_with_unix_fd_list_sync` to receive the fd.

**`PortalManager` (orchestration, unit-tested)** — sequences the four steps, threads the
restore token in/out of `Settings`, parses `streams` to the node id, assembles the
`pipewiresrc` fragment, and keeps the session handle + fd alive until `close()`. It talks
only to a `ScreenCastPortal` collaborator, which tests substitute with a fake — so all
orchestration logic is testable without real D-Bus.

**`CapturePipeline` change** — `source_desc` becomes `tuple[str, str | None]`. When the
audio fragment is `None`, the launch string omits the `opusenc ! replaymux.audio_0` branch
(video-only). `test_source_bin()` still returns `(video, audio)`, so existing engine tests
are unchanged and still exercise the audio path.

**`portal_probe` (`src/tea_clipper/portal_probe.py`, `__main__`)** — wires
`PortalManager → CapturePipeline → ReplayBuffer`: open the portal, run ~6s into a temp
buffer dir, `save_last(5, out, pipeline)`, print the clip path, `stop()` + `close()`,
persist the (possibly new) restore token via `Settings.save`. Run by hand on real hardware.

## Data flow

1. `PortalManager.open()` reads `settings.source_restore_token` (may be empty).
2. `CreateSession` → session handle.
3. `SelectSources` with `types=1` (MONITOR), `cursor_mode=2`, `persist_mode=2`, and
   `restore_token` if non-empty.
4. `Start("")` → the portal shows the picker (skipped if a valid restore token let it
   auto-restore). `results` yields `streams` (`a(ua{sv})`) and possibly `restore_token`.
5. Save `restore_token` back onto `settings`; take `streams[0]` node id.
6. `OpenPipeWireRemote` → fd (kept open).
7. Build and return the `pipewiresrc` fragment.
8. Capture runs. `close()` closes the fd and calls `Session.Close`.

## Error handling

A small exception hierarchy in `portal.py`:

- `PortalError` — base.
- `PortalUnavailableError` — `org.freedesktop.portal.Desktop` not on the bus.
- `PortalCancelledError` — user dismissed the picker (`Response` code 1).
- `PortalFailedError` — portal reported failure (code 2) or returned no streams.

An expired/invalid restore token is not an error: the portal simply ignores it and shows
the picker, producing a fresh token. Callers (probe; later the Controller/UI) surface these
as messages rather than crashing, consistent with the project's "surface failures" rule.

## Testing

**Unit (`tests/test_portal.py`, runs in CI, no real portal):**
- Injects a fake `ScreenCastPortal` into `PortalManager`.
- Asserts `SelectSources` options: `types` has the MONITOR bit, `persist_mode == 2`,
  `restore_token` passed only when `settings.source_restore_token` is non-empty.
- Asserts the returned fragment is `pipewiresrc fd=<fd> path=<node> ! ...` for canned
  fd/node values.
- Asserts a fresh `restore_token` in the Start results is written back to `settings`.
- Asserts `Response` code 1 → `PortalCancelledError`; code 2 / empty streams →
  `PortalFailedError`.

**Pipeline unit (extend existing):**
- A video-only `source_desc=(videotestsrc-fragment, None)` builds and runs, producing
  segments with a video track only (engine-marked; reuses the existing harness).

**Manual (`portal_probe`):** run on the KDE/Wayland target; confirm the picker appears
(first run), a clip is written with a real video track, and a second run reuses the token
without prompting.

## File structure

```
src/tea_clipper/portal.py          # PortalManager + ScreenCastPortal + exceptions
src/tea_clipper/portal_probe.py    # __main__ real-hardware probe
src/tea_clipper/pipeline.py        # MODIFIED: optional audio branch
tests/test_portal.py               # mocked orchestration tests
tests/test_pipeline_integration.py # MODIFIED: video-only build test
```
