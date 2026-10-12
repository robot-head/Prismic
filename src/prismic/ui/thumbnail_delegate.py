"""Paints each result-list row as a thumbnail + relative path.

A `QStyledItemDelegate` rather than a widget-per-row: the result set can be
large, and Qt's model/view delegates are exactly the mechanism the
architecture calls for here (overview section 11, "use Qt model/view
abstractions for potentially large ... result collections"). Selection and
hover are painted here too, deliberately replacing the view's own default
(see `ui/theme.py`'s `QListView#resultList::item` rules, which blank the
default painting out) so the accent wash and the thumbnail share one
consistent look.

Thumbnail decoding itself is `ThumbnailProvider`'s job; this class only
asks for one when painting a row that doesn't have one cached yet, and
repaints that row once it arrives.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from prismic.ui import theme
from prismic.ui._delegate_painting import draw_elided_item_text, paint_selection_wash
from prismic.ui._thumbnail_badge import paint_thumbnail
from prismic.ui.result_model import MediaIdRole
from prismic.ui.thumbnail_services import ThumbnailServices

_Index = QModelIndex | QPersistentModelIndex

_ROW_HEIGHT = 64
_COMPACT_ROW_HEIGHT = 32
_THUMB_SIZE = 48
_MARGIN = 8


class ThumbnailDelegate(QStyledItemDelegate):
    def __init__(
        self,
        thumbnails: ThumbnailServices,
        resolve_path: Callable[[int], Path | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._thumbnails = thumbnails
        self._resolve_path = resolve_path
        # Off by default -- thumbnails cost a decode per file, and the
        # plain filename list is the lighter-weight, always-available
        # option (View > Show Thumbnails opts in). Toggled by MainWindow;
        # this delegate owns the flag since it's the one that decides row
        # height and whether to paint/request a thumbnail at all.
        self.show_thumbnails = False

    def sizeHint(self, option: QStyleOptionViewItem, index: _Index) -> QSize:
        height = _ROW_HEIGHT if self.show_thumbnails else _COMPACT_ROW_HEIGHT
        return QSize(option.rect.width(), height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        media_id = index.data(MediaIdRole)
        name = index.data(Qt.ItemDataRole.DisplayRole)
        if not isinstance(media_id, int) or not isinstance(name, str):
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        paint_selection_wash(painter, rect, selected=selected, hovered=hovered)

        if self.show_thumbnails:
            thumb_rect = QRectF(
                rect.x() + _MARGIN,
                rect.y() + (rect.height() - _THUMB_SIZE) / 2,
                _THUMB_SIZE,
                _THUMB_SIZE,
            )
            self._paint_thumbnail(painter, thumb_rect, media_id, name)
            text_x = thumb_rect.right() + _MARGIN + 4
        else:
            text_x = rect.x() + _MARGIN

        text_rect = QRectF(text_x, rect.y(), rect.right() - text_x - _MARGIN, rect.height())
        painter.setPen(QPen(QColor(theme.TEXT_PRIMARY)))
        draw_elided_item_text(painter, name, text_rect, int(text_rect.width()))

        painter.restore()

    def _paint_thumbnail(self, painter: QPainter, rect: QRectF, media_id: int, name: str) -> None:
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.save()
        painter.setClipPath(path)

        pixmap = self._thumbnails.provider.get(media_id)
        is_video = self._thumbnails.is_video(name)

        scaled = None
        position = None
        if pixmap is not None:
            scaled = pixmap.scaled(
                rect.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off = rect.x() - (scaled.width() - rect.width()) / 2
            y_off = rect.y() - (scaled.height() - rect.height()) / 2
            position = QPoint(int(x_off), int(y_off))

        paint_thumbnail(
            painter=painter,
            rect=rect,
            scaled_pixmap=scaled,
            draw_position=position,
            is_video=is_video,
        )
        if pixmap is None and not is_video and not self._thumbnails.provider.has_failed(media_id):
            self._request_thumbnail(media_id, name)

        painter.restore()

    def _request_thumbnail(self, media_id: int, name: str) -> None:
        path = self._resolve_path(media_id)
        if path is None:
            return
        self._thumbnails.request(media_id, path)
