from tea_clipper.ui.instance_server import SERVER_NAME, serve, try_activate


def _spin(app, ms=200):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_try_activate_false_when_nothing_listening(qapp):
    from PySide6.QtNetwork import QLocalServer

    QLocalServer.removeServer(SERVER_NAME)  # ensure clean
    assert try_activate() is False


def test_serve_then_activate_fires_callback(qapp):
    fired = []
    server = serve(lambda: fired.append(True))
    try:
        assert try_activate() is True
        _spin(qapp)
        assert fired == [True]
    finally:
        server.close()
