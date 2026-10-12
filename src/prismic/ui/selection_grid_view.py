"""A grid of every currently-selected item, shown instead of the
single-item `MediaViewer` whenever more than one file is selected in the
result list.

Cell size is picked by brute-force search over candidate column counts
(1..N): for each column count, the resulting row count is
`ceil(N / cols)`, and the cell size is bounded by whichever of
`width / cols` or `height / rows` is smaller -- the column count that
maximizes that bound is used, so cells end up as large as possible while
every one of them still fits on screen at once. Cell slots are uniform,
but each image is scaled with `KeepAspectRatio` (never `...ByExpanding`)
and centered within its slot rather than cropped -- the product ask was
explicit that no content may be cropped, even at the cost of letterboxed
gaps around non-matching aspect ratios. Not a "justified" mosaic that
sizes each cell to its image's own aspect ratio -- straightforward over
sophisticated, deliberately.

Thumbnail decoding is delegated to `ThumbnailProvider` -- the same
async, cached, worker-pool-backed decoder the result list's own
thumbnails use, but through its own separate cache/instance (see
`MainWindow.grid_thumbnail_provider`) and at a dimension computed per
cell, per paint (`_required_dimension`), rather than one fixed size:
a cell is anywhere from a shrunk-to-fit dozens-wide grid entry to
most of the window's height, and a fixed decode cap would either
blur the latter or waste decode time on the former. `request()`
no-ops once the cache already meets the size asked for, so re-painting
after a resize or a selection-count change only triggers a re-decode
when the cell actually grew past what's cached.
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import QWidget

from prismic.ui import theme
from prismic.ui._thumbnail_badge import paint_thumbnail
from prismic.ui.thumbnail_services import ThumbnailServices

_MARGIN = 12
_SPACING = 6

GRID_THUMBNAIL_DIMENSION = 640
"""Fallback/default decode dimension for the grid's `ThumbnailProvider`
instance (see `MainWindow.grid_thumbnail_provider`) -- unused in practice
by `SelectionGridView` itself, which always passes the actual on-screen
cell size (see `_required_dimension`) so thumbnails stay sharp whether a
cell ends up much smaller or much larger than this number. Kept as the
provider's constructor default so `get()`/`has_failed()` callers that
don't care about sizing still have a sane value."""


class SelectionGridView(QWidget):
    def __init__(
        self,
        thumbnails: ThumbnailServices,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("selectionGrid")
        self._thumbnails = thumbnails
        self._items: list[tuple[int, Path]] = []
        self._thumbnails.provider.thumbnail_ready.connect(self._on_thumbnail_event)
        self._thumbnails.provider.decode_failed.connect(self._on_thumbnail_event)

    def set_items(self, items: list[tuple[int, Path]]) -> None:
        """`items` is (media_id, absolute_path) pairs, in display order."""
        self._items = items
        self.update()

    def _on_thumbnail_event(self, media_id: int) -> None:
        if any(media_id == item_id for item_id, _ in self._items):
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.BG_CANVAS))

        if not self._items:
            painter.end()
            return

        cols, cell_w, cell_h = _best_grid(len(self._items), self.width(), self.height())
        for index, (media_id, path) in enumerate(self._items):
            row, col = divmod(index, cols)
            x = _MARGIN + col * (cell_w + _SPACING)
            y = _MARGIN + row * (cell_h + _SPACING)
            self._paint_cell(painter, QRectF(x, y, cell_w, cell_h), media_id, path)

        painter.end()

    def _paint_cell(self, painter: QPainter, rect: QRectF, media_id: int, path: Path) -> None:
        clip = QPainterPath()
        clip.addRoundedRect(rect, 6, 6)
        painter.save()
        painter.setClipPath(clip)

        pixmap = self._thumbnails.provider.get(media_id)
        is_video = self._thumbnails.is_video(path)

        scaled = None
        position = None
        if pixmap is not None:
            ratio = self.devicePixelRatioF()
            # Scale to the cell's *physical* pixel size (logical size times
            # DPI ratio), not `rect.size()` (logical) directly -- scaling
            # straight to logical size would throw away exactly the extra
            # resolution `_required_dimension` decoded for on a >1x display,
            # producing a pixmap Qt then has to re-stretch to fill the same
            # physical area, blurring it right back out. Setting the result's
            # own `devicePixelRatio` is what tells Qt those extra pixels are
            # real detail, not something to stretch.
            physical_size = (rect.size() * ratio).toSize()
            scaled = pixmap.scaled(
                physical_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(ratio)
            logical_size = scaled.deviceIndependentSize()
            x_off = rect.x() + (rect.width() - logical_size.width()) / 2
            y_off = rect.y() + (rect.height() - logical_size.height()) / 2
            position = QPointF(x_off, y_off)

        paint_thumbnail(
            painter,
            rect,
            scaled,
            position,
            is_video=is_video,
            size_fraction=0.16,
        )

        if not is_video and not self._thumbnails.provider.has_failed(media_id):
            # Requested every paint, not just when `pixmap is None`: a cell
            # that already has a thumbnail may still be under-resolution
            # for its *current* size (the window grew, or the selection
            # shrank to fewer, larger cells) -- `ThumbnailProvider.request`
            # is a no-op once the cached decode already meets this size.
            self._thumbnails.request(media_id, path, self._required_dimension(rect))

        painter.restore()

    def _required_dimension(self, rect: QRectF) -> int:
        ratio = self.devicePixelRatioF()
        return max(1, math.ceil(max(rect.width(), rect.height()) * ratio))


def _best_grid(count: int, width: int, height: int) -> tuple[int, float, float]:
    """The (columns, cell_width, cell_height) that fits `count` cells into
    a `width` x `height` area with the largest possible cell -- see this
    module's docstring for the search itself."""
    available_w = max(1.0, width - 2 * _MARGIN)
    available_h = max(1.0, height - 2 * _MARGIN)

    best_cols = 1
    best_cell_w = available_w
    best_cell_h = available_h / count
    best_score = min(best_cell_w, best_cell_h)

    for cols in range(2, count + 1):
        rows = math.ceil(count / cols)
        cell_w = (available_w - (cols - 1) * _SPACING) / cols
        cell_h = (available_h - (rows - 1) * _SPACING) / rows
        if cell_w <= 0 or cell_h <= 0:
            continue
        score = min(cell_w, cell_h)
        if score > best_score:
            best_score = score
            best_cols = cols
            best_cell_w = cell_w
            best_cell_h = cell_h

    return best_cols, best_cell_w, best_cell_h
