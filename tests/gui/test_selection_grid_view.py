from __future__ import annotations

import math
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainterPath, QPaintEvent, QPixmap
from pytestqt.qtbot import QtBot

from prismic.application.worker_pool import WorkerPool
from prismic.ui import _thumbnail_badge, selection_grid_view, thumbnail_provider, thumbnail_services
from prismic.ui.selection_grid_view import _MARGIN, _SPACING, SelectionGridView, _best_grid
from prismic.ui.thumbnail_provider import ThumbnailProvider
from prismic.ui.thumbnail_services import ThumbnailServices


def test_a_single_cell_fills_the_whole_available_area() -> None:
    cols, cell_w, cell_h = _best_grid(1, 220, 120)

    assert cols == 1
    assert cell_w == 220 - 2 * 12  # width minus the two side margins
    assert cell_h == 120 - 2 * 12


def test_four_cells_in_a_square_area_form_a_two_by_two_grid() -> None:
    cols, cell_w, cell_h = _best_grid(4, 400, 400)

    assert cols == 2  # 2 cols x 2 rows -- the largest-cell arrangement for a square area
    assert cell_w > 0
    assert cell_h > 0


def test_a_wide_area_prefers_more_columns_than_a_tall_one_for_the_same_count() -> None:
    wide_cols, _wide_w, _wide_h = _best_grid(6, 1200, 300)
    tall_cols, _tall_w, _tall_h = _best_grid(6, 300, 1200)

    assert wide_cols > tall_cols


def test_every_arrangement_actually_fits_every_cell_on_screen() -> None:
    """The chosen (cols, cell size) must never let `rows * cell_h` or
    `cols * cell_w` exceed the available area -- the whole point of the
    search is picking an arrangement that fits, not just a large cell."""
    for count in range(1, 13):
        cols, cell_w, cell_h = _best_grid(count, 500, 350)
        rows = -(-count // cols)  # ceil division
        assert cols * cell_w <= 500 + 1  # +1 for float slop
        assert rows * cell_h <= 350 + 1


def test_grid_view_renders_without_crashing_and_requests_missing_thumbnails(
    qtbot: QtBot, tmp_path: Path
) -> None:
    (tmp_path / "a.jpg").write_bytes(b"not a real image, just needs to exist")
    (tmp_path / "b.jpg").write_bytes(b"not a real image, just needs to exist")

    provider = ThumbnailProvider()
    pool = WorkerPool()
    view = SelectionGridView(ThumbnailServices(provider, lambda: pool))
    qtbot.addWidget(view)
    view.resize(400, 300)

    view.set_items([(1, tmp_path / "a.jpg"), (2, tmp_path / "b.jpg")])
    view.show()
    qtbot.waitExposed(view)

    # Neither is cached yet, so painting should have kicked off a decode
    # request for each rather than raising.
    qtbot.waitUntil(lambda: provider.has_failed(1) or provider.get(1) is not None, timeout=5000)

    pool.shutdown(wait=True)


def test_a_non_matching_aspect_ratio_is_letterboxed_not_cropped(qtbot: QtBot) -> None:
    """The product's own ask: content is never cropped, even if it doesn't
    fill its grid cell neatly -- a very wide pixmap in a square-ish cell
    must come out scaled down on *both* axes (letterboxed), not scaled to
    exactly fill one axis while overflowing the other (which is what
    `KeepAspectRatioByExpanding`, the cropping mode, would produce)."""
    cols, cell_w, cell_h = _best_grid(1, 300, 300)
    assert cols == 1

    source = QPixmap(800, 100)
    scaled = source.scaled(
        int(cell_w),
        int(cell_h),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    assert scaled.width() <= cell_w
    assert scaled.height() <= cell_h

    # Sanity: render the real widget end-to-end with this same pixmap to
    # confirm nothing crashes along that path.
    provider = ThumbnailProvider()
    provider._cache[1] = source
    view = SelectionGridView(ThumbnailServices(provider, lambda: None))
    qtbot.addWidget(view)
    view.resize(300, 300)
    view.set_items([(1, Path("a.jpg"))])
    view.show()
    qtbot.waitExposed(view)


def test_the_requested_dimension_tracks_the_actual_cell_size(qtbot: QtBot, tmp_path: Path) -> None:
    """A cell's decode request must scale with how big the cell actually
    is on screen -- a fixed decode cap either blurs a large cell (a small
    selection in a big window) or wastes decode time on a small one (a
    big selection), which is exactly the blurriness this test guards
    against regressing."""
    (tmp_path / "a.jpg").write_bytes(b"not a real image, just needs to exist")

    provider = ThumbnailProvider()
    requested_dimensions: list[int] = []
    original_request = provider.request

    def spy_request(
        media_id: int, path: Path, worker_pool: object, dimension: int | None = None
    ) -> None:
        requested_dimensions.append(dimension)  # type: ignore[arg-type]

    provider.request = spy_request  # type: ignore[method-assign]

    pool = WorkerPool()
    view = SelectionGridView(ThumbnailServices(provider, lambda: pool))
    qtbot.addWidget(view)
    view.resize(1000, 1000)  # a single item gets a large cell
    view.set_items([(1, tmp_path / "a.jpg")])
    view.show()
    qtbot.waitExposed(view)
    qtbot.waitUntil(lambda: bool(requested_dimensions), timeout=2000)

    # Comfortably above the old fixed 640px cap this replaced -- the cell
    # at this window size is roughly 1000px minus margins.
    assert requested_dimensions[-1] > 640

    provider.request = original_request  # type: ignore[method-assign]
    pool.shutdown(wait=True)


def test_grid_keeps_a_candidate_with_one_pixel_cells() -> None:
    columns, cell_width, cell_height = _best_grid(2, 32, 1)

    assert columns == 2
    assert cell_width == 1
    assert cell_height == 1


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


def _grid_view(
    provider: thumbnail_provider.ThumbnailProvider | None = None,
) -> selection_grid_view.SelectionGridView:
    thumbnails = provider or thumbnail_provider.ThumbnailProvider()
    return selection_grid_view.SelectionGridView(
        thumbnail_services.ThumbnailServices(thumbnails, lambda: None)
    )


def _add_grid_view(
    qtbot, provider: thumbnail_provider.ThumbnailProvider | None = None
) -> selection_grid_view.SelectionGridView:
    view = _grid_view(provider)
    qtbot.addWidget(view)
    return view


def test_grid_thumbnail_events_refresh_only_a_visible_item(qtbot) -> None:
    view = _add_grid_view(qtbot)
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
        self.save_depth = 0

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
        self.save_depth += 1

    def restore(self) -> None:
        self.save_depth -= 1

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


def test_grid_paints_cells_in_display_order_with_row_and_column_spacing(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = _add_grid_view(qtbot)
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
    view = _add_grid_view(qtbot)
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
    provider = thumbnail_provider.ThumbnailProvider()
    provider._cache[7] = QPixmap(*source_size)
    view = _add_grid_view(qtbot, provider)
    monkeypatch.setattr(view, "devicePixelRatioF", lambda: 2.0)
    painter = _Painter()

    view._paint_cell(painter, QRectF(10, 20, 100, 60), 7, Path("photo.jpg"))  # type: ignore[arg-type]

    assert painter.save_depth == 0
    expected_clip = QPainterPath()
    expected_clip.addRoundedRect(QRectF(10, 20, 100, 60), 6, 6)
    assert painter.clip_paths == [expected_clip]
    assert len(painter.pixmaps) == 1
    point, scaled = painter.pixmaps[0]
    assert (point.x(), point.y()) == pytest.approx(expected_point)  # type: ignore[attr-defined]
    assert (scaled.width(), scaled.height()) == expected_size


def test_grid_video_badge_uses_the_compact_grid_scale(qtbot, monkeypatch) -> None:
    view = _add_grid_view(qtbot)
    badge_calls: list[tuple[QRectF, float]] = []
    monkeypatch.setattr(
        _thumbnail_badge,
        "paint_play_badge",
        lambda _painter, rect, *, size_fraction: badge_calls.append((rect, size_fraction)),
    )
    rect = QRectF(12, 15, 100, 80)

    view._paint_cell(_Painter(), rect, 17, Path("clip.webm"))  # type: ignore[arg-type]

    assert badge_calls == [(rect, 0.16)]
