from tea_clipper.settings import Settings
from tea_clipper.ui.engine_host import EngineHost


class FakeController:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.saved = 0
        self.toggled = 0

    def start(self):
        self.started = True

    def run(self):          # no real GLib loop in tests
        pass

    def stop(self):
        self.stopped = True

    def save_clip(self):
        self.saved += 1

    def toggle_record(self):
        self.toggled += 1


def _host(tmp_path, builder, **kw):
    cfg = tmp_path / "config.toml"
    return EngineHost(Settings(output_dir=str(tmp_path)), cfg, builder=builder, **kw), cfg


def test_bring_up_success_persists_and_emits(qapp, tmp_path):
    fake = FakeController()
    captured = {}

    def builder(settings, clip_saved_cb=None, recording_changed_cb=None):
        captured["cb"] = clip_saved_cb
        return fake

    host, cfg = _host(tmp_path, builder)
    states = []
    host.state_changed.connect(lambda st, detail: states.append(st))
    host._bring_up()
    assert fake.started
    assert cfg.exists()                       # restore token persisted
    assert host.state == "Recording"
    assert states == ["Starting", "Recording"]
    assert captured["cb"] is not None


def test_bring_up_failure_emits_error(qapp, tmp_path):
    def builder(settings, clip_saved_cb=None, recording_changed_cb=None):
        raise RuntimeError("portal denied")

    host, _cfg = _host(tmp_path, builder)
    seen = []
    host.state_changed.connect(lambda st, detail: seen.append((st, detail)))
    host._bring_up()
    assert host.state == "Error"
    assert ("Error", "portal denied") in seen


def test_clip_saved_cb_reemits_qt_signal(qapp, tmp_path):
    captured = {}

    def builder(settings, clip_saved_cb=None, recording_changed_cb=None):
        captured["cb"] = clip_saved_cb
        return FakeController()

    host, _cfg = _host(tmp_path, builder)
    got = []
    host.clip_saved.connect(got.append)
    host._bring_up()
    captured["cb"]("/tmp/clip_1.mkv")
    assert got == ["/tmp/clip_1.mkv"]


def test_save_and_toggle_dispatch_to_controller(qapp, tmp_path):
    fake = FakeController()
    host, _cfg = _host(
        tmp_path, lambda s, clip_saved_cb=None, recording_changed_cb=None: fake, dispatch=lambda fn: fn()
    )
    host._bring_up()
    host.save_clip()
    host.toggle_record()
    assert fake.saved == 1
    assert fake.toggled == 1


def test_apply_settings_swaps_and_restarts(qapp, tmp_path, monkeypatch):
    host, _cfg = _host(tmp_path, lambda s, clip_saved_cb=None, recording_changed_cb=None: FakeController())
    calls = []
    monkeypatch.setattr(host, "restart", lambda: calls.append("restart"))
    new = Settings(clip_length_seconds=99)
    host.apply_settings(new)
    assert host._settings is new
    assert calls == ["restart"]


def test_repick_clears_token_then_restarts(qapp, tmp_path, monkeypatch):
    settings = Settings(output_dir=str(tmp_path), source_restore_token="tok")
    cfg = tmp_path / "config.toml"
    host = EngineHost(settings, cfg, builder=lambda s, clip_saved_cb=None, recording_changed_cb=None: FakeController())
    calls = []
    monkeypatch.setattr(host, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(host, "start", lambda: calls.append("start"))
    host.repick_source()
    assert settings.source_restore_token == ""
    assert calls == ["stop", "start"]


def test_recording_changed_cb_reemits_qt_signal(qapp, tmp_path):
    captured = {}

    def builder(settings, clip_saved_cb=None, recording_changed_cb=None):
        captured["rec_cb"] = recording_changed_cb
        return FakeController()

    host, _cfg = _host(tmp_path, builder)
    got = []
    host.recording_changed.connect(got.append)
    host._bring_up()
    captured["rec_cb"](True)
    captured["rec_cb"](False)
    assert got == [True, False]
