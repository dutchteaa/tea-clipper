import os

from tea_clipper.ui.instance_server import serve, try_activate


def _spin(app, ms=200):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_try_activate_false_when_nothing_listening(qapp, monkeypatch):
    from PySide6.QtNetwork import QLocalServer

    unique_name = f"tea-clipper-test-{os.getpid()}"
    monkeypatch.setattr("tea_clipper.ui.instance_server.SERVER_NAME", unique_name)
    QLocalServer.removeServer(unique_name)  # ensure clean
    assert try_activate() is False


def test_serve_then_activate_fires_callback(qapp, monkeypatch):
    from PySide6.QtNetwork import QLocalServer

    unique_name = f"tea-clipper-test-{os.getpid()}"
    monkeypatch.setattr("tea_clipper.ui.instance_server.SERVER_NAME", unique_name)
    QLocalServer.removeServer(unique_name)  # ensure clean
    fired = []
    server = serve(lambda: fired.append(True))
    try:
        assert try_activate() is True
        _spin(qapp)
        assert fired == [True]
    finally:
        server.close()
