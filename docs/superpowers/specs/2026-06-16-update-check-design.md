# Startup update check (GitHub Releases) — design

**Date:** 2026-06-16
**Status:** Approved (brainstorming)
**Repository:** https://github.com/dutchteaa/tea-clipper

## Goal

On GUI launch, check GitHub for a newer release of tea-clipper. If one exists, show a
dialog listing what's new and offer to open the release page in the browser. Honor a
"skip this version" choice so the same update never nags the user twice.

## Context & constraints

- tea-clipper is intended for AUR distribution, where updates normally come through the
  package manager (`paru`/`yay`), **not** the app. The AUR package is **not published
  yet** (AUR registration is currently disabled), so GitHub Releases is the fallback
  source for now. The app today runs either from a git checkout
  (`python -m tea_clipper.ui`) or installed via `makepkg -si` from the repo.
- Because of the above, the checker **only notifies** — it never downloads, installs, or
  runs git/pacman. "Update" means *open the GitHub release page* so the user reads the
  notes and updates however they installed.
- Scope is deliberately small (CLAUDE.md: "Resist scope creep — YAGNI").
- UI threading rule (CLAUDE.md): Qt owns the main thread; blocking work runs off it. The
  network call must not block the Qt main thread.

## Behavior

1. GUI starts (`python -m tea_clipper.ui`), window + tray come up, capture auto-starts.
2. Shortly after, a background worker fetches the latest GitHub release.
3. If the latest release is **newer** than the running version **and** is not the
   version the user previously skipped, a `QMessageBox` appears:
   - Title/text: new version number + the release notes (the GitHub release `body`,
     i.e. "what's new").
   - Buttons: **Update** (opens the release page), **Skip this version** (persists the
     skip + dismisses), **Not now** (dismisses; will prompt again next launch).
4. Any failure (offline, timeout, GitHub error, parse error) is **silent** — logged at
   debug level, no dialog, no crash.
5. The headless daemon (`python -m tea_clipper`) is untouched — no UI, no check.

## Components

### 1. `src/tea_clipper/update_check.py` (new)

Pure / I/O-isolated logic, independent of Qt so it is unit-testable.

- `CURRENT_VERSION: str` — single source of truth for the running version. Derived from
  `tea_clipper.__version__`, with an `importlib.metadata.version("tea-clipper")` fallback
  for installed packages. (See "Version source of truth" below.)
- `parse_version(text: str) -> tuple[int, ...]` — parse `"v0.1.0"` / `"0.1.0"` into a
  comparable tuple of ints; tolerate a leading `v` and trailing junk; return `(0,)` or
  similar sentinel on unparseable input rather than raising.
- `@dataclass UpdateInfo` — `version: str`, `notes: str`, `url: str`.
- `fetch_latest_release(repo: str = "dutchteaa/tea-clipper", timeout: float = 5.0)
  -> UpdateInfo | None` — GET
  `https://api.github.com/repos/<repo>/releases/latest` via stdlib `urllib.request`
  (no new dependency). On success, build `UpdateInfo(version=tag_name, notes=body,
  url=html_url)`. On **any** exception (network, HTTP error, JSON/key error) return
  `None`. Sends a `User-Agent` header (GitHub API requires one) and `Accept:
  application/vnd.github+json`.
- `is_newer(latest: str, current: str) -> bool` — pure; `parse_version(latest) >
  parse_version(current)`.
- `should_prompt(latest: str, current: str, skipped: str) -> bool` — `is_newer(latest,
  current) and latest != skipped`. (Compared on the raw tag string for the skip check so
  an exact "skip this tag" is honored; `is_newer` does the numeric comparison.)

### 2. `src/tea_clipper/settings.py` — one new field

- `skipped_update_version: str = ""` on the `Settings` dataclass.
- `Settings.load` already filters unknown keys, so existing configs are forward-compatible
  with no migration. The field is written (and `Settings.save`d) when the user clicks
  "Skip this version".

### 3. `src/tea_clipper/__init__.py` — version fix

`__version__` is currently `"0.0.1"` while `pyproject.toml` is `"0.1.0"`. Update
`__version__` to `"0.1.0"` so it matches the package version, and treat it as the source
of truth the update check derives `CURRENT_VERSION` from. (A short note will be added near
the version in `pyproject.toml`/`__init__.py` reminding to bump both together; full
single-sourcing of the version is out of scope here.)

### 4. UI wiring

A small worker + handler, kept out of the hot path and off the main thread.

- A `QThread`-based (or `QRunnable`/`QThreadPool`) worker runs `fetch_latest_release` and
  emits a Qt signal with the `UpdateInfo | None` result back on the main thread. This
  mirrors the existing "engine on a worker thread, Qt updates marshalled back as signals"
  pattern; the update worker is much simpler (one call, one result) and does not touch the
  engine.
- `app.py` starts the check after the window/tray are shown and `host.start()` is called.
  It passes the current `Settings` (for `skipped_update_version`) and the config `Path`
  (to persist a skip).
- On result: if `result is not None and should_prompt(result.version, CURRENT_VERSION,
  settings.skipped_update_version)`, show a `QMessageBox` with the version + notes and the
  three buttons. Handle the chosen action:
  - **Update** → `QDesktopServices.openUrl(QUrl(result.url))`.
  - **Skip this version** → `settings.skipped_update_version = result.version;
    settings.save(config)`.
  - **Not now** → no-op.
- The dialog/worker code lives in a small UI helper (e.g.
  `src/tea_clipper/ui/update_prompt.py`) so `app.py` stays a thin wiring layer.

## Version source of truth

`CURRENT_VERSION` resolution order:
1. `tea_clipper.__version__` (works from a checkout and when installed).
2. Fallback to `importlib.metadata.version("tea-clipper")` if `__version__` is somehow
   missing.

`__version__` is bumped to `0.1.0` as part of this work so it agrees with
`pyproject.toml`.

## Error handling

- Network/HTTP/parse failures in `fetch_latest_release` → return `None`, logged at debug.
- The UI never shows an error dialog for a failed check — a missed check is a non-event.
- Malformed/missing version strings → `parse_version` returns a sentinel low tuple; the
  comparison simply treats it as not-newer rather than raising.

## Testing

Consistent with the project's split — unit-test pure/orchestration logic with fakes; the
live GitHub call and the real dialog are manually verified, not in CI.

Unit tests (`tests/test_update_check.py`):
- `parse_version` — `"v0.1.0"`, `"0.1.0"`, `"1.2"`, junk → sentinel.
- `is_newer` — older/equal/newer across patch/minor/major; `v`-prefix tolerance.
- `should_prompt` — newer+unskipped → True; newer+skipped → False; equal/older → False.
- `fetch_latest_release` — parse a sample GitHub `releases/latest` JSON into `UpdateInfo`
  (monkeypatch `urllib.request.urlopen` / inject a fake opener); the error path returns
  `None` (raise inside the fake → `None`).
- `Settings` round-trip includes `skipped_update_version` (extend the existing settings
  test).

Manually verified (not CI):
- Real GitHub fetch against the live repo.
- The `QMessageBox` appears with notes and the three buttons behave (open page / persist
  skip / dismiss). Skipping a version suppresses it on next launch; a newer release still
  prompts.

## Out of scope (YAGNI)

- Self-install, git pull, or any package-manager invocation.
- Aggregating notes across multiple missed releases — only the latest release is shown.
- Checking in the headless daemon.
- A configurable check interval, "check now" button, or disabling the check via UI
  (can be added later if asked; the data field already allows a permanent skip of a
  version).
- Full single-sourcing of the version between `pyproject.toml` and `__init__.py`.
