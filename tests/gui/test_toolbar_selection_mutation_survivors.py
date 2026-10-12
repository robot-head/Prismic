"""Regression coverage for toolbar and selection-grid paint geometry."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, QRectF
from PySide6.QtGui import QPainterPath, QPaintEvent, QPixmap

from prismic.ui import panel_toolbar, selection_grid_view
from prismic.ui.panel_toolbar import (
    FullScreenButton,
    PanelToolbar,
    RedoButton,
    ShuffleButton,
    UndoButton,
)
from prismic.ui.selection_grid_view import _MARGIN, _SPACING, SelectionGridView, _best_grid
from prismic.ui.thumbnail_provider import ThumbnailProvider


class _Pen:
    def color(self) -> str:
        return "icon-color"


class _Painter:
    """Small recorder for the geometric arguments passed to QPainter."""

    def __init__(self) -> None:
        self.paths: list[QPainterPath] = []
        self.polygons: list[object] = []
        self.lines: list[tuple[int, int, int, int]] = []
        self.pixmaps: list[tuple[object, QPixmap]] = []
        self.fills: list[tuple[object, object]] = []
        self.clip_paths: list[QPainterPath] = []
        self.pens: list[object] = []

    def setRenderHint(self, _hint: object) -> None:
        pass

    def pen(self) -> _Pen:
        return _Pen()

    def setPen(self, _pen: object) -> None:
        self.pens.append(_pen)

    def setBrush(self, _brush: object) -> None:
        pass

    def drawPath(self, path: QPainterPath) -> None:
        self.paths.append(path)

    def drawPolygon(self, polygon: object) -> None:
        self.polygons.append(polygon)

    def drawLine(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.lines.append((x1, y1, x2, y2))

    def save(self) -> None:
        pass

    def restore(self) -> None:
        pass

    def setClipPath(self, path: QPainterPath) -> None:
        self.clip_paths.append(path)

    def drawPixmap(self, point: object, pixmap: QPixmap) -> None:
        self.pixmaps.append((point, pixmap))

    def fillRect(self, rect: object, color: object) -> None:
        self.fills.append((rect, color))


class _EventPainter(_Painter):
    class RenderHint:
        Antialiasing = object()

    last: _EventPainter | None = None

    def __init__(self, *_args: object) -> None:
        super().__init__()
        _EventPainter.last = self

    def end(self) -> None:
        pass


def _path_points(path: QPainterPath) -> list[tuple[float, float]]:
    return [(path.elementAt(i).x, path.elementAt(i).y) for i in range(path.elementCount())]


def _polygon_points(polygon: object) -> list[tuple[int, int]]:
    return [(polygon.at(i).x(), polygon.at(i).y()) for i in range(polygon.count())]  # type: ignore[attr-defined]


def test_toolbar_icons_keep_their_size_and_point_the_chevrons_outward(qtbot) -> None:
    undo = UndoButton()
    redo = RedoButton()
    qtbot.addWidget(undo)
    qtbot.addWidget(redo)

    assert undo.size().width() == undo.size().height() == 22
    assert redo.size().width() == redo.size().height() == 22

    rect = QRect(10, 20, 40, 30)
    undo_painter = _Painter()
    redo_painter = _Painter()
    undo._paint_icon(undo_painter, rect)  # type: ignore[arg-type]
    redo._paint_icon(redo_painter, rect)  # type: ignore[arg-type]

    assert sum(_path_points(undo_painter.paths[0]), ()) == pytest.approx(
        (40.2, 23.8, 17.8, 34, 40.2, 44.2)
    )
    assert sum(_path_points(redo_painter.paths[0]), ()) == pytest.approx(
        (17.8, 23.8, 40.2, 34, 17.8, 44.2)
    )


def test_button_paints_inside_the_five_pixel_icon_margin(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    button = UndoButton()
    qtbot.addWidget(button)
    button.show()
    qtbot.waitExposed(button)
    painted_rects: list[QRect] = []
    monkeypatch.setattr(
        UndoButton,
        "_paint_icon",
        lambda _self, _painter, rect: painted_rects.append(rect),
    )
    monkeypatch.setattr(panel_toolbar, "QPainter", _EventPainter)

    button.paintEvent(QPaintEvent(button.rect()))

    assert painted_rects[-1] == QRect(5, 5, 12, 12)
    painter = _EventPainter.last
    assert painter is not None
    assert [pen.widthF() for pen in painter.pens] == [1.5]  # type: ignore[attr-defined]


def test_toolbar_layout_keeps_its_spacing_and_side_margins(qtbot) -> None:
    toolbar = PanelToolbar()
    qtbot.addWidget(toolbar)
    layout = toolbar.layout()
    assert layout is not None

    assert layout.contentsMargins().left() == 8
    assert layout.contentsMargins().right() == 8
    assert layout.contentsMargins().top() == layout.contentsMargins().bottom() == 0
    assert layout.spacing() == 6
    assert [layout.itemAt(i).widget() for i in range(4)] == [
        toolbar.undo_button,
        toolbar.redo_button,
        toolbar.shuffle_button,
        toolbar.fullscreen_button,
    ]


def test_shuffle_icon_draws_shallow_crossing_arrows_with_separated_heads(qtbot) -> None:
    painter = _Painter()
    ShuffleButton()._paint_icon(painter, QRect(10, 20, 40, 30))  # type: ignore[arg-type]

    assert len(painter.paths) == 2
    assert _path_points(painter.paths[0]) == pytest.approx(
        [(10, 44.36), (23.6, 44.36), (23.6, 24.64), (46, 24.64)]
    )
    assert _path_points(painter.paths[1]) == pytest.approx(
        [(10, 24.64), (23.6, 24.64), (23.6, 44.36), (46, 44.36)]
    )
    assert [_polygon_points(polygon) for polygon in painter.polygons] == [
        [(49, 25), (46, 22), (46, 27)],
        [(49, 44), (46, 42), (46, 47)],
    ]


def test_fullscreen_icon_draws_eight_corner_arms_of_the_expected_length(qtbot) -> None:
    painter = _Painter()
    FullScreenButton()._paint_icon(painter, QRect(1, 2, 19, 16))  # type: ignore[arg-type]

    assert painter.lines == [
        (1, 7, 1, 2),
        (1, 2, 6, 2),
        (14, 2, 19, 2),
        (19, 2, 19, 7),
        (1, 12, 1, 17),
        (1, 17, 6, 17),
        (14, 17, 19, 17),
        (19, 17, 19, 12),
    ]


def test_fullscreen_icon_keeps_a_three_pixel_minimum_arm(qtbot) -> None:
    painter = _Painter()
    FullScreenButton()._paint_icon(painter, QRect(0, 3, 6, 6))  # type: ignore[arg-type]

    assert painter.lines == [
        (0, 6, 0, 3),
        (0, 3, 3, 3),
        (2, 3, 5, 3),
        (5, 3, 5, 6),
        (0, 5, 0, 8),
        (0, 8, 3, 8),
        (2, 8, 5, 8),
        (5, 8, 5, 5),
    ]


def test_fullscreen_icon_uses_addition_for_non_aligned_coordinates(qtbot) -> None:
    painter = _Painter()
    FullScreenButton()._paint_icon(painter, QRect(1, 3, 19, 16))  # type: ignore[arg-type]

    assert painter.lines == [
        (1, 8, 1, 3),
        (1, 3, 6, 3),
        (14, 3, 19, 3),
        (19, 3, 19, 8),
        (1, 13, 1, 18),
        (1, 18, 6, 18),
        (14, 18, 19, 18),
        (19, 18, 19, 13),
    ]


@pytest.mark.parametrize(
    ("count", "width", "height"),
    [
        (count, width, height)
        for count in range(1, 15)
        for width, height in (
            (20, 20),
            (31, 47),
            (97, 61),
            (100, 30),
            (301, 211),
            (401, 401),
        )
    ],
)
def test_grid_uses_the_candidate_with_the_largest_fitting_cell(
    count: int, width: int, height: int
) -> None:
    available_w = max(1.0, width - 2 * _MARGIN)
    available_h = max(1.0, height - 2 * _MARGIN)
    candidates = [(min(available_w, available_h / count), 1, available_w, available_h / count)]
    for columns in range(1, count + 1):
        if columns == 1:
            continue
        rows = math.ceil(count / columns)
        cell_w = (available_w - (columns - 1) * _SPACING) / columns
        cell_h = (available_h - (rows - 1) * _SPACING) / rows
        if cell_w > 0 and cell_h > 0:
            candidates.append((min(cell_w, cell_h), columns, cell_w, cell_h))

    cols, cell_w, cell_h = _best_grid(count, width, height)
    assert cell_w > 0 and cell_h > 0
    expected = max(candidates, key=lambda candidate: candidate[0])
    assert (cols, cell_w, cell_h) == pytest.approx((expected[1], expected[2], expected[3]))


def test_grid_thumbnail_events_refresh_only_a_visible_item(qtbot) -> None:
    view = SelectionGridView(ThumbnailProvider(), lambda: None)
    qtbot.addWidget(view)
    updates: list[bool] = []
    view.update = lambda: updates.append(True)  # type: ignore[method-assign]
    view.set_items([(4, Path("a.jpg")), (9, Path("b.jpg"))])
    updates.clear()

    view._on_thumbnail_event(8)
    assert updates == []

    class EqualId(int):
        pass

    view._on_thumbnail_event(EqualId(9))
    assert updates == [True]


def test_grid_paints_cells_in_display_order_with_row_and_column_spacing(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = SelectionGridView(ThumbnailProvider(), lambda: None)
    qtbot.addWidget(view)
    view.resize(400, 300)
    items = [(media_id, Path(f"{media_id}.jpg")) for media_id in range(1, 6)]
    view.set_items(items)
    painted: list[tuple[int, QRectF]] = []
    view._paint_cell = lambda _painter, rect, media_id, _path: painted.append((media_id, rect))  # type: ignore[method-assign]
    monkeypatch.setattr(selection_grid_view, "QPainter", _EventPainter)

    view.paintEvent(QPaintEvent(view.rect()))

    assert [media_id for media_id, _rect in painted] == [1, 2, 3, 4, 5]
    assert sum(
        [(rect.x(), rect.y(), rect.width(), rect.height()) for _media_id, rect in painted],
        (),
    ) == pytest.approx(
        sum(
            [
                (12, 12, 121 + 1 / 3, 135),
                (12 + 127 + 1 / 3, 12, 121 + 1 / 3, 135),
                (12 + 2 * (127 + 1 / 3), 12, 121 + 1 / 3, 135),
                (12, 153, 121 + 1 / 3, 135),
                (12 + 127 + 1 / 3, 153, 121 + 1 / 3, 135),
            ],
            (),
        )
    )


def test_grid_thumbnail_dimension_uses_ceil_and_never_falls_below_one(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = SelectionGridView(ThumbnailProvider(), lambda: None)
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "devicePixelRatioF", lambda: 1.25)

    assert view._required_dimension(QRectF(0, 0, 100.1, 60.0)) == 126
    assert view._required_dimension(QRectF(0, 0, 0, 0)) == 1


@pytest.mark.parametrize(
    ("source_size", "expected_point", "expected_size"),
    [
        ((80, 20), (10, 37.5), (200, 50)),
        ((20, 80), (52.5, 20), (30, 120)),
    ],
)
def test_grid_centers_a_letterboxed_thumbnail_inside_its_cell(
    qtbot, monkeypatch, source_size, expected_point, expected_size
) -> None:
    provider = ThumbnailProvider()
    provider._cache[7] = QPixmap(*source_size)
    view = SelectionGridView(provider, lambda: None)
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "devicePixelRatioF", lambda: 2.0)
    painter = _Painter()

    view._paint_cell(painter, QRectF(10, 20, 100, 60), 7, Path("photo.jpg"))  # type: ignore[arg-type]

    expected_clip = QPainterPath()
    expected_clip.addRoundedRect(QRectF(10, 20, 100, 60), 6, 6)
    assert painter.clip_paths == [expected_clip]
    assert len(painter.pixmaps) == 1
    point, scaled = painter.pixmaps[0]
    assert (point.x(), point.y()) == pytest.approx(expected_point)  # type: ignore[attr-defined]
    assert (scaled.width(), scaled.height()) == expected_size


def test_grid_video_badge_uses_the_compact_grid_scale(qtbot, monkeypatch) -> None:
    view = SelectionGridView(ThumbnailProvider(), lambda: None)
    qtbot.addWidget(view)
    badge_calls: list[tuple[QRectF, float]] = []
    monkeypatch.setattr(
        selection_grid_view,
        "paint_play_badge",
        lambda _painter, rect, *, size_fraction: badge_calls.append((rect, size_fraction)),
    )
    rect = QRectF(12, 15, 100, 80)

    view._paint_cell(_Painter(), rect, 17, Path("clip.webm"))  # type: ignore[arg-type]

    assert badge_calls == [(rect, 0.16)]
