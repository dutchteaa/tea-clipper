"""Wire QApplication + EngineHost + MainWindow + TrayIcon; python -m tea_clipper.ui."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tea_clipper.settings import Settings
from tea_clipper.ui.engine_host import EngineHost
from tea_clipper.ui.icons import app_icon
from tea_clipper.ui.main_window import MainWindow
from tea_clipper.ui.tray import TrayIcon


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = Path.home() / ".config" / "tea-clipper" / "config.toml"
    settings = Settings.load(config)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("tea-clipper")
    app.setApplicationDisplayName("tea-clipper")
    app.setDesktopFileName("tea-clipper")  # ties window/tray to a stable app identity
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)  # closing the window hides to tray

    host = EngineHost(settings, config)
    window = MainWindow(host, settings)
    tray = TrayIcon(host, window, settings)
    tray.show()
    window.show()

    host.start()  # auto-start capture (picker may appear the first time)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
