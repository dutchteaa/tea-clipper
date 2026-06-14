import pytest

from tea_clipper.portal import (
    CURSOR_EMBEDDED,
    MONITOR,
    PERSIST_MODE,
    PortalFailedError,
    build_select_sources_options,
    build_video_fragment,
    parse_start_results,
)


def test_build_select_sources_options_without_token():
    opts = build_select_sources_options("")
    assert opts["types"].unpack() == MONITOR
    assert opts["cursor_mode"].unpack() == CURSOR_EMBEDDED
    assert opts["persist_mode"].unpack() == PERSIST_MODE
    assert "restore_token" not in opts  # empty token is omitted


def test_build_select_sources_options_with_token():
    opts = build_select_sources_options("tok-123")
    assert opts["restore_token"].unpack() == "tok-123"


def test_parse_start_results_returns_node_and_token():
    results = {"streams": [(42, {})], "restore_token": "newtok"}
    node_id, token = parse_start_results(results)
    assert node_id == 42
    assert token == "newtok"


def test_parse_start_results_missing_token_is_empty():
    node_id, token = parse_start_results({"streams": [(7, {})]})
    assert node_id == 7
    assert token == ""


def test_parse_start_results_no_streams_raises():
    with pytest.raises(PortalFailedError):
        parse_start_results({"streams": []})


def test_build_video_fragment():
    frag = build_video_fragment(27, 42, fps=60)
    assert frag == (
        "pipewiresrc fd=27 path=42 ! videoconvert ! videorate ! "
        "video/x-raw,framerate=60/1 ! queue name=venc_in"
    )


import os

from tea_clipper.portal import PortalManager, PortalCancelledError
from tea_clipper.settings import Settings


class FakePortal:
    """Records calls and returns canned values, standing in for ScreenCastPortal."""

    def __init__(self, start_results, fd=27):
        self._start_results = start_results
        self._fd = fd
        self.calls = []
        self.closed = []

    def create_session(self):
        self.calls.append(("create",))
        return "/org/session/1"

    def select_sources(self, session, *, types, cursor_mode, persist_mode, restore_token=""):
        self.calls.append(
            ("select", dict(types=types, cursor_mode=cursor_mode,
                            persist_mode=persist_mode, restore_token=restore_token))
        )

    def start(self, session, parent_window=""):
        self.calls.append(("start", session, parent_window))
        if isinstance(self._start_results, Exception):
            raise self._start_results
        return self._start_results

    def open_pipewire_remote(self, session):
        self.calls.append(("open", session))
        return self._fd

    def close_session(self, session):
        self.closed.append(session)


def _select_opts(fake):
    return next(c[1] for c in fake.calls if c[0] == "select")


def test_open_returns_fragment_and_saves_new_token():
    settings = Settings(source_restore_token="")
    fake = FakePortal({"streams": [(42, {})], "restore_token": "newtok"}, fd=27)
    mgr = PortalManager(settings, portal=fake)

    frag = mgr.open()

    assert frag == (
        "pipewiresrc fd=27 path=42 ! videoconvert ! videorate ! "
        "video/x-raw,framerate=60/1 ! queue name=venc_in"
    )
    assert settings.source_restore_token == "newtok"
    assert mgr.is_open
    opts = _select_opts(fake)
    assert opts["types"] == 1          # MONITOR
    assert opts["persist_mode"] == 2   # PERSIST_MODE
    assert opts["restore_token"] == "" # none saved yet


def test_open_reuses_existing_token_and_keeps_it_when_none_returned():
    settings = Settings(source_restore_token="saved-tok")
    fake = FakePortal({"streams": [(7, {})]}, fd=31)  # no restore_token in results
    mgr = PortalManager(settings, portal=fake)

    frag = mgr.open()

    assert "path=7" in frag
    assert _select_opts(fake)["restore_token"] == "saved-tok"
    assert settings.source_restore_token == "saved-tok"  # unchanged


def test_open_applies_configured_fps_to_fragment():
    settings = Settings(source_restore_token="t", fps=30)
    fake = FakePortal({"streams": [(7, {})]}, fd=31)
    mgr = PortalManager(settings, portal=fake)

    frag = mgr.open()

    assert "videorate ! video/x-raw,framerate=30/1" in frag


def test_open_cancelled_propagates_and_closes_session():
    settings = Settings()
    fake = FakePortal(PortalCancelledError("user said no"))
    mgr = PortalManager(settings, portal=fake)

    with pytest.raises(PortalCancelledError):
        mgr.open()

    assert fake.closed == ["/org/session/1"]  # session cleaned up on failure
    assert not mgr.is_open


def test_close_closes_fd_and_session():
    settings = Settings()
    real_fd = os.open(os.devnull, os.O_RDONLY)  # a real fd so os.close succeeds
    fake = FakePortal({"streams": [(1, {})]}, fd=real_fd)
    mgr = PortalManager(settings, portal=fake)
    mgr.open()

    mgr.close()

    assert not mgr.is_open
    assert fake.closed == ["/org/session/1"]
    with pytest.raises(OSError):
        os.close(real_fd)  # already closed by PortalManager.close()
