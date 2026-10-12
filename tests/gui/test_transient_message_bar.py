from __future__ import annotations

from pytestqt.qtbot import QtBot

from prismic.ui.transient_message_bar import TransientMessageBar


def test_transient_message_without_timeout_stays_visible(qtbot: QtBot) -> None:
    bar = TransientMessageBar()
    qtbot.addWidget(bar)

    bar.show_message("Collection is already open")
    qtbot.wait(20)

    assert bar.text() == "Collection is already open"


def test_message_timer_is_inactive_after_clearing_a_transient_message(qtbot: QtBot) -> None:
    bar = TransientMessageBar()
    qtbot.addWidget(bar)

    bar.show_message("Temporary notice", timeout_ms=20)
    qtbot.waitUntil(lambda: bar.text() == "", timeout=1000)

    assert not bar._timer.isActive()  # noqa: SLF001 - verify one-shot timer behavior
