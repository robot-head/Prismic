"""A Qt list model over the current query result set.

Display-only, like `tag_model.TagListModel` — it just reflects whatever
`set_media()` is given (the application layer's `ApplicationState.result_set`,
resolved to `Media` rows by the caller), in the order it's given, which is
already the deterministic relative-path order the query layer guarantees.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QPersistentModelIndex, Qt

from prismic.domain.media import Media
from prismic.ui._model_utils import find_row_by_id, top_level_row_count

_Index = QModelIndex | QPersistentModelIndex

MediaIdRole = Qt.ItemDataRole.UserRole + 1


class ResultListModel(QAbstractListModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._media: list[Media] = []

    def set_media(self, media: list[Media]) -> None:
        self.beginResetModel()
        self._media = media
        self.endResetModel()

    def media_at(self, row: int) -> Media:
        return self._media[row]

    def row_for_media_id(self, media_id: int) -> int | None:
        return find_row_by_id(self._media, media_id)

    def rowCount(self, parent: _Index | None = None) -> int:
        return top_level_row_count(parent, len(self._media))

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not (0 <= index.row() < len(self._media)):
            return None
        media = self._media[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return media.relative_path
        if role == MediaIdRole:
            return media.id
        return None
