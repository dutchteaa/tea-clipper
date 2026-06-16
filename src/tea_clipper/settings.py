"""User-configurable settings with TOML persistence."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import tomli_w


@dataclass
class Settings:
    clip_length_seconds: int = 30
    codec: str = "h264"            # "h264" | "hevc" | "av1"
    hardware: bool = True          # prefer VAAPI; fall back to software
    bitrate_kbps: int = 30000
    fps: int = 60
    segment_seconds: int = 2       # rolling-buffer segment granularity
    audio_devices: list[str] = field(default_factory=lambda: ["@desktop@", "@mic@"])
    output_dir: str = field(default_factory=lambda: str(Path.home() / "Videos" / "tea-clipper"))
    buffer_dir: str = field(default_factory=lambda: str(Path.home() / ".cache" / "tea-clipper" / "buffer"))
    source_restore_token: str = ""
    skipped_update_version: str = ""   # release tag the user chose to skip

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            tomli_w.dump(asdict(self), fh)

    @classmethod
    def load(cls, path: Path) -> "Settings":
        path = Path(path)
        if not path.exists():
            return cls()
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
