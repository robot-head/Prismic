"""A passive Qt list model over a collection's tags.

Reused for two different purposes in the UI, each with a different notion
of "checked": the item-tags panel (checked = mapped to the current item)
and the filter panel (checked = part of the active filter). Which one a
given instance represents is entirely up to whatever supplies its
`selected_tag_ids` -- the model itself is agnostic.

Display-only, like `result_model.ResultListModel`: it never talks to the
database itself and holds no interaction logic of its own. Rows are
painted and clicked via `TagRowDelegate`/`TagPanel`, which read `TagIdRole`
and `CheckedRole` here and emit their own signals rather than writing back
through this model -- there is deliberately no `setData()`.

`UncheckedSlotRole`/`CheckedSlotRole` are computed here too (once, in
`set_tags()`) for the same reason `CheckedRole` is: this is the one place
that already knows each tag's checked state and the order it's displayed
in, so it's the natural place to number "the Nth unchecked tag" without a
second component re-deriving that split. Both roles are always populated
regardless of which panel this model backs -- the filter panel's delegate
just never reads them, since only the item-tags panel shows shortcut
numbers (see `MainWindow`).

They hold a quick-select *slot* (0-based position within the numbered
group), not the key that triggers it: which key that is comes from
`ShortcutBindings`, since every quick-select shortcut is individually
rebindable in Settings. Keeping the model on slots means rebinding one
never touches this file.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, Qt

from prismic.application.input.shortcuts import QUICK_SELECT_SLOT_COUNT
from prismic.domain.tag import Tag
from prismic.ui._identified_list_model import _IdentifiedListModel

_Index = QModelIndex | QPersistentModelIndex

TagIdRole = Qt.ItemDataRole.UserRole + 1
CheckedRole = Qt.ItemDataRole.UserRole + 2
# The quick-select slot (0-based) this tag occupies when the item-tags
# panel's shortcut numbering is limited to unchecked (or checked) tags --
# None past `QUICK_SELECT_SLOT_COUNT` tags in that state, or when this tag
# isn't in that state at all.
UncheckedSlotRole = Qt.ItemDataRole.UserRole + 3
CheckedSlotRole = Qt.ItemDataRole.UserRole + 4


def _slot_for_position(position: int) -> int | None:
    return position if position < QUICK_SELECT_SLOT_COUNT else None


class TagListModel(_IdentifiedListModel[Tag]):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._selected_tag_ids: frozenset[int] = frozenset()
        self._unchecked_slots: dict[int, int] = {}
        self._checked_slots: dict[int, int] = {}

    def set_tags(self, tags: list[Tag], selected_tag_ids: frozenset[int]) -> None:
        with self._model_reset():
            self._items = tags
            self._selected_tag_ids = selected_tag_ids
            self._unchecked_slots = {}
            self._checked_slots = {}
            unchecked_count = 0
            checked_count = 0
            for tag in tags:
                if tag.id in selected_tag_ids:
                    slot = _slot_for_position(checked_count)
                    if slot is not None:
                        self._checked_slots[tag.id] = slot
                    checked_count += 1
                else:
                    slot = _slot_for_position(unchecked_count)
                    if slot is not None:
                        self._unchecked_slots[tag.id] = slot
                    unchecked_count += 1

    def tag_id_for_slot(self, slot: int, *, selected: bool) -> int | None:
        """The tag currently occupying quick-select `slot` in the unchecked
        (or, with `selected=True`, checked) numbering -- the same mapping
        `data()` exposes per-row via `UncheckedSlotRole`/`CheckedSlotRole`,
        as one reverse lookup instead of a scan over every row."""
        table = self._checked_slots if selected else self._unchecked_slots
        for tag_id, bound_slot in table.items():
            if bound_slot == slot:
                return tag_id
        return None

    def tag_at(self, row: int) -> Tag:
        return self._item_at(row)

    def row_for_tag_id(self, tag_id: int) -> int | None:
        return self._row_for_id(tag_id)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        tag = self._item_for_index(index)
        if tag is None:
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return tag.name
        if role == TagIdRole:
            return tag.id
        if role == CheckedRole:
            return tag.id in self._selected_tag_ids
        if role == UncheckedSlotRole:
            return self._unchecked_slots.get(tag.id)
        if role == CheckedSlotRole:
            return self._checked_slots.get(tag.id)
        return None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
