import io
import urllib.request

import pytest

from tea_clipper.update_check import parse_version, is_newer, should_prompt


def test_parse_version_strips_v_prefix():
    assert parse_version("v0.1.0") == (0, 1, 0)
    assert parse_version("0.1.0") == (0, 1, 0)


def test_parse_version_tolerates_short_and_junk():
    assert parse_version("1.2") == (1, 2)
    assert parse_version("garbage") == (0,)
    assert parse_version("") == (0,)


def test_is_newer():
    assert is_newer("v0.2.0", "0.1.0") is True
    assert is_newer("0.1.1", "0.1.0") is True
    assert is_newer("0.1.0", "0.1.0") is False
    assert is_newer("0.0.9", "0.1.0") is False


def test_should_prompt_newer_and_not_skipped():
    assert should_prompt("v0.2.0", "0.1.0", "") is True


def test_should_prompt_false_when_skipped():
    assert should_prompt("v0.2.0", "0.1.0", "v0.2.0") is False


def test_should_prompt_false_when_not_newer():
    assert should_prompt("0.1.0", "0.1.0", "") is False
