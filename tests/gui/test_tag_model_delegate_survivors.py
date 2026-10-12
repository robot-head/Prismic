from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QListView, QStyle, QStyleOptionViewItem
from pytestqt.qtbot import QtBot

from prismic.application.input.shortcuts import QUICK_SELECT_SLOT_COUNT
from prismic.domain.tag import Tag
from prismic.ui.tag_model import (
    CheckedRole,
    CheckedSlotRole,
    TagIdRole,
    TagListModel,
    UncheckedSlotRole,
)
from prismic.ui.tag_row_delegate import TagRowDelegate
from tests.gui._mutation_helpers import RecordingCalls, assert_editor_geometry


class _RecordingPainter(RecordingCalls):
    def __init__(self) -> None:
        super().__init__()
        self.elide_width: int | None = None

    def fontMetrics(self) -> _RecordingPainter:
        return self

    def elidedText(self, text: str, mode: Qt.TextElideMode, width: int) -> str:
        self.elide_width = width
        return text


def _delegate(qtbot: QtBot) -> TagRowDelegate:
    view = QListView()
    qtbot.addWidget(view)
    return TagRowDelegate(view, view)


def test_tag_model_roles_keep_their_documented_qt_user_role_offsets() -> None:
    user_role = Qt.ItemDataRole.UserRole

    assert TagIdRole == user_role + 1
    assert CheckedRole == user_role + 2
    assert UncheckedSlotRole == user_role + 3
    assert CheckedSlotRole == user_role + 4


def test_tag_slots_are_group_relative_capped_and_reversible(qtbot: QtBot) -> None:
    model = TagListModel()
    tags = [Tag(id=row + 1, name=f"tag {row}") for row in range(QUICK_SELECT_SLOT_COUNT * 2 + 2)]
    selected_ids = frozenset(tag.id for row, tag in enumerate(tags) if row % 2 == 0)
    model.set_tags(tags, selected_ids)

    unchecked_ids: list[int] = []
    checked_ids: list[int] = []
    for tag in tags:
        row = model.row_for_tag_id(tag.id)
        assert row is not None
        index = model.index(row, 0)
        is_checked = tag.id in selected_ids
        assert index.data(CheckedRole) is is_checked

        group_ids = checked_ids if is_checked else unchecked_ids
        role = CheckedSlotRole if is_checked else UncheckedSlotRole
        expected_slot = len(group_ids) if len(group_ids) < QUICK_SELECT_SLOT_COUNT else None
        assert index.data(role) == expected_slot
        # Integer role IDs cross Qt-facing code paths too; dispatch is by
        # value, not Python object identity.
        assert index.data(int(role)) == expected_slot
        group_ids.append(tag.id)

    for selected, ids in ((False, unchecked_ids), (True, checked_ids)):
        for slot, tag_id in enumerate(ids[:QUICK_SELECT_SLOT_COUNT]):
            assert model.tag_id_for_slot(slot, selected=selected) == tag_id
        assert model.tag_id_for_slot(QUICK_SELECT_SLOT_COUNT, selected=selected) is None
        # An int subclass compares equal to the stored slot without being the
        # same object. The reverse lookup must use equality.
        if ids:

            class EqualSlot(int):
                pass

            assert model.tag_id_for_slot(EqualSlot(0), selected=selected) == ids[0]


def test_tag_model_data_rejects_a_valid_looking_index_past_the_last_row() -> None:
    model = TagListModel()
    model.set_tags([Tag(id=1, name="one"), Tag(id=2, name="two")], frozenset())

    class OutOfRangeIndex:
        def isValid(self) -> bool:
            return True

        def row(self) -> int:
            return model.rowCount() + 1

    assert model.data(OutOfRangeIndex(), TagIdRole) is None  # type: ignore[arg-type]


def test_delegate_rects_use_the_row_geometry_and_center_the_controls(qtbot: QtBot) -> None:
    delegate = _delegate(qtbot)

    checkbox, rename, delete = delegate._rects(QRect(7, 11, 220, 34))  # noqa: SLF001

    assert checkbox == QRect(15, 20, 15, 15)
    assert rename == QRect(180, 19, 18, 18)
    assert delete == QRect(200, 19, 18, 18)


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
    model = TagListModel()
    model.set_tags([Tag(id=7, name="seven")], frozenset())
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
            return "not an id" if role == TagIdRole else "name"

    delegate.paint(painter, option, InvalidTagIndex())  # type: ignore[arg-type]

    assert painter.calls_for("drawText") == []


def test_inline_editor_geometry_starts_after_the_checkbox(qtbot: QtBot) -> None:
    delegate = _delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(7, 11, 220, 34)

    assert_editor_geometry(delegate, option, QRect(37, 13, 181, 30))
