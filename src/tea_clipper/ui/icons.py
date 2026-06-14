"""Shared application icon resolution.

KDE shows a generic placeholder when no themed icon / desktop association exists.
We prefer a freedesktop theme icon (present on KDE), falling back to a Qt standard
pixmap so the tray + window always have a real glyph.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle

_THEME_NAMES = ("media-record", "camera-video", "media-playback-start")


def app_icon() -> QIcon:
    for name in _THEME_NAMES:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
