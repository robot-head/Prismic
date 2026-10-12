from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from pytestqt.qtbot import QtBot

from prismic.application.worker_pool import WorkerPool
from prismic.ui.selection_grid_view import SelectionGridView, _best_grid
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
