from tea_clipper.hotkeys import (
    SAVE_CLIP,
    TOGGLE_RECORD,
    build_shortcuts_list,
)


def test_build_shortcuts_list_ids_in_order():
    shortcuts = build_shortcuts_list()
    assert [s[0] for s in shortcuts] == [SAVE_CLIP, TOGGLE_RECORD]


def test_build_shortcuts_list_descriptions_and_triggers():
    shortcuts = build_shortcuts_list()
    save_opts = shortcuts[0][1]
    assert save_opts["description"].unpack() == "Save clip (last N seconds)"
    assert save_opts["preferred_trigger"].unpack() == "CTRL+ALT+c"
    rec_opts = shortcuts[1][1]
    assert rec_opts["description"].unpack() == "Toggle manual recording"
    assert rec_opts["preferred_trigger"].unpack() == "CTRL+ALT+r"
