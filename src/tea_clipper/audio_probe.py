"""Manual real-hardware probe: list capturable audio devices.

Run on the KDE/Wayland target:  .venv/bin/python -m tea_clipper.audio_probe
Put the printed node.name strings (or @desktop@ / @mic@) into audio_devices in your config.
"""

from __future__ import annotations

import sys

from tea_clipper.audio import discover_audio_devices


def main(argv: list[str] | None = None) -> int:
    devices = discover_audio_devices()
    if not devices:
        print("No audio devices found.")
        return 1

    print(f"Found {len(devices)} audio device(s):\n")
    for d in devices:
        kind = "desktop" if d.is_monitor else "mic"
        default = " [default]" if d.is_default else ""
        print(f"  {d.node_name}")
        print(f"      {d.display_name}  ({kind}){default}")
    print(
        "\nPut node.name strings (or the @desktop@ / @mic@ tokens) into "
        "audio_devices in your config."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
