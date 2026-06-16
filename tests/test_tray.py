from pathlib import Path

from PySide6.QtCore import QObject, Signal

from tea_clipper.settings import Settings
from tea_clipper.ui.tray import TrayIcon


class _Sig(QObject):
    state_changed = Signal(str, str)
    clip_saved = Signal(str)
    recording_changed = Signal(bool)


class FakeHost:
    def __init__(self):
        self._sig = _Sig()
        self.state_changed = self._sig.state_changed
        self.clip_saved = self._sig.clip_saved
        self.recording_changed = self._sig.recording_changed
        self.state = "Recording"

    def save_clip(self):
        pass

    def toggle_record(self):
        pass


def test_clip_saved_raises_toast(qapp, monkeypatch, tmp_path):
    host = FakeHost()
    window = object()  # tray only calls window methods on user interaction
    tray = TrayIcon(host, window, Settings(output_dir=str(tmp_path)))
    messages = []
    monkeypatch.setattr(tray, "showMessage", lambda title, body, *a, **k: messages.append((title, body)))
    host.clip_saved.emit(str(Path(tmp_path) / "clip_x.mkv"))
    assert messages == [("Clip saved", "clip_x.mkv")]


def test_recording_started_toast_and_label(qapp, monkeypatch, tmp_path):
    host = FakeHost()
    tray = TrayIcon(host, object(), Settings(output_dir=str(tmp_path)))
    messages = []
    monkeypatch.setattr(tray, "showMessage", lambda title, body, *a, **k: messages.append((title, body)))
    host.recording_changed.emit(True)
    assert ("tea-clipper", "Recording started") in messages
    assert tray._record_action.text() == "Stop recording"
    messages.clear()
    host.recording_changed.emit(False)
    assert messages == []                      # no toast on stop (clip_saved covers it)
    assert tray._record_action.text() == "Start recording"
