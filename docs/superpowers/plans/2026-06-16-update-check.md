# Startup Update Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On GUI launch, check GitHub Releases for a newer version and, if found, show a `QMessageBox` with the release notes and an "open release page" / "skip this version" / "not now" choice.

**Architecture:** A pure/IO-isolated `update_check` module fetches the latest release via stdlib `urllib` (no new dependency) and exposes pure version-comparison helpers. A small UI helper runs the fetch on a `QThread` worker (off the Qt main thread) and shows the dialog on the result. A new `Settings.skipped_update_version` field persists a per-version skip.

**Tech Stack:** Python 3.12, stdlib `urllib.request` + `json`, PySide6 (`QThread`, `QMessageBox`, `QDesktopServices`), pytest.

Spec: `docs/superpowers/specs/2026-06-16-update-check-design.md`

---

### Task 1: Sync the version source of truth

**Files:**
- Modify: `src/tea_clipper/__init__.py`

- [ ] **Step 1: Update `__version__` to match `pyproject.toml`**

`src/tea_clipper/__init__.py` currently reads `__version__ = "0.0.1"` while
`pyproject.toml` is `0.1.0`. Change the line to:

```python
"""tea-clipper: instant-replay game clipper for Linux/Wayland."""

__version__ = "0.1.0"  # keep in sync with pyproject.toml [project].version
```

- [ ] **Step 2: Verify it imports**

Run: `.venv/bin/python -c "import tea_clipper; print(tea_clipper.__version__)"`
Expected: prints `0.1.0`

- [ ] **Step 3: Commit**

```bash
git add src/tea_clipper/__init__.py
git commit -m "fix: bump __version__ to 0.1.0 to match pyproject"
```

---

### Task 2: `Settings.skipped_update_version` field

**Files:**
- Modify: `src/tea_clipper/settings.py:23` (add field after `source_restore_token`)
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings.py`:

```python
def test_skipped_update_version_default_is_empty():
    assert Settings().skipped_update_version == ""


def test_skipped_update_version_round_trip(tmp_path: Path):
    s = Settings(skipped_update_version="v0.2.0")
    cfg = tmp_path / "config.toml"
    s.save(cfg)
    assert Settings.load(cfg).skipped_update_version == "v0.2.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_settings.py::test_skipped_update_version_default_is_empty -v`
Expected: FAIL — `TypeError`/`AttributeError` (field doesn't exist).

- [ ] **Step 3: Add the field**

In `src/tea_clipper/settings.py`, add after the `source_restore_token` line:

```python
    source_restore_token: str = ""
    skipped_update_version: str = ""   # release tag the user chose to skip
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_settings.py -v`
Expected: PASS (all settings tests, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/settings.py tests/test_settings.py
git commit -m "feat: add Settings.skipped_update_version"
```

---

### Task 3: `update_check` pure version helpers

**Files:**
- Create: `src/tea_clipper/update_check.py`
- Test: `tests/test_update_check.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_update_check.py`:

```python
from tea_clipper.update_check import parse_version, is_newer, should_prompt


def test_parse_version_strips_v_prefix():
    assert parse_version("v0.1.0") == (0, 1, 0)
    assert parse_version("0.1.0") == (0, 1, 0)


def test_parse_version_tolerates_short_and_junk():
    assert parse_version("1.2") == (1, 2)
    assert parse_version("garbage") == (0,)
    assert parse_version("") == (0,)


def test_is_newer():
    assert is_newer("v0.2.0", "0.1.0") is True
    assert is_newer("0.1.1", "0.1.0") is True
    assert is_newer("0.1.0", "0.1.0") is False
    assert is_newer("0.0.9", "0.1.0") is False


def test_should_prompt_newer_and_not_skipped():
    assert should_prompt("v0.2.0", "0.1.0", "") is True


def test_should_prompt_false_when_skipped():
    assert should_prompt("v0.2.0", "0.1.0", "v0.2.0") is False


def test_should_prompt_false_when_not_newer():
    assert should_prompt("0.1.0", "0.1.0", "") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_update_check.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tea_clipper.update_check'`.

- [ ] **Step 3: Write the module (pure helpers only)**

Create `src/tea_clipper/update_check.py`:

```python
"""Check GitHub Releases for a newer tea-clipper and model the result."""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass

from tea_clipper import __version__ as CURRENT_VERSION

log = logging.getLogger("tea_clipper")

_REPO = "dutchteaa/tea-clipper"


def parse_version(text: str) -> tuple[int, ...]:
    """Parse 'v0.1.0' / '0.1.0' into a comparable int tuple; (0,) on junk."""
    if not text:
        return (0,)
    cleaned = text.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits == "":
            break
        parts.append(int(digits))
    return tuple(parts) if parts else (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def should_prompt(latest: str, current: str, skipped: str) -> bool:
    return is_newer(latest, current) and latest != skipped


@dataclass
class UpdateInfo:
    version: str
    notes: str
    url: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_update_check.py -v`
Expected: PASS (the six pure-logic tests).

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/update_check.py tests/test_update_check.py
git commit -m "feat: update_check pure version helpers + UpdateInfo"
```

---

### Task 4: `fetch_latest_release` (network, error→None)

**Files:**
- Modify: `src/tea_clipper/update_check.py`
- Test: `tests/test_update_check.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_update_check.py`:

```python
import io
import urllib.request

from tea_clipper import update_check
from tea_clipper.update_check import UpdateInfo, fetch_latest_release

_SAMPLE = b"""
{"tag_name": "v0.2.0",
 "html_url": "https://github.com/dutchteaa/tea-clipper/releases/tag/v0.2.0",
 "body": "## What's new\\n- Toasts\\n- Update check"}
"""


def test_fetch_latest_release_parses_json(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return io.BytesIO(_SAMPLE)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    info = fetch_latest_release()
    assert info == UpdateInfo(
        version="v0.2.0",
        notes="## What's new\n- Toasts\n- Update check",
        url="https://github.com/dutchteaa/tea-clipper/releases/tag/v0.2.0",
    )


def test_fetch_latest_release_returns_none_on_error(monkeypatch):
    def boom(req, timeout=None):
        raise OSError("no network")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert fetch_latest_release() is None


def test_fetch_latest_release_returns_none_on_bad_json(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(b"not json")
    )
    assert fetch_latest_release() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_update_check.py -k fetch -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_latest_release'`.

- [ ] **Step 3: Implement `fetch_latest_release`**

Append to `src/tea_clipper/update_check.py`:

```python
def fetch_latest_release(repo: str = _REPO, timeout: float = 5.0) -> UpdateInfo | None:
    """GET the latest GitHub release. Return None on any network/parse failure."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "tea-clipper-update-check",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return UpdateInfo(
            version=data["tag_name"],
            notes=data.get("body") or "",
            url=data["html_url"],
        )
    except Exception:
        log.debug("update check failed", exc_info=True)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_update_check.py -v`
Expected: PASS (all nine tests).

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/update_check.py tests/test_update_check.py
git commit -m "feat: fetch_latest_release via GitHub API (error-safe)"
```

---

### Task 5: UI helper — worker + dialog

**Files:**
- Create: `src/tea_clipper/ui/update_prompt.py`
- Test: `tests/test_update_prompt.py`

The worker runs `fetch_latest_release` off the Qt main thread and emits the result; a
free function decides whether to prompt and (if so) shows the dialog. The decision +
skip-persistence logic is split out as a pure function so it is unit-testable without a
real `QMessageBox`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_update_prompt.py`:

```python
from tea_clipper.settings import Settings
from tea_clipper.update_check import UpdateInfo
from tea_clipper.ui.update_prompt import decide_update_action


def test_decide_skips_when_not_newer():
    s = Settings()  # current version is tea_clipper.__version__
    info = UpdateInfo(version="0.0.1", notes="", url="x")
    assert decide_update_action(info, s) == "ignore"


def test_decide_prompts_when_newer():
    s = Settings()
    info = UpdateInfo(version="v999.0.0", notes="notes", url="x")
    assert decide_update_action(info, s) == "prompt"


def test_decide_ignores_skipped_version():
    s = Settings(skipped_update_version="v999.0.0")
    info = UpdateInfo(version="v999.0.0", notes="notes", url="x")
    assert decide_update_action(info, s) == "ignore"


def test_decide_ignores_none():
    assert decide_update_action(None, Settings()) == "ignore"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_update_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tea_clipper.ui.update_prompt'`.

- [ ] **Step 3: Implement the helper**

Create `src/tea_clipper/ui/update_prompt.py`:

```python
"""Background update check + dialog for the GUI (python -m tea_clipper.ui)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from tea_clipper.update_check import (
    CURRENT_VERSION,
    UpdateInfo,
    fetch_latest_release,
    should_prompt,
)


def decide_update_action(info: UpdateInfo | None, settings) -> str:
    """'prompt' if a newer, un-skipped release exists; else 'ignore'. Pure."""
    if info is None:
        return "ignore"
    if should_prompt(info.version, CURRENT_VERSION, settings.skipped_update_version):
        return "prompt"
    return "ignore"


class _FetchWorker(QObject):
    done = Signal(object)  # UpdateInfo | None

    def run(self) -> None:
        self.done.emit(fetch_latest_release())


class UpdateChecker(QObject):
    """Run the fetch on a worker thread; show the dialog on the main thread."""

    def __init__(self, settings, config_path, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._config_path = Path(config_path)
        self._thread = QThread()
        self._worker = _FetchWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)

    def start(self) -> None:
        self._thread.start()

    def _on_done(self, info) -> None:
        self._thread.quit()
        if decide_update_action(info, self._settings) == "prompt":
            self._show_dialog(info)

    def _show_dialog(self, info: UpdateInfo) -> None:
        box = QMessageBox()
        box.setWindowTitle("tea-clipper update available")
        box.setText(f"A new version is available: {info.version}")
        box.setInformativeText(info.notes or "See the release page for details.")
        update = box.addButton("Update", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is update:
            QDesktopServices.openUrl(QUrl(info.url))
        elif clicked is skip:
            self._settings.skipped_update_version = info.version
            self._settings.save(self._config_path)
```

Note: import `CURRENT_VERSION` requires it be exported from `update_check`; it already is
(`from tea_clipper import __version__ as CURRENT_VERSION` in Task 3).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_update_prompt.py -v`
Expected: PASS (the four decision tests; they need the `qapp` fixture only if a
`QApplication` is required — `decide_update_action` is pure and does not, but importing the
module pulls in PySide6, which the offscreen `qapp` conftest fixture already supports).

If import-time needs a QApplication, add `qapp` as a parameter to each test (the fixture
exists in `tests/conftest.py`, used by `test_engine_host.py`).

- [ ] **Step 5: Commit**

```bash
git add src/tea_clipper/ui/update_prompt.py tests/test_update_prompt.py
git commit -m "feat: UpdateChecker worker + dialog + decide_update_action"
```

---

### Task 6: Wire the check into the GUI entrypoint

**Files:**
- Modify: `src/tea_clipper/ui/app.py:30-37`

- [ ] **Step 1: Wire `UpdateChecker` into `main()`**

In `src/tea_clipper/ui/app.py`, add the import near the other UI imports:

```python
from tea_clipper.ui.update_prompt import UpdateChecker
```

Then, after `host.start()` (and before `return app.exec()`), start the check. Keep a
reference so it isn't garbage-collected before the worker finishes:

```python
    host.start()  # auto-start capture (picker may appear the first time)

    updater = UpdateChecker(settings, config)
    updater.start()
    app._tea_updater = updater  # keep a reference alive for the app's lifetime

    return app.exec()
```

- [ ] **Step 2: Verify the module imports and the suite still passes**

Run: `.venv/bin/python -c "import tea_clipper.ui.app"`
Expected: no error.

Run: `.venv/bin/pytest`
Expected: PASS (full unit suite, now including the new update tests).

- [ ] **Step 3: Commit**

```bash
git add src/tea_clipper/ui/app.py
git commit -m "feat: run startup update check in the GUI entrypoint"
```

---

### Task 7: Manual hardware verification (not CI)

**Files:** none (verification only).

- [ ] **Step 1: Run the GUI and observe**

Run: `.venv/bin/python -m tea_clipper.ui`

Expected: the window/tray come up and capture starts as before. With `__version__`
`0.1.0` and the published GitHub release being `v0.1.0`, `should_prompt` is False, so **no
dialog** appears (correct — you're up to date). Confirm there is no error in the logs and
the app is unaffected.

- [ ] **Step 2: Force the prompt to verify the dialog**

Temporarily set `__version__ = "0.0.1"` in `src/tea_clipper/__init__.py`, re-run
`.venv/bin/python -m tea_clipper.ui`, and confirm: the dialog appears with the `v0.1.0`
notes; "Update" opens the release page in the browser; "Skip this version" writes
`skipped_update_version` into `~/.config/tea-clipper/config.toml` and suppresses the
dialog on the next launch; "Not now" dismisses without persisting. **Revert** the
`__version__` change afterward.

- [ ] **Step 3: Record the result**

Note the verification outcome in `CLAUDE.md` under a new "Status — update check" section
(follow the existing status-section style), then commit.

```bash
git add CLAUDE.md
git commit -m "docs: record update-check hardware verification"
```
