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
    frag = build_video_fragment(27, 42)
    assert frag == "pipewiresrc fd=27 path=42 ! videoconvert ! queue name=venc_in"
