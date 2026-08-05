# Capture resolution + multiple clip-length hotkeys — design

**Date:** 2026-08-05
**Status:** Approved (brainstorm) → ready for implementation plan

## Problem

Two Medal-parity gaps in tea-clipper's capture settings:

1. **Single clip length.** The instant-replay hotkey (`save_clip`) always saves
   `clip_length_seconds`. Medal's most-used feature is multiple clip-length hotkeys (e.g.
   "save last 15s" vs "save last 60s") bound to different keys.
2. **Native resolution only.** `settings.fps` drives capture rate, but resolution is always
   the monitor's native size. There's no way to downscale (e.g. clip at 1080p from a 1440p
   monitor) to save disk/CPU.

Both are "settings that matter" per the project scope; both are small and share the
`Settings` + `SettingsForm` surface, so they're specified together but implemented as
independent tasks.

## Goals

- Let the user bind **multiple clip-length hotkeys**, each saving a different number of
  seconds, without breaking the existing `save_clip` binding.
- Let the user cap **capture resolution** by target height, preserving aspect ratio, never
  upscaling.
- Backward-compatible settings: old `config.toml` files keep working with sensible defaults.
- Keep the pure/orchestration logic unit-testable with fakes; verify the real
  pipeline/portal paths by hardware probe (existing convention).

## Non-goals (YAGNI)

- No upscaling, no arbitrary `WxH`, no per-game resolution presets — target **height** only.
- No compositor-side key binding from the app (KDE owns bindings; we only suggest a default
  trigger for slot 1, as today).
- No live-apply-without-restart — both settings flow through the existing Apply → restart.
- No editing UI beyond a resolution dropdown and a comma-separated lengths field.

## Settings (data model)

Three new/retained fields on `Settings` (dataclass + TOML). `Settings.load` already drops
unknown keys, so old configs fall back to defaults with no migration:

```python
clip_length_seconds: int = 30        # unchanged — slot 1 (the existing save_clip hotkey)
extra_clip_lengths: list[int] = []   # extra clip slots, positional (slots 2..N)
capture_max_height: int = 0          # 0 = native (no downscale); else target height in px
```

## Feature A — multiple clip-length hotkeys

### Single source of truth

One pure helper in `hotkeys.py` derives the full hotkey set so the portal registration and
the controller's listener wiring cannot drift:

```python
@dataclass(frozen=True)
class ClipHotkey:
    action_id: str        # "save_clip", "save_clip_2", "save_clip_3", ...
    seconds: int
    description: str       # "Save clip (last 30s)"
    preferred_trigger: str # "CTRL+ALT+c" for slot 1; "" for extras

def clip_hotkeys(clip_length_seconds: int, extra_clip_lengths: list[int]) -> list[ClipHotkey]:
    ...
```

- **Slot 1** keeps the existing `save_clip` action id and `CTRL+ALT+c` preferred trigger, so
  no existing KDE binding breaks. Its description becomes dynamic: `"Save clip (last {n}s)"`.
- **Extras** get positional ids `save_clip_2`, `save_clip_3`, … and an **empty**
  preferred trigger (the user binds them in KDE System Settings — the app cannot set
  compositor bindings, consistent with the current model).

### Registration + dispatch

- `build_shortcuts_list(clip_length_seconds, extra_clip_lengths)` builds its
  `a(sa{sv})` payload from `clip_hotkeys(...) + [toggle_record]`.
- `HotkeyService` receives the shortcuts list by injection (built in `build_controller` from
  settings) rather than calling the module-level builder with no args. `TOGGLE_RECORD` is
  unchanged. `HotkeyService` already dispatches per-action-id to registered listeners — no
  change to its dispatch core.
- `Controller.save_clip` gains a `seconds: int | None = None` parameter (defaults to
  `clip_length_seconds`). `Controller.start()` iterates `clip_hotkeys(...)` and registers one
  listener per action id, each bound to its `seconds` via a factory (avoiding the late-binding
  closure trap).

### Buffer sizing

`compute_max_segments(settings)` sizes the rolling buffer from the **longest** slot:

```python
longest = max([settings.clip_length_seconds, *settings.extra_clip_lengths])
return math.ceil(longest / settings.segment_seconds) + 2
```

### Caveats (documented in code + handoff)

- Extra hotkeys ship with no default trigger — user binds them in KDE.
- Ids are positional: reordering `extra_clip_lengths` reassigns durations to existing
  bindings (the KDE binding follows the id, not the duration).
- The longest slot sizes the on-disk buffer (`≈ bitrate × longest_length`).

## Feature B — capture resolution / downscale

### Source size from the portal

`portal.parse_start_results(results)` also extracts the stream **size** when the compositor
provides it in the Start response stream properties, returning
`(node_id, restore_token, size | None)` where `size` is `(width, height)`.

### Pure scaling helper

```python
def compute_scaled_size(src_w: int, src_h: int, max_height: int) -> tuple[int, int] | None:
    """Target (w, h) preserving aspect, or None for no scaling."""
    # None when max_height == 0 (native) or src_h <= max_height (never upscale).
    # else: h = max_height; w = round(src_w * max_height / src_h);
    #       then snap BOTH w and h to the nearest even integer (min 2) —
    #       encoders require even dimensions.
```

### Pipeline fragment

`build_video_fragment(fd, node_id, fps, size=None)` inserts a `videoscale` stage only when
`size` is provided:

```
pipewiresrc fd=… path=… ! videoconvert ! videoscale ! video/x-raw,width=W,height=H
  ! videorate ! video/x-raw,framerate=<fps>/1 ! queue name=venc_in
```

When `size is None` the fragment is exactly today's (no `videoscale`).

### Orchestration

`PortalManager.open()` reads the Start-response size, computes
`compute_scaled_size(src_w, src_h, settings.capture_max_height)`, and passes the result to
`build_video_fragment`. If the portal omitted the size, the computed size is `None` →
**native capture** (feature degrades gracefully rather than guessing).

## UI (`SettingsForm`)

Pure `Settings` ↔ widget mapping, matching the existing form pattern:

- **Max resolution** `QComboBox` → `capture_max_height`: `Native (0)`, `1440p (1440)`,
  `1080p (1080)`, `720p (720)`. Selecting a height ≥ the monitor is harmless (no upscale).
- **Extra clip lengths (s)** `QLineEdit` → `extra_clip_lengths`: comma-separated ints, parsed
  with invalid tokens ignored; rendered back as `"60, 15"`.
- `load`/`collect` continue to preserve fields the form doesn't edit (`segment_seconds`,
  `buffer_dir`, `source_restore_token`, `skipped_update_version`, …).

Both settings take effect through the existing **Apply → `EngineHost.restart`** path: the
controller is rebuilt, so the pipeline picks up the new resolution and `BindShortcuts`
re-runs with the new hotkey set.

## Error handling

- Portal size absent → native capture (logged at debug).
- Bad text in the extra-lengths field → those tokens dropped; the rest kept; never raises.
- `compute_scaled_size` never raises; returns `None` for any no-op/degenerate case.
- Per-hotkey save failures are already caught per-action in `Controller.save_clip` so one bad
  clip never kills the daemon.

## Testing

**Pure unit tests (headless):**
- `compute_scaled_size`: 16:9 (2560×1440→1920×1080), ultrawide (3440×1440→even width),
  native (`max_height=0` → None), no-upscale (`src_h ≤ max_height` → None), even-rounding.
- `clip_hotkeys` / `build_shortcuts_list`: slot-1 identity (id `save_clip`, trigger kept),
  extras get positional ids + empty triggers + dynamic descriptions; empty `extra_clip_lengths`
  reproduces today's list.
- `compute_max_segments`: uses the longest slot.
- `parse_start_results`: with and without a size in the stream props.
- `build_video_fragment`: string assertion with and without `size`.
- `Controller`: registers one listener per length and calls `save_last` with the correct
  seconds (fake replay + pipeline).
- `SettingsForm`: round-trip including the new fields and bad-text parsing (offscreen Qt).
- `Settings`: TOML round-trip + forward-compat (unknown-key drop) with the new fields.

**Hardware probe (not in the automated suite, per convention):**
- A downscaled clip is actually the computed W×H and undistorted (ffprobe).
- An extra-length hotkey, once bound in KDE, saves a clip of ≈ its configured seconds.

## Rollout / task decomposition

Independent tasks (each its own TDD cycle):

1. `Settings` fields + tests (foundation for both).
2. Feature A: `clip_hotkeys`/`build_shortcuts_list` + `HotkeyService` injection + `Controller`
   wiring + `compute_max_segments`.
3. Feature B: `compute_scaled_size` + `parse_start_results` size + `build_video_fragment` +
   `PortalManager.open`.
4. UI: `SettingsForm` resolution dropdown + extra-lengths field.
5. Hardware-probe both on KDE/Wayland.
