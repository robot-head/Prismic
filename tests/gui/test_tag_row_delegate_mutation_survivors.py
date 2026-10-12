"""Regression tests for tag-row shortcut, event, and geometry behavior."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QModelIndex, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem
from pytestqt.qtbot import QtBot

from tests.gui import _tag_model_support as model_support


class _Font:
    def __init__(self) -> None:
        self.pixel_size = 12
        self.bold = False

    def setPixelSize(self, size: int) -> None:
        self.pixel_size = size

    def setBold(self, bold: bool) -> None:
        self.bold = bold


class _Metrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Qt.TextElideMode, int]] = []

    def elidedText(self, text: str, mode: Qt.TextElideMode, width: int) -> str:
        self.calls.append((text, mode, width))
        return text


class _Painter(model_support.RecordingCalls):
    def __init__(self) -> None:
        super().__init__()
        self.metrics = _Metrics()
        self.font_value = _Font()

    def fontMetrics(self) -> _Metrics:
        return self.metrics

    def font(self) -> _Font:
        return self.font_value


def _delegate(
    qtbot: QtBot, *, show_shortcuts: bool = False
) -> tuple[QListView, model_support.TagRowDelegate]:
    view = QListView()
    qtbot.addWidget(view)
    return view, model_support.TagRowDelegate(view, view, show_shortcuts=show_shortcuts)


def _model() -> model_support.TagListModel:
    model = model_support.TagListModel()
    model.set_tags(
        [
            model_support.Tag(id=1, name="first"),
            model_support.Tag(id=2, name="second"),
            model_support.Tag(id=3, name="third"),
            model_support.Tag(id=4, name="fourth"),
        ],
        frozenset({1, 3}),
    )
    return model


def _paint_option(rect: QRect, *, hovered: bool = False) -> QStyleOptionViewItem:
    option = QStyleOptionViewItem()
    option.rect = rect
    option.state = QStyle.StateFlag.State_MouseOver if hovered else QStyle.StateFlag.State_None
    return option


def test_shortcut_configuration_updates_only_when_the_value_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    view, delegate = _delegate(qtbot)
    updates: list[bool] = []
    monkeypatch.setattr(view.viewport(), "update", lambda: updates.append(True))

    delegate.set_show_checked_shortcuts(False)
    assert updates == []
    delegate.set_show_checked_shortcuts(True)
    delegate.set_show_checked_shortcuts(True)
    delegate.set_show_checked_shortcuts(False)
    assert updates == [True, True]

    supplied = {0: "Q", 1: "F11"}
    delegate.set_shortcut_labels(supplied)
    supplied[1] = "changed"
    delegate.set_shortcut_labels({0: "Q", 1: "F11"})
    assert updates == [True, True, True]
    assert delegate._shortcut_labels == {0: "Q", 1: "F11"}  # noqa: SLF001


def test_shortcut_paint_uses_checked_or_unchecked_slots_and_elides_long_labels(
    qtbot: QtBot,
) -> None:
    view, delegate = _delegate(qtbot, show_shortcuts=True)
    model = _model()
    delegate.set_shortcut_labels({1: "F11"})
    painter = _Painter()
    option = _paint_option(QRect(0, 0, 240, 32))

    checked_index = model.index(2, 0)
    assert checked_index.data(model_support.CheckedRole) is True
    assert checked_index.data(model_support.CheckedSlotRole) == 1
    delegate.set_show_checked_shortcuts(True)
    delegate.paint(painter, option, checked_index)

    assert painter.calls_for("drawText")[0] == (
        QRect(8, 8, 15, 15),
        Qt.AlignmentFlag.AlignCenter,
        "F1",
    )
    assert painter.font_value.pixel_size == 9
    assert painter.font_value.bold is True

    unchecked_index = model.index(3, 0)
    assert unchecked_index.data(model_support.UncheckedSlotRole) == 1
    delegate.set_show_checked_shortcuts(False)
    painter = _Painter()
    delegate.paint(painter, option, unchecked_index)
    assert painter.calls_for("drawText")[0][2] == "F1"


@pytest.mark.parametrize(
    ("row_rect", "expected"),
    [
        (
            QRect(5, 7, 140, 31),
            (QRect(13, 15, 15, 15), QRect(98, 13, 18, 18), QRect(118, 13, 18, 18)),
        ),
        (
            QRect(12, 25, 240, 41),
            (QRect(20, 38, 15, 15), QRect(205, 36, 18, 18), QRect(225, 36, 18, 18)),
        ),
    ],
)
def test_hit_targets_keep_their_offsets_for_odd_row_heights(
    qtbot: QtBot, row_rect: QRect, expected: tuple[QRect, QRect, QRect]
) -> None:
    _view, delegate = _delegate(qtbot)

    assert delegate._rects(row_rect) == expected  # noqa: SLF001


def test_size_hint_preserves_the_row_width_and_fixed_height(qtbot: QtBot) -> None:
    _view, delegate = _delegate(qtbot)
    option = _paint_option(QRect(0, 0, 257, 41))

    assert delegate.sizeHint(option, QModelIndex()).width() == 257
    assert delegate.sizeHint(option, QModelIndex()).height() == 32


def test_checked_and_hovered_paint_states_use_the_expected_background_and_checkbox(
    qtbot: QtBot,
) -> None:
    _view, delegate = _delegate(qtbot)
    model = _model()
    row_rect = QRect(0, 0, 240, 32)
    checked_painter = _Painter()
    delegate.paint(checked_painter, _paint_option(row_rect, hovered=True), model.index(0, 0))

    assert checked_painter.calls_for("fillRect")
    assert checked_painter.calls_for("fillPath")
    assert len(checked_painter.calls_for("drawPath")) == 1  # hover pencil only
    assert len(checked_painter.calls_for("drawText")) == 1

    unchecked_painter = _Painter()
    delegate.paint(unchecked_painter, _paint_option(row_rect, hovered=True), model.index(1, 0))
    assert len(unchecked_painter.calls_for("drawPath")) == 2  # outline and hover pencil
    assert unchecked_painter.calls_for("fillPath") == []
    assert len(unchecked_painter.calls_for("drawText")) == 1
    assert len(unchecked_painter.calls_for("drawLine")) == 3


def test_editor_event_rejects_bad_ids_and_non_release_events(qtbot: QtBot) -> None:
    _view, delegate = _delegate(qtbot)
    option = _paint_option(QRect(0, 0, 220, 32))
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(40, 16),
        QPointF(40, 16),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    class InvalidIndex:
        def data(self, role: int) -> object:
            return "not an integer" if role == model_support.TagIdRole else None

    toggled: list[int] = []
    delegate.toggle_requested.connect(toggled.append)
    assert (
        delegate.editorEvent(release, model_support.TagListModel(), option, InvalidIndex()) is False
    )  # type: ignore[arg-type]
    assert (
        delegate.editorEvent(
            QEvent(QEvent.Type.KeyPress), model_support.TagListModel(), option, QModelIndex()
        )
        is False
    )
    assert toggled == []


def test_enter_commits_and_escape_reverts_a_delegate_editor(qtbot: QtBot) -> None:
    view, delegate = _delegate(qtbot)
    model = _model()
    option = _paint_option(QRect(0, 0, 220, 32))
    editor = delegate.createEditor(view, option, model.index(0, 0))
    committed: list[object] = []
    closed: list[tuple[object, ...]] = []
    delegate.commitData.connect(committed.append)
    delegate.closeEditor.connect(lambda *args: closed.append(args))

    enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    assert delegate.eventFilter(editor, enter) is True
    assert committed == [editor]
    assert closed[-1] == (editor, QStyledItemDelegate.EndEditHint.NoHint)

    escape = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    assert delegate.eventFilter(editor, escape) is True
    assert closed[-1] == (
        editor,
        QStyledItemDelegate.EndEditHint.RevertModelCache,
    )


def test_inline_editor_geometry_uses_the_row_inset_and_padding(qtbot: QtBot) -> None:
    _view, delegate = _delegate(qtbot)
    option = _paint_option(QRect(12, 25, 241, 39))

    model_support.assert_editor_geometry(delegate, option, QRect(42, 27, 202, 35))
