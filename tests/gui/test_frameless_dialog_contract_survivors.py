"""Contract checks for custom dialog geometry and title-bar behavior."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QMargins, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton
from pytestqt.qtbot import QtBot

from prismic.ui.frameless_dialog import MessageDialog, TitleBar


def test_message_dialog_keeps_its_layout_and_minimum_width_contract(qtbot: QtBot) -> None:
    dialog = MessageDialog(
        None,
        "Title",
        "A message with enough text to wrap when it needs to.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Yes,
    )
    qtbot.addWidget(dialog)

    outer = dialog.layout()
    assert outer is not None
    body = outer.itemAt(1).layout()
    assert body is not None
    button_row = body.itemAt(1).layout()
    assert button_row is not None
    text = dialog.findChild(QLabel, "messageDialogText")
    assert text is not None

    assert dialog.minimumWidth() == 360
    assert dialog.isModal()
    assert text.maximumWidth() == 420
    assert text.wordWrap()
    assert outer.contentsMargins() == QMargins(0, 0, 0, 0)
    assert outer.spacing() == 0
    assert body.contentsMargins() == QMargins(20, 16, 20, 16)
    assert body.spacing() == 16
    assert button_row.spacing() == 8
    assert dialog.title_bar.layout().contentsMargins() == QMargins(14, 0, 0, 0)
    assert dialog.title_bar.layout().spacing() == 0

    buttons = [
        button
        for button in dialog.findChildren(QPushButton)
        if button is not dialog.title_bar.close_button
    ]
    assert [button.text() for button in buttons] == ["Yes", "Cancel"]
    assert buttons[0].isDefault()
    assert not buttons[1].isDefault()


@pytest.mark.parametrize("window_handle", [None, "cannot-move"], ids=["no-handle", "move-denied"])
def test_title_bar_leaves_a_left_press_unhandled_when_system_move_is_unavailable(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    window_handle: object,
) -> None:
    title_bar = TitleBar("Title")
    qtbot.addWidget(title_bar)
    title_bar.show()
    calls: list[None] = []

    class DeniedHandle:
        def startSystemMove(self) -> bool:
            calls.append(None)
            return False

    handle = DeniedHandle() if window_handle == "cannot-move" else None

    class WindowStub:
        def windowHandle(self) -> DeniedHandle | None:
            return handle

    monkeypatch.setattr(title_bar, "window", lambda: WindowStub())
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(1, 1),
        QPointF(1, 1),
        QPointF(1, 1),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.ignore()

    title_bar.mousePressEvent(event)

    assert calls == ([None] if handle is not None else [])
    assert not event.isAccepted()


def test_title_bar_swallows_double_clicks(qtbot: QtBot) -> None:
    title_bar = TitleBar("Title")
    qtbot.addWidget(title_bar)
    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(1, 1),
        QPointF(1, 1),
        QPointF(1, 1),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.ignore()

    title_bar.mouseDoubleClickEvent(event)

    assert event.isAccepted()
