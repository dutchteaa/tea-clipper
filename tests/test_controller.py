from pathlib import Path

from tea_clipper.controller import Controller, compute_max_segments
from tea_clipper.hotkeys import SAVE_CLIP, TOGGLE_RECORD
from tea_clipper.settings import Settings


class FakePipeline:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeReplay:
    def __init__(self, raises=False):
        self.calls = []
        self._raises = raises

    def save_last(self, seconds, out, pipeline):
        self.calls.append((seconds, out, pipeline))
        if self._raises:
            raise RuntimeError("boom")
        return out


class FakeRecorder:
    def __init__(self):
        self.is_recording = False
        self.started = 0
        self.stopped = []

    def start(self):
        self.started += 1
        self.is_recording = True

    def stop(self, out):
        self.is_recording = False
        self.stopped.append(out)
        return out


class FakeHotkeys:
    def __init__(self):
        self.listeners = {}
        self.started = False
        self.stopped = False
        self.run_loop = None

    def add_listener(self, action, cb):
        self.listeners.setdefault(action, []).append(cb)

    def start(self, run_loop=True):
        self.started = True
        self.run_loop = run_loop

    def stop(self):
        self.stopped = True

    def fire(self, action):
        for cb in self.listeners.get(action, []):
            cb()


class FakePortal:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _controller(tmp_path, replay=None, recorder=None, portal=None):
    settings = Settings(output_dir=str(tmp_path), clip_length_seconds=20, segment_seconds=2)
    pipeline = FakePipeline()
    hotkeys = FakeHotkeys()
    ctl = Controller(
        settings, pipeline, replay or FakeReplay(), recorder or FakeRecorder(),
        hotkeys, portal=portal,
    )
    return ctl, pipeline, hotkeys


def test_compute_max_segments():
    assert compute_max_segments(Settings(clip_length_seconds=30, segment_seconds=2)) == 17
    assert compute_max_segments(Settings(clip_length_seconds=10, segment_seconds=3)) == 6


def test_start_wires_handlers_and_starts(tmp_path):
    ctl, pipeline, hotkeys = _controller(tmp_path)
    ctl.start()
    assert SAVE_CLIP in hotkeys.listeners
    assert TOGGLE_RECORD in hotkeys.listeners
    assert pipeline.started
    assert hotkeys.started and hotkeys.run_loop is False


def test_save_clip_handler_saves_with_clip_length(tmp_path):
    replay = FakeReplay()
    ctl, pipeline, hotkeys = _controller(tmp_path, replay=replay)
    ctl.start()
    hotkeys.fire(SAVE_CLIP)
    assert len(replay.calls) == 1
    seconds, out, pipe = replay.calls[0]
    assert seconds == 20                      # settings.clip_length_seconds
    assert pipe is pipeline
    assert Path(out).parent == tmp_path
    assert Path(out).name.startswith("clip_")
    assert ctl.last_clip == out


def test_toggle_record_alternates(tmp_path):
    recorder = FakeRecorder()
    ctl, pipeline, hotkeys = _controller(tmp_path, recorder=recorder)
    ctl.start()
    hotkeys.fire(TOGGLE_RECORD)
    assert recorder.started == 1 and recorder.is_recording
    hotkeys.fire(TOGGLE_RECORD)
    assert recorder.is_recording is False
    assert len(recorder.stopped) == 1
    assert Path(recorder.stopped[0]).name.startswith("recording_")


def test_save_clip_failure_is_caught(tmp_path):
    replay = FakeReplay(raises=True)
    ctl, pipeline, hotkeys = _controller(tmp_path, replay=replay)
    ctl.start()
    hotkeys.fire(SAVE_CLIP)   # must not raise
    assert ctl.last_clip is None


def test_clip_saved_cb_fires_on_save(tmp_path):
    saved = []
    ctl, _pipeline, _hotkeys = _controller(tmp_path)
    ctl._clip_saved_cb = saved.append   # set directly; constructor path covered below
    ctl.start()
    ctl.save_clip()
    assert saved == [str(ctl.last_clip)]


def test_clip_saved_cb_passed_via_constructor(tmp_path):
    saved = []
    settings = Settings(output_dir=str(tmp_path))
    ctl = Controller(
        settings, FakePipeline(), FakeReplay(), FakeRecorder(), FakeHotkeys(),
        clip_saved_cb=saved.append,
    )
    ctl.start()
    ctl.save_clip()
    assert len(saved) == 1


def test_clip_saved_cb_fires_on_record_stop(tmp_path):
    saved = []
    recorder = FakeRecorder()
    ctl, _pipeline, _hotkeys = _controller(tmp_path, recorder=recorder)
    ctl._clip_saved_cb = saved.append
    ctl.start()
    ctl.toggle_record()   # start: no clip yet
    assert saved == []
    ctl.toggle_record()   # stop: clip finalized
    assert len(saved) == 1


def test_clip_saved_cb_not_called_on_failure(tmp_path):
    saved = []
    replay = FakeReplay(raises=True)
    ctl, _pipeline, _hotkeys = _controller(tmp_path, replay=replay)
    ctl._clip_saved_cb = saved.append
    ctl.start()
    ctl.save_clip()       # save_last raises
    assert saved == []


def test_stop_tears_down(tmp_path):
    portal = FakePortal()
    settings = Settings(output_dir=str(tmp_path))
    pipeline = FakePipeline()
    hotkeys = FakeHotkeys()
    ctl = Controller(settings, pipeline, FakeReplay(), FakeRecorder(), hotkeys, portal=portal)
    ctl.start()
    ctl.stop()
    assert hotkeys.stopped
    assert pipeline.stopped
    assert portal.closed
