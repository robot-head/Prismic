from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from prismic.application.input.shortcuts import QUICK_SELECT_SLOT_COUNT
from prismic.domain.tag import Tag
from prismic.ui.tag_model import CheckedRole, TagIdRole, TagListModel, UncheckedSlotRole
from tests.gui import _tag_model_support as model_support


def test_tag_model_roles_keep_their_documented_qt_user_role_offsets() -> None:
    user_role = Qt.ItemDataRole.UserRole

    assert model_support.TagIdRole == user_role + 1
    assert model_support.CheckedRole == user_role + 2
    assert model_support.UncheckedSlotRole == user_role + 3
    assert model_support.CheckedSlotRole == user_role + 4


def test_tag_slots_are_group_relative_capped_and_reversible(qtbot: QtBot) -> None:
    model = model_support.TagListModel()
    tags = [
        model_support.Tag(id=row + 1, name=f"tag {row}")
        for row in range(QUICK_SELECT_SLOT_COUNT * 2 + 4)
    ]
    selected_ids = frozenset(tag.id for row, tag in enumerate(tags) if row % 2 == 0)
    model.set_tags(tags, selected_ids)

    class EqualId(int):
        pass

    class EqualRole(int):
        pass

    unchecked_ids: list[int] = []
    checked_ids: list[int] = []
    for tag in tags:
        row = model.row_for_tag_id(tag.id)
        assert row is not None
        index = model.index(row, 0)
        is_checked = tag.id in selected_ids
        assert index.data(model_support.CheckedRole) is is_checked
        assert model.row_for_tag_id(EqualId(tag.id)) == row

        group_ids = checked_ids if is_checked else unchecked_ids
        role = model_support.CheckedSlotRole if is_checked else model_support.UncheckedSlotRole
        expected_slot = len(group_ids) if len(group_ids) < QUICK_SELECT_SLOT_COUNT else None
        assert index.data(role) == expected_slot
        assert model.data(index, EqualRole(int(role))) == expected_slot
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
    model = model_support.TagListModel()
    model.set_tags(
        [model_support.Tag(id=1, name="one"), model_support.Tag(id=2, name="two")], frozenset()
    )

    class OutOfRangeIndex:
        def isValid(self) -> bool:
            return True

        def __init__(self, row: int) -> None:
            self._row = row

        def row(self) -> int:
            return self._row

    for row in (-1, model.rowCount()):
        assert model.data(OutOfRangeIndex(row), model_support.TagIdRole) is None  # type: ignore[arg-type]
    assert model.rowCount(model.index(0, 0)) == 0


def test_tag_model_flags_allow_editing_only_for_valid_rows(qtbot: QtBot) -> None:
    model = model_support.TagListModel()
    model.set_tags([model_support.Tag(id=1, name="one")], frozenset())
    expected = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

    assert model.flags(model.index(0, 0)) == expected
    assert model.flags(model.index(-1, 0)) == Qt.ItemFlag.NoItemFlags


def test_tag_model_returns_none_for_unassigned_roles() -> None:
    model = TagListModel()
    model.set_tags([Tag(id=5, name="checked")], frozenset({5}))
    index = model.index(0, 0)

    assert index.data(TagIdRole) == 5
    assert index.data(CheckedRole) is True
    assert index.data(UncheckedSlotRole) is None
    assert model.data(index, Qt.ItemDataRole.UserRole) is None
    assert model.data(index, Qt.ItemDataRole.UserRole + 5) is None


def test_tag_model_lookups_require_exact_ids_and_nonnegative_slots() -> None:
    model = TagListModel()
    model.set_tags(
        [Tag(id=20, name="first"), Tag(id=5, name="selected"), Tag(id=15, name="last")],
        frozenset({5}),
    )

    assert model.row_for_tag_id(5) == 1
    assert model.tag_id_for_slot(0, selected=False) == 20
    assert model.tag_id_for_slot(0, selected=True) == 5
    assert model.tag_id_for_slot(-1, selected=False) is None
    assert model.tag_id_for_slot(-1, selected=True) is None
