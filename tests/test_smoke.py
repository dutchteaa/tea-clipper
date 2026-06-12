from tea_clipper import __version__
from tea_clipper.gst_init import ensure_gst


def test_version_present():
    assert isinstance(__version__, str)


def test_ensure_gst_idempotent():
    ensure_gst()
    ensure_gst()  # second call must not raise
