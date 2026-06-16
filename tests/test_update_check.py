import io
import urllib.request

from tea_clipper.update_check import (
    UpdateInfo,
    fetch_latest_release,
    is_newer,
    parse_version,
    should_prompt,
)


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
