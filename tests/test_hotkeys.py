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


from tea_clipper.hotkeys import HotkeyService


class FakeShortcutsPortal:
    """Records calls and lets tests fire activations, standing in for GlobalShortcutsPortal."""

    def __init__(self):
        self.calls = []
        self.closed = []
        self._activated = None

    def create_session(self):
        self.calls.append("create")
        return "/gs/session/1"

    def bind_shortcuts(self, session, shortcuts, parent_window=""):
        self.calls.append(("bind", session, [s[0] for s in shortcuts]))

    def connect_activated(self, callback):
        self._activated = callback

    def fire(self, shortcut_id):
        assert self._activated is not None, "connect_activated was never called"
        self._activated(shortcut_id)

    def close_session(self, session):
        self.closed.append(session)


def test_start_binds_expected_shortcuts():
    fake = FakeShortcutsPortal()
    svc = HotkeyService(portal=fake)
    svc.start(run_loop=False)
    bind = next(c for c in fake.calls if c[0] == "bind")
    assert bind[2] == [SAVE_CLIP, TOGGLE_RECORD]
    assert svc.is_running


def test_activated_dispatches_to_matching_listener():
    fake = FakeShortcutsPortal()
    svc = HotkeyService(portal=fake)
    saves, records = [], []
    svc.add_listener(SAVE_CLIP, lambda: saves.append(1))
    svc.add_listener(TOGGLE_RECORD, lambda: records.append(1))
    svc.start(run_loop=False)
    fake.fire(SAVE_CLIP)
    assert saves == [1]
    assert records == []


def test_multiple_listeners_all_fire():
    fake = FakeShortcutsPortal()
    svc = HotkeyService(portal=fake)
    hits = []
    svc.add_listener(SAVE_CLIP, lambda: hits.append("a"))
    svc.add_listener(SAVE_CLIP, lambda: hits.append("b"))
    svc.start(run_loop=False)
    fake.fire(SAVE_CLIP)
    assert hits == ["a", "b"]


def test_unknown_shortcut_id_is_ignored():
    fake = FakeShortcutsPortal()
    svc = HotkeyService(portal=fake)
    fired = []
    svc.add_listener(SAVE_CLIP, lambda: fired.append(1))
    svc.start(run_loop=False)
    fake.fire("bogus")  # no registered listener; must not raise
    assert fired == []


def test_stop_closes_session():
    fake = FakeShortcutsPortal()
    svc = HotkeyService(portal=fake)
    svc.start(run_loop=False)
    svc.stop()
    assert fake.closed == ["/gs/session/1"]
    assert not svc.is_running
