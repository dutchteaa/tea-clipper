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
