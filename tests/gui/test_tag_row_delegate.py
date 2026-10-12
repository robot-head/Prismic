from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QModelIndex, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QLineEdit,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from pytestqt.qtbot import QtBot

from prismic.domain.tag import Tag
from prismic.ui.tag_model import TagIdRole, TagListModel
from prismic.ui.tag_row_delegate import TagRowDelegate
from tests.gui import _tag_model_support as model_support
from tests.gui._ui_test_helpers import RecordingCalls, RecordingPainter, left_mouse_release_at


def _build(qtbot: QtBot) -> tuple[QListView, TagListModel, TagRowDelegate]:
    view = QListView()
    qtbot.addWidget(view)
    model = TagListModel()
    view.setModel(model)
    delegate = TagRowDelegate(view, view)
    view.setItemDelegate(delegate)
    model.set_tags([Tag(id=1, name="kittens"), Tag(id=2, name="sunset")], frozenset({2}))
    view.resize(220, 200)
    view.show()
    qtbot.waitExposed(view)
    return view, model, delegate


def test_clicking_anywhere_on_a_row_toggles_it_not_just_the_checkbox(qtbot: QtBot) -> None:
    view, model, delegate = _build(qtbot)
    toggled: list[int] = []
    delegate.toggle_requested.connect(toggled.append)
    index = model.index(0, 0)  # "kittens", unchecked
    row_rect = view.visualRect(index)
    # Click near the far-right edge of the row -- nowhere near the
    # checkbox -- to prove the whole row is the toggle target, not just
    # the small indicator box.
    far_right = row_rect.center()
    far_right.setX(row_rect.right() - 2)

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=far_right)

    # Emission is deferred a tick past the click (see `_emit_later`'s
    # docstring in tag_row_delegate.py) so the handler's model reset can't
    # land while the view is still mid-dispatch of this same mouse event.
    qtbot.waitUntil(lambda: toggled == [1], timeout=1000)


def test_clicking_the_delete_icon_emits_delete_not_toggle(qtbot: QtBot) -> None:
    view, model, delegate = _build(qtbot)
    toggled: list[int] = []
    deleted: list[int] = []
    delegate.toggle_requested.connect(toggled.append)
    delegate.delete_requested.connect(deleted.append)
    index = model.index(0, 0)
    row_rect = view.visualRect(index)
    _checkbox, _rename, delete_rect = delegate._rects(row_rect)  # noqa: SLF001 - white-box test

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=delete_rect.center())
    qtbot.waitUntil(lambda: deleted == [1], timeout=1000)

    assert toggled == []


def test_clicking_the_rename_icon_starts_inline_editing_not_toggle(qtbot: QtBot) -> None:
    view, model, delegate = _build(qtbot)
    toggled: list[int] = []
    delegate.toggle_requested.connect(toggled.append)
    index = model.index(0, 0)
    row_rect = view.visualRect(index)
    _checkbox, rename_rect, _delete = delegate._rects(row_rect)  # noqa: SLF001 - white-box test

    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rename_rect.center())

    assert view.indexWidget(index) is not None
    qtbot.wait(50)  # give a wrongly-fired deferred toggle a chance to arrive before checking
    assert toggled == []


def test_committing_a_rename_emits_rename_committed_not_a_model_write(qtbot: QtBot) -> None:
    view, model, delegate = _build(qtbot)
    renamed: list[tuple[int, str]] = []
    delegate.rename_committed.connect(lambda tag_id, name: renamed.append((tag_id, name)))
    index = model.index(0, 0)
    view.edit(index)
    editor = view.indexWidget(index)
    assert isinstance(editor, QLineEdit)

    editor.setText("felines")
    qtbot.keyClick(editor, Qt.Key.Key_Return)

    assert renamed == [(1, "felines")]
    # The model itself never changes -- TagListModel is display-only; a
    # real rename only happens once the caller dispatches a command and
    # calls set_tags() again.
    assert model.tag_at(0).name == "kittens"


def _delegate(qtbot: QtBot) -> model_support.TagRowDelegate:
    view = QListView()
    qtbot.addWidget(view)
    return model_support.TagRowDelegate(view, view)


def test_delegate_rects_use_the_row_geometry_and_center_the_controls(qtbot: QtBot) -> None:
    delegate = _delegate(qtbot)

    checkbox, rename, delete = delegate._rects(QRect(7, 11, 220, 34))  # noqa: SLF001

    assert checkbox == QRect(15, 20, 15, 15)
    assert rename == QRect(180, 19, 18, 18)
    assert delete == QRect(200, 19, 18, 18)


class _RecordingPainter(model_support.RecordingCalls):
    def __init__(self) -> None:
        super().__init__()
        self.elide_width: int | None = None

    def fontMetrics(self) -> _RecordingPainter:
        return self

    def elidedText(self, text: str, mode: Qt.TextElideMode, width: int) -> str:
        self.elide_width = width
        return text


def test_delete_icon_draws_a_centered_bin_with_two_handle_lines(qtbot: QtBot) -> None:
    delegate = _delegate(qtbot)
    painter = _RecordingPainter()

    delegate._paint_icon(painter, QRect(40, 20, 18, 18), "delete")  # noqa: SLF001

    assert painter.calls_for("drawLine") == [
        (43, 24, 53, 24),
        (47, 27, 47, 31),
        (49, 27, 49, 31),
    ]
    assert painter.calls_for("drawRect") == [(45, 24, 6, 1)]
    assert painter.calls_for("drawRoundedRect") == [(44, 25, 8, 8, 1, 1)]


def test_rename_icon_path_keeps_its_tapered_pencil_geometry(qtbot: QtBot) -> None:
    delegate = _delegate(qtbot)
    painter = _RecordingPainter()

    delegate._paint_icon(painter, QRect(40, 20, 18, 18), "rename")  # noqa: SLF001

    path = painter.calls_for("drawPath")[0][0]
    expected = (
        (42.93935, 30.93935),
        (45.06065, 33.06065),
        (50.3639, 27.7574),
        (52.4852, 23.5148),
        (48.2426, 25.6361),
    )
    assert path.elementCount() == 6
    for element, (x, y) in zip(range(5), expected, strict=True):
        point = path.elementAt(element)
        assert (point.x, point.y) == pytest.approx((x, y))


@pytest.mark.parametrize(
    ("hovered", "expected_text_rect"),
    [
        (False, QRect(30, 0, 181, 32)),
        (True, QRect(30, 0, 135, 32)),
    ],
)
def test_paint_places_text_and_uses_left_vertical_alignment(
    qtbot: QtBot, hovered: bool, expected_text_rect: QRect
) -> None:
    delegate = _delegate(qtbot)
    model = model_support.TagListModel()
    model.set_tags([model_support.Tag(id=7, name="seven")], frozenset())
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 220, 32)
    option.state = QStyle.StateFlag.State_MouseOver if hovered else QStyle.StateFlag.State_None
    painter = _RecordingPainter()

    delegate.paint(painter, option, model.index(0, 0))

    ((text_rect, alignment, text),) = painter.calls_for("drawText")
    assert text_rect == expected_text_rect
    assert alignment == Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
    assert text == "seven"


def test_paint_ignores_indexes_with_non_integer_tag_ids(qtbot: QtBot) -> None:
    delegate = _delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 220, 32)
    painter = _RecordingPainter()

    class InvalidTagIndex:
        def data(self, role: int) -> object:
            return "not an id" if role == model_support.TagIdRole else "name"

    delegate.paint(painter, option, InvalidTagIndex())  # type: ignore[arg-type]

    assert painter.calls_for("drawText") == []


def test_inline_editor_geometry_starts_after_the_checkbox(qtbot: QtBot) -> None:
    delegate = _delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(7, 11, 220, 34)

    model_support.assert_editor_geometry(delegate, option, QRect(37, 13, 181, 30))


def _build_shortcut_delegate(
    qtbot: QtBot, *, show_shortcuts: bool = False
) -> tuple[QListView, model_support.TagRowDelegate]:
    view = QListView()
    qtbot.addWidget(view)
    return (view, model_support.TagRowDelegate(view, view, show_shortcuts=show_shortcuts))


def test_shortcut_configuration_updates_only_when_the_value_changes(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    view, delegate = _build_shortcut_delegate(qtbot)
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
    assert delegate._shortcut_labels == {0: "Q", 1: "F11"}


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


def test_shortcut_paint_uses_checked_or_unchecked_slots_and_elides_long_labels(
    qtbot: QtBot,
) -> None:
    view, delegate = _build_shortcut_delegate(qtbot, show_shortcuts=True)
    model = _model()
    delegate.set_shortcut_labels({1: "F11"})
    painter = RecordingPainter()
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
    painter = RecordingPainter()
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
    _view, delegate = _build_shortcut_delegate(qtbot)
    assert delegate._rects(row_rect) == expected


def test_size_hint_preserves_the_row_width_and_fixed_height(qtbot: QtBot) -> None:
    _view, delegate = _build_shortcut_delegate(qtbot)
    option = _paint_option(QRect(0, 0, 257, 41))
    assert delegate.sizeHint(option, QModelIndex()).width() == 257
    assert delegate.sizeHint(option, QModelIndex()).height() == 32


def test_checked_and_hovered_paint_states_use_the_expected_background_and_checkbox(
    qtbot: QtBot,
) -> None:
    _view, delegate = _build_shortcut_delegate(qtbot)
    model = _model()
    row_rect = QRect(0, 0, 240, 32)
    checked_painter = RecordingPainter()
    delegate.paint(checked_painter, _paint_option(row_rect, hovered=True), model.index(0, 0))
    assert checked_painter.calls_for("fillRect")
    assert checked_painter.calls_for("fillPath")
    assert len(checked_painter.calls_for("drawPath")) == 1
    assert len(checked_painter.calls_for("drawText")) == 1
    unchecked_painter = RecordingPainter()
    delegate.paint(unchecked_painter, _paint_option(row_rect, hovered=True), model.index(1, 0))
    assert len(unchecked_painter.calls_for("drawPath")) == 2
    assert unchecked_painter.calls_for("fillPath") == []
    assert len(unchecked_painter.calls_for("drawText")) == 1
    assert len(unchecked_painter.calls_for("drawLine")) == 3


def test_editor_event_rejects_bad_ids_and_non_release_events(qtbot: QtBot) -> None:
    _view, delegate = _build_shortcut_delegate(qtbot)
    option = _paint_option(QRect(0, 0, 220, 32))
    release = left_mouse_release_at(QPointF(40, 16))

    class InvalidIndex:
        def data(self, role: int) -> object:
            return "not an integer" if role == model_support.TagIdRole else None

    toggled: list[int] = []
    delegate.toggle_requested.connect(toggled.append)
    assert (
        delegate.editorEvent(release, model_support.TagListModel(), option, InvalidIndex()) is False
    )
    assert (
        delegate.editorEvent(
            QEvent(QEvent.Type.KeyPress), model_support.TagListModel(), option, QModelIndex()
        )
        is False
    )
    assert toggled == []


def test_enter_commits_and_escape_reverts_a_delegate_editor(qtbot: QtBot) -> None:
    view, delegate = _build_shortcut_delegate(qtbot)
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
    assert closed[-1] == (editor, QStyledItemDelegate.EndEditHint.RevertModelCache)


def test_inline_editor_geometry_uses_the_row_inset_and_padding(qtbot: QtBot) -> None:
    _view, delegate = _build_shortcut_delegate(qtbot)
    option = _paint_option(QRect(12, 25, 241, 39))
    model_support.assert_editor_geometry(delegate, option, QRect(42, 27, 202, 35))


def _tag_delegate(qtbot: QtBot) -> tuple[QListView, TagListModel, TagRowDelegate]:
    view = QListView()
    qtbot.addWidget(view)
    model = TagListModel()
    model.set_tags([Tag(id=7, name="kittens")], frozenset())
    view.setModel(model)
    delegate = TagRowDelegate(view, view)
    view.setItemDelegate(delegate)
    return view, model, delegate


def test_tag_row_editor_is_prefilled_and_blank_renames_are_ignored(qtbot: QtBot) -> None:
    view, model, delegate = _tag_delegate(qtbot)
    index = model.index(0, 0)
    editor = delegate.createEditor(view, QStyleOptionViewItem(), index)
    renamed: list[tuple[int, str]] = []
    delegate.rename_committed.connect(lambda tag_id, name: renamed.append((tag_id, name)))

    delegate.setEditorData(editor, index)
    assert editor.text() == "kittens"

    editor.setText("   ")
    delegate.setModelData(editor, model, index)

    assert renamed == []
    assert model.data(index) == "kittens"


def test_tag_row_escape_reverts_the_inline_editor(qtbot: QtBot) -> None:
    view, model, delegate = _tag_delegate(qtbot)
    editor = delegate.createEditor(view, QStyleOptionViewItem(), model.index(0, 0))
    closed: list[tuple[object, ...]] = []
    delegate.closeEditor.connect(lambda *args: closed.append(args))
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)

    assert delegate.eventFilter(editor, event) is True
    assert closed == [(editor, QStyledItemDelegate.EndEditHint.RevertModelCache)]


def test_tag_row_editor_ignores_a_rename_for_an_invalid_tag_id(qtbot: QtBot) -> None:
    view, model, delegate = _tag_delegate(qtbot)
    editor = delegate.createEditor(view, QStyleOptionViewItem(), model.index(0, 0))
    editor.setText("new name")

    class InvalidIdIndex:
        def data(self, role: int) -> object:
            return "invalid" if role == TagIdRole else None

    renamed: list[tuple[int, str]] = []
    delegate.rename_committed.connect(lambda tag_id, name: renamed.append((tag_id, name)))

    delegate.setModelData(editor, model, InvalidIdIndex())  # type: ignore[arg-type]

    assert renamed == []


def test_tag_row_delegate_consumes_a_delete_click(qtbot: QtBot) -> None:
    _view, model, delegate = _tag_delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 240, 32)
    delete_rect = delegate._rects(option.rect)[2]  # noqa: SLF001 - target the delete affordance
    position = QPointF(delete_rect.center())
    event = left_mouse_release_at(position)
    deleted: list[int] = []
    delegate.delete_requested.connect(deleted.append)

    consumed = delegate.editorEvent(event, model, option, model.index(0, 0))
    qtbot.waitUntil(lambda: deleted == [7], timeout=1000)

    assert consumed is True


def test_tag_row_paint_uses_expected_delete_icon_geometry(qtbot: QtBot) -> None:
    _view, _model, delegate = _tag_delegate(qtbot)
    painter = RecordingCalls()

    delegate._paint_icon(painter, QRect(1, 1, 18, 18), "delete")  # noqa: SLF001

    assert painter.calls_for("drawLine") == [
        (4, 5, 14, 5),
        (8, 8, 8, 12),
        (10, 8, 10, 12),
    ]
    assert painter.calls_for("drawRect") == [(6, 5, 6, 1)]
    assert painter.calls_for("drawRoundedRect") == [(5, 6, 8, 8, 1, 1)]


def test_tag_row_paint_preserves_border_strokes_and_text_width(qtbot: QtBot) -> None:
    _view, model, delegate = _tag_delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 241, 32)
    painter = RecordingPainter()

    delegate.paint(painter, option, model.index(0, 0))

    checkbox_path = painter.calls_for("drawPath")[0][0]
    assert checkbox_path.elementAt(0).y == 12
    assert checkbox_path.contains(QPointF(10, 9))
    assert painter.calls_for("setPen")[0][0].widthF() == 1.5
    assert painter.metrics.widths == [202]

    delete_painter = RecordingCalls()
    delegate._paint_icon(delete_painter, QRect(1, 1, 18, 18), "delete")  # noqa: SLF001
    assert delete_painter.calls_for("setPen")[0][0].widthF() == 1.6
