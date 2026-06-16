from tea_clipper.settings import Settings
from tea_clipper.ui.main_window import MainWindow


class FakeHost:
    """Minimal EngineHost stand-in exposing the signals MainWindow connects to."""

    def __init__(self):
        from PySide6.QtCore import QObject, Signal

        class _Sig(QObject):
            state_changed = Signal(str, str)
            clip_saved = Signal(str)
            recording_changed = Signal(bool)

        self._sig = _Sig()
        self.state_changed = self._sig.state_changed
        self.clip_saved = self._sig.clip_saved
        self.recording_changed = self._sig.recording_changed
        self.state = "Recording"
        self.toggles = 0

    def save_clip(self):
        pass

    def toggle_record(self):
        self.toggles += 1


def test_recording_changed_updates_button_without_toggling(qapp):
    host = FakeHost()
    win = MainWindow(host, Settings())
    host.recording_changed.emit(True)
    assert win._record_btn.isChecked() is True
    assert "Stop" in win._record_btn.text()
    assert host.toggles == 0          # programmatic sync must NOT call toggle_record


def test_button_click_requests_toggle(qapp):
    host = FakeHost()
    win = MainWindow(host, Settings())
    win._record_btn.click()
    assert host.toggles == 1
