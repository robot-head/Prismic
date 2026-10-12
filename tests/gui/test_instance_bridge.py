"""Focus-forwarding when a second launch targets an already-open
collection, per the user's explicit request after Phase 6: rather than
just showing an error, ask the existing instance to raise its window.
"""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from prismic.ui.instance_bridge import InstanceBridge, request_focus
from prismic.ui.main_window import MainWindow
from tests.gui._ui_test_helpers import assert_raise_not_requested
from tests.gui.helpers import open_and_wait


def test_request_focus_with_no_listener_returns_false(tmp_path: Path) -> None:
    assert request_focus(tmp_path / "nothing.prismic") is False


def test_instance_bridge_delivers_a_raise_request(qtbot: QtBot, tmp_path: Path) -> None:
    database_path = tmp_path / "vacation.prismic"
    database_path.touch()

    bridge = InstanceBridge()
    bridge.take_ownership(database_path)
    try:
        received = []
        bridge.raise_requested.connect(lambda: received.append(True))

        delivered = request_focus(database_path)

        assert delivered is True
        qtbot.waitUntil(lambda: received == [True], timeout=2000)
    finally:
        bridge.release()


def test_opening_the_same_collection_twice_focuses_the_first_window_instead_of_erroring(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    assert window._instance_bridge is not None

    second = MainWindow()
    qtbot.addWidget(second)

    with qtbot.waitSignal(window._instance_bridge.raise_requested, timeout=2000):
        second.open_collection(collection_dir)  # not is_startup: a manual "File > Open"

    assert second.session is None  # the second window never actually opened it


def test_a_locked_startup_launch_closes_itself_after_focusing_the_first(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)

    second = MainWindow()
    qtbot.addWidget(second)
    second.show()

    second.open_collection(collection_dir, is_startup=True)

    qtbot.waitUntil(lambda: not second.isVisible(), timeout=2000)
    assert second.session is None


def test_instance_bridge_ignores_raise_messages_with_trailing_bytes() -> None:
    bridge = InstanceBridge()
    assert_raise_not_requested(bridge, b"raise-extra")


def test_instance_bridge_release_closes_its_listening_server(tmp_path: Path) -> None:
    bridge = InstanceBridge()
    bridge.take_ownership(tmp_path / "collection.prismic")
    server = bridge._server
    assert server is not None and server.isListening()

    try:
        bridge.release()

        assert bridge._server is None
        assert server.isListening() is False
    finally:
        if server.isListening():
            server.close()


def test_instance_bridge_rejects_a_raise_message_that_is_only_a_prefix() -> None:
    bridge = InstanceBridge()
    assert_raise_not_requested(bridge, b"rai")
