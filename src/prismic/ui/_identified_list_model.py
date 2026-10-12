"""Shared storage and row operations for identified Qt list models."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QPersistentModelIndex

from prismic.ui._model_utils import _HasId, find_row_by_id, top_level_row_count

_Index = QModelIndex | QPersistentModelIndex


class _IdentifiedListModel[Item: _HasId](QAbstractListModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[Item] = []

    def _reset_items(self, items: list[Item]) -> None:
        with self._model_reset():
            self._items = items

    @contextmanager
    def _model_reset(self) -> Iterator[None]:
        self.beginResetModel()
        try:
            yield
        finally:
            self.endResetModel()

    def _item_at(self, row: int) -> Item:
        return self._items[row]

    def _item_for_index(self, index: _Index) -> Item | None:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        return self._items[index.row()]

    def _row_for_id(self, item_id: int) -> int | None:
        return find_row_by_id(self._items, item_id)

    def rowCount(self, parent: _Index | None = None) -> int:
        return top_level_row_count(parent, len(self._items))
