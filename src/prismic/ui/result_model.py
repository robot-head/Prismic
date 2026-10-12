"""A Qt list model over the current query result set.

Display-only, like `tag_model.TagListModel` — it just reflects whatever
`set_media()` is given (the application layer's `ApplicationState.result_set`,
resolved to `Media` rows by the caller), in the order it's given, which is
already the deterministic relative-path order the query layer guarantees.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt

from prismic.domain.media import Media
from prismic.ui._identified_list_model import _IdentifiedListModel

_Index = QModelIndex | QPersistentModelIndex

MediaIdRole = Qt.ItemDataRole.UserRole + 1


class ResultListModel(_IdentifiedListModel[Media]):
    def set_media(self, media: list[Media]) -> None:
        self._reset_items(media)

    def media_at(self, row: int) -> Media:
        return self._item_at(row)

    def row_for_media_id(self, media_id: int) -> int | None:
        return self._row_for_id(media_id)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        media = self._item_for_index(index)
        if media is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return media.relative_path
        if role == MediaIdRole:
            return media.id
        return None
