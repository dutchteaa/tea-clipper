"""Run tea-clipper as a daemon:  python -m tea_clipper

Opens screen capture (a portal picker appears the first time), keeps the rolling buffer
full, and routes the global hotkeys to save clips / toggle recording. Ctrl-C to quit.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from tea_clipper.controller import build_controller
from tea_clipper.portal import PortalError
from tea_clipper.settings import Settings
from tea_clipper.single_instance import InstanceLock


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Path.home() / ".config" / "tea-clipper" / "config.toml"
    settings = Settings.load(config)

    lock = InstanceLock()
    if not lock.acquire():
        print("tea-clipper is already running.", file=sys.stderr)
        return 1

    try:
        print("Starting screen capture (a picker may appear the first time)...")
        try:
            controller = build_controller(settings)
        except PortalError as exc:
            print(f"Startup failed: {exc}", file=sys.stderr)
            return 1
        settings.save(config)  # persist the (possibly new) restore token

        controller.start()
        print("tea-clipper running. Press your hotkeys to save clips / toggle recording.")
        print(f"Clips are written to {settings.output_dir}. Ctrl-C to quit.")
        try:
            controller.run()
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            controller.stop()
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
