"""Manual real-hardware probe for global shortcuts.

Run on the KDE/Wayland target:  .venv/bin/python -m tea_clipper.hotkey_probe
If the keys don't fire, bind them in System Settings > Shortcuts, then press them.
"""

from __future__ import annotations

import sys
import time

from tea_clipper.hotkeys import SAVE_CLIP, TOGGLE_RECORD, HotkeyService
from tea_clipper.portal import PortalError


def main(argv: list[str] | None = None) -> int:
    svc = HotkeyService()
    svc.add_listener(SAVE_CLIP, lambda: print("  >> save_clip activated"))
    svc.add_listener(TOGGLE_RECORD, lambda: print("  >> toggle_record activated"))

    print("Registering global shortcuts...")
    try:
        svc.start()
    except PortalError as exc:
        print(f"Portal error: {exc}", file=sys.stderr)
        return 1

    print("Registered. Suggested triggers: Ctrl+Alt+C (save), Ctrl+Alt+R (record).")
    print("If they don't fire, bind them in System Settings > Shortcuts, then press them.")
    print("Listening for 30s...")
    try:
        time.sleep(30)
    finally:
        svc.stop()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
