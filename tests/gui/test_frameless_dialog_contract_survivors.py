"""Contract checks for custom dialog geometry and title-bar behavior."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QMargins, QRect, Qt
from PySide6.QtWidgets import QLabel, QMessageBox
from pytestqt.qtbot import QtBot

from prismic.ui.frameless_dialog import FramelessDialog, MessageDialog, TitleBar
from tests.gui._mutation_helpers import mouse_event
from tests.gui.test_frameless_dialog import buttons_of


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

    buttons = buttons_of(dialog)
    assert [button.text() for button in buttons] == ["Yes", "Cancel"]
    assert buttons[0].isDefault()
    assert not buttons[1].isDefault()


def test_frameless_dialog_centering_accounts_for_frame_margins(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = FramelessDialog("Title")
    qtbot.addWidget(dialog)

    class FrameHandle:
        def frameMargins(self) -> QMargins:
            return QMargins(4, 8, 6, 12)

    class Screen:
        def availableGeometry(self) -> QRect:
            return QRect(0, 0, 1000, 800)

    class ParentWindow:
        def window(self) -> ParentWindow:
            return self

        def frameGeometry(self) -> QRect:
            return QRect(201, 161, 100, 80)

        def screen(self) -> Screen:
            return Screen()

    monkeypatch.setattr(dialog, "parentWidget", lambda: ParentWindow())
    monkeypatch.setattr(dialog, "create", lambda: None)
    monkeypatch.setattr(dialog, "windowHandle", lambda: FrameHandle())
    monkeypatch.setattr(dialog, "width", lambda: 100)
    monkeypatch.setattr(dialog, "height", lambda: 60)
    positions: list[tuple[int, int]] = []
    monkeypatch.setattr(dialog, "move", lambda x, y: positions.append((x, y)))

    dialog._center_on_parent()

    assert positions == [(200, 169)]


@pytest.mark.parametrize(
    ("move_result", "has_handle", "left_accepted", "expected_calls"),
    [(True, True, True, 1), (False, True, False, 1), (False, False, False, 0)],
    ids=["move-started", "move-denied", "no-handle"],
)
def test_title_bar_starts_system_move_only_for_a_left_press(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    move_result: bool,
    has_handle: bool,
    left_accepted: bool,
    expected_calls: int,
) -> None:
    title_bar = TitleBar("Title")
    qtbot.addWidget(title_bar)
    title_bar.show()
    calls: list[None] = []

    class MoveHandle:
        def startSystemMove(self) -> bool:
            calls.append(None)
            return move_result

    handle = MoveHandle() if has_handle else None

    class WindowStub:
        def windowHandle(self) -> MoveHandle | None:
            return handle

    monkeypatch.setattr(title_bar, "window", lambda: WindowStub())
    event = mouse_event(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton)
    event.ignore()

    title_bar.mousePressEvent(event)

    assert len(calls) == expected_calls
    assert event.isAccepted() is left_accepted

    right_press = mouse_event(QEvent.Type.MouseButtonPress, Qt.MouseButton.RightButton)
    right_press.ignore()
    title_bar.mousePressEvent(right_press)

    assert len(calls) == expected_calls
    assert not right_press.isAccepted()


def test_title_bar_swallows_double_clicks(qtbot: QtBot) -> None:
    title_bar = TitleBar("Title")
    qtbot.addWidget(title_bar)
    event = mouse_event(QEvent.Type.MouseButtonDblClick, Qt.MouseButton.LeftButton)
    event.ignore()

    title_bar.mouseDoubleClickEvent(event)

    assert event.isAccepted()
