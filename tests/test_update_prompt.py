from tea_clipper.settings import Settings
from tea_clipper.update_check import UpdateInfo
from tea_clipper.ui.update_prompt import decide_update_action


def test_decide_skips_when_not_newer():
    s = Settings()  # current version is tea_clipper.__version__ (0.1.0)
    info = UpdateInfo(version="0.0.1", notes="", url="x")
    assert decide_update_action(info, s) == "ignore"


def test_decide_prompts_when_newer():
    s = Settings()
    info = UpdateInfo(version="v999.0.0", notes="notes", url="x")
    assert decide_update_action(info, s) == "prompt"


def test_decide_ignores_skipped_version():
    s = Settings(skipped_update_version="v999.0.0")
    info = UpdateInfo(version="v999.0.0", notes="notes", url="x")
    assert decide_update_action(info, s) == "ignore"


def test_decide_ignores_none():
    assert decide_update_action(None, Settings()) == "ignore"
