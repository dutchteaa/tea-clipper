"""GUI-only activation channel over a Qt local socket.

The running GUI listens on a named local socket; a second GUI launch connects as a client
to ask the running instance to raise its window, then exits.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

SERVER_NAME = "tea-clipper"


def serve(on_activate: Callable[[], None]) -> QLocalServer:
    """Listen for activation requests; call on_activate() for each one.

    Caller must keep the returned server alive for the app's lifetime.
    """
    QLocalServer.removeServer(SERVER_NAME)  # clear a stale socket from a crashed run
    server = QLocalServer()

    def _handle() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return
        conn.disconnectFromServer()
        on_activate()

    server.newConnection.connect(_handle)
    if not server.listen(SERVER_NAME):
        logger.warning("could not listen on local socket %r: %s", SERVER_NAME, server.errorString())
    return server


def try_activate() -> bool:
    """Ask a running GUI to raise its window. False if none is listening."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(500):
        return False
    sock.write(b"activate")
    sock.flush()
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True
