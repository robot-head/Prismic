"""Tests for `MessageDialog`, the themed stand-in for the static
`QMessageBox.question`/`warning`/`critical` helpers.

`FramelessDialog`'s own mechanics (the frameless window flag, the
flash-free centering, the title bar's close button and its focus policy)
are exercised thoroughly via `SettingsDialog` in `test_settings_dialog.py`
-- both classes share that code, so this file only re-touches it lightly,
as a check that `MessageDialog`'s own layout doesn't accidentally break
what it inherits, and otherwise sticks to what's specific to a message
dialog: which buttons appear, which one is default, and what `exec()`
reports.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton
from pytestqt.qtbot import QtBot

from prismic.ui.frameless_dialog import MessageDialog, SizeGrip
from tests.gui._dialog_helpers import message_dialog
from tests.gui.helpers import shown_parent


def buttons_of(dialog: MessageDialog) -> list[QPushButton]:
    """Every button in the dialog's own button row, left to right, in
    the order they were added -- title-bar close button excluded, since
    that one isn't part of the button row this module builds."""
    return [
        button
        for button in dialog.findChildren(QPushButton)
        if button is not dialog.title_bar.close_button
    ]


# -- Construction --------------------------------------------------------


def _dialog(
    qtbot: QtBot,
    *,
    title: str = "Title",
    text: str = "Text",
    buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    default: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
) -> MessageDialog:
    dialog = MessageDialog(
        parent=None,
        title=title,
        text=text,
        buttons=buttons,
        default=default,
    )
    qtbot.addWidget(dialog)
    return dialog


def _yes_cancel_dialog(qtbot: QtBot) -> MessageDialog:
    return _dialog(
        qtbot,
        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        default=QMessageBox.StandardButton.Cancel,
    )


def test_the_dialog_has_no_native_frame(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot)

    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint


def test_the_title_bar_shows_the_given_title(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot, title="Could not open collection")

    label = dialog.title_bar.findChild(QLabel, "dialogTitle")
    assert label is not None
    assert label.text() == "Could not open collection"


def test_the_body_shows_the_given_text(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot, text="Something went wrong in a way the user needs to know about.")

    label = dialog.findChild(QLabel, "messageDialogText")
    assert label is not None
    assert label.text() == "Something went wrong in a way the user needs to know about."


def test_only_the_requested_buttons_are_built(qtbot: QtBot) -> None:
    dialog = _yes_cancel_dialog(qtbot)

    assert [button.text() for button in buttons_of(dialog)] == ["Yes", "Cancel"]


def test_a_single_button_dialog_builds_just_that_one(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot)

    assert [button.text() for button in buttons_of(dialog)] == ["OK"]


def test_the_default_button_is_marked_as_qts_default(qtbot: QtBot) -> None:
    """So Enter fires it, the same as a native QMessageBox."""
    dialog = _yes_cancel_dialog(qtbot)

    by_text = {button.text(): button for button in buttons_of(dialog)}
    assert by_text["Cancel"].isDefault()
    assert not by_text["Yes"].isDefault()


# -- What exec() reports --------------------------------------------------


def test_clicking_a_button_reports_it(qtbot: QtBot) -> None:
    dialog = _yes_cancel_dialog(qtbot)
    yes_button = next(b for b in buttons_of(dialog) if b.text() == "Yes")

    qtbot.mouseClick(yes_button, Qt.MouseButton.LeftButton)

    assert dialog.clicked_button == QMessageBox.StandardButton.Yes
    assert not dialog.isVisible()


def test_escape_reports_the_default_button(qtbot: QtBot) -> None:
    """Matches `QMessageBox`'s own convention: closing some way other
    than a button click falls back to whichever button was default."""
    dialog = _yes_cancel_dialog(qtbot)

    qtbot.keyClick(dialog, Qt.Key.Key_Escape)

    assert dialog.clicked_button == QMessageBox.StandardButton.Cancel
    assert not dialog.isVisible()


def test_the_title_bar_close_button_also_reports_the_default(qtbot: QtBot) -> None:
    dialog = _yes_cancel_dialog(qtbot)

    qtbot.mouseClick(dialog.title_bar.close_button, Qt.MouseButton.LeftButton)

    assert dialog.clicked_button == QMessageBox.StandardButton.Cancel
    assert not dialog.isVisible()


# -- The static helpers ----------------------------------------------------
# `question`/`warning`/`critical` build a dialog and call its real,
# blocking `exec()` -- so each test intercepts `__init__` to grab the
# instance and queue a button click on a zero-delay timer before `exec()`
# starts its own event loop. That exercises the actual modal round trip
# (does clicking a button inside a truly blocking exec() unblock it with
# the right value?) rather than assuming it works.


def intercept(
    monkeypatch: pytest.MonkeyPatch, qtbot: QtBot, on_shown: Callable[[MessageDialog], None]
) -> list[MessageDialog]:
    """Capture every `MessageDialog` constructed during the test, and
    queue `on_shown(dialog)` to run once its (still-to-come) `exec()`
    starts spinning."""
    seen: list[MessageDialog] = []
    original_init = MessageDialog.__init__

    def capture_init(
        self: MessageDialog,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        original_init(self, *args, **kwargs)
        seen.append(self)
        qtbot.addWidget(self)
        QTimer.singleShot(0, lambda: on_shown(self))

    monkeypatch.setattr(MessageDialog, "__init__", capture_init)
    return seen


def test_question_returns_the_clicked_button(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    intercept(monkeypatch, qtbot, lambda dialog: buttons_of(dialog)[0].click())

    answer = MessageDialog.question(None, "Title", "Text")

    assert answer == QMessageBox.StandardButton.Yes  # the first button, per _BUTTON_ORDER


def test_question_defaults_to_yes_and_cancel(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = intercept(monkeypatch, qtbot, lambda dialog: dialog.reject())

    MessageDialog.question(None, "Title", "Text")

    assert [b.text() for b in buttons_of(seen[0])] == ["Yes", "Cancel"]


def test_warning_shows_only_an_ok_button(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = intercept(monkeypatch, qtbot, lambda dialog: dialog.accept())

    MessageDialog.warning(None, "Could not create tag", "A tag by that name already exists.")

    assert [b.text() for b in buttons_of(seen[0])] == ["OK"]


def test_critical_shows_only_an_ok_button(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = intercept(monkeypatch, qtbot, lambda dialog: dialog.accept())

    MessageDialog.critical(None, "Could not open collection", "Boom.")

    assert [b.text() for b in buttons_of(seen[0])] == ["OK"]


# -- Reused frameless mechanics ---------------------------------------------
# Light coverage only -- see this file's module docstring.


def test_a_parented_message_dialog_positions_itself_before_it_is_shown(qtbot: QtBot) -> None:
    parent = shown_parent(qtbot, 1200, 800)

    dialog = message_dialog(parent)
    qtbot.addWidget(dialog)

    assert dialog.testAttribute(Qt.WidgetAttribute.WA_Moved)


def test_a_message_dialog_has_no_resize_grip(qtbot: QtBot) -> None:
    """Unlike Settings, a message box's size follows its text -- there's
    nothing for a resize handle to usefully do here."""
    dialog = message_dialog()
    qtbot.addWidget(dialog)

    assert dialog.findChild(SizeGrip) is None
