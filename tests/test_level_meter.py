from tea_clipper.audio import AudioDevice
from tea_clipper.ui.level_meter import LevelMeterBar, MicLevelMonitor, _build_monitor_launch, db_to_fraction, peak_to_display_db


def test_peak_empty_returns_floor():
    assert peak_to_display_db([]) == -60.0


def test_peak_takes_max_channel():
    assert peak_to_display_db([-40.0, -12.0]) == -12.0


def test_peak_clamped_to_floor():
    assert peak_to_display_db([-90.0]) == -60.0


def test_fraction_endpoints():
    assert db_to_fraction(-60.0) == 0.0
    assert db_to_fraction(0.0) == 1.0


def test_fraction_midpoint():
    assert abs(db_to_fraction(-30.0) - 0.5) < 1e-6


def test_fraction_clamped():
    assert db_to_fraction(-100.0) == 0.0
    assert db_to_fraction(12.0) == 1.0


def _mic(name):
    return AudioDevice(name, name, is_monitor=False, is_default=False)


def test_monitor_launch_none_without_mics():
    assert _build_monitor_launch([]) is None


def test_monitor_launch_builds_level_pipeline():
    launch = _build_monitor_launch([_mic("mic.a")])
    assert "pipewiresrc target-object=mic.a" in launch
    assert "level" in launch
    assert "post-messages=true" in launch
    assert "audiomixer name=amix" in launch


def test_monitor_launch_one_chain_per_mic():
    launch = _build_monitor_launch([_mic("mic.a"), _mic("mic.b")])
    assert launch.count("pipewiresrc") == 2


def test_monitor_start_is_noop_without_mics(qapp):
    # No mics -> launch is None -> start()/stop() must not raise and must not build a pipeline.
    mon = MicLevelMonitor([])
    mon.start()
    assert mon._pipeline is None
    mon.stop()


def test_meter_bar_stores_level(qapp):
    bar = LevelMeterBar()
    bar.set_level(-18.0)
    assert bar._level_db == -18.0


def test_meter_bar_stores_threshold(qapp):
    bar = LevelMeterBar()
    bar.set_threshold(-35.0)
    assert bar._threshold_db == -35.0
