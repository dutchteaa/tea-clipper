from pathlib import Path

from tea_clipper.single_instance import InstanceLock, lock_path


def test_lock_path_uses_xdg_runtime_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert lock_path() == tmp_path / "tea-clipper.lock"


def test_lock_path_falls_back_to_tempdir(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    import tempfile

    assert lock_path() == Path(tempfile.gettempdir()) / "tea-clipper.lock"


def test_second_acquire_on_same_path_fails(tmp_path):
    path = tmp_path / "tea-clipper.lock"
    first = InstanceLock(path)
    second = InstanceLock(path)
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    # once released, a fresh lock can acquire again
    third = InstanceLock(path)
    assert third.acquire() is True
    third.release()


def test_release_is_idempotent(tmp_path):
    lock = InstanceLock(tmp_path / "tea-clipper.lock")
    assert lock.acquire() is True
    lock.release()
    lock.release()  # must not raise


def test_unusable_lock_dir_degrades_to_true(tmp_path):
    # path inside a non-existent, non-creatable directory -> open fails, not contention
    bad = tmp_path / "nope" / "deeper" / "tea-clipper.lock"
    lock = InstanceLock(bad)
    assert lock.acquire() is True  # degrades gracefully
    lock.release()
