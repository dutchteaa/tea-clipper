from tea_clipper.ui.level_meter import db_to_fraction, peak_to_display_db


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
