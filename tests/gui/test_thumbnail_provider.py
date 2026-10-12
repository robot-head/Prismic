"""Coverage for `ThumbnailProvider`'s per-request dimension: a cache hit
at a smaller decode size than what's now being asked for must trigger a
re-decode, since `SelectionGridView` relies on this to sharpen a cell's
thumbnail as it grows (a window resize, or a selection shrinking to
fewer, larger cells) rather than leaving it blurry at whatever size it
first decoded at.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPixmap
from pytestqt.qtbot import QtBot

from prismic.application.worker_pool import WorkerPool
from prismic.ui.main_window import MainWindow
from prismic.ui.thumbnail_provider import ThumbnailProvider
from prismic.ui.viewer import MediaViewer
from tests.gui._media_helpers import solid_image
from tests.gui.helpers import open_three_item_collection

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "media"


def make_provider_and_pool(*, dimension: int | None = None) -> tuple[ThumbnailProvider, WorkerPool]:
    provider = ThumbnailProvider() if dimension is None else ThumbnailProvider(dimension=dimension)
    return provider, WorkerPool()


def _provider_pool_and_path(dimension: int) -> tuple[ThumbnailProvider, WorkerPool, Path]:
    provider, pool = make_provider_and_pool(dimension=dimension)
    return (
        provider,
        pool,
        FIXTURES_DIR / "supported_image.png",
    )


def _load_thumbnail(
    qtbot: QtBot,
    provider: ThumbnailProvider,
    pool: WorkerPool,
    path: Path,
    dimension: int,
) -> QPixmap:
    provider.request(1, path, pool, dimension=dimension)
    qtbot.waitUntil(lambda: provider.get(1) is not None, timeout=5000)
    pixmap = provider.get(1)
    assert pixmap is not None
    return pixmap


def test_a_second_request_at_a_larger_dimension_replaces_the_cached_pixmap(qtbot: QtBot) -> None:
    provider, pool, path = _provider_pool_and_path(dimension=32)

    small = _load_thumbnail(qtbot, provider, pool, path, dimension=32)

    provider.request(1, path, pool, dimension=512)
    qtbot.waitUntil(
        lambda: (
            provider.get(1) is not None
            and (
                provider.get(1).width() > small.width() or provider.get(1).height() > small.height()
            )
        ),  # type: ignore[union-attr]
        timeout=5000,
    )

    pool.shutdown(wait=True)


def test_a_second_request_at_a_smaller_dimension_is_a_no_op(qtbot: QtBot) -> None:
    provider, pool, path = _provider_pool_and_path(dimension=512)

    large = _load_thumbnail(qtbot, provider, pool, path, dimension=512)

    provider.request(1, path, pool, dimension=32)

    # No decode was queued for the smaller size, so the cached pixmap is
    # untouched -- give any (incorrect) re-decode a moment to land, then
    # confirm it didn't.
    qtbot.wait(200)
    assert provider.get(1) is large

    pool.shutdown(wait=True)


def test_reset_clears_the_remembered_decode_size_too(qtbot: QtBot) -> None:
    provider, pool, path = _provider_pool_and_path(dimension=512)

    _load_thumbnail(qtbot, provider, pool, path, dimension=512)

    provider.reset()

    assert provider.get(1) is None
    # A fresh request at a small dimension must actually decode again,
    # not be treated as already-satisfied by the pre-reset large decode.
    _load_thumbnail(qtbot, provider, pool, path, dimension=32)

    pool.shutdown(wait=True)


@pytest.mark.parametrize(
    ("current_index", "direction", "neighbor_indexes"),
    [(0, 1, [1, 2]), (2, -1, [1, 0])],
    ids=["forward-from-first", "backward-from-last"],
)
def test_thumbnail_preloading_follows_direction_and_stays_within_display_order(
    qtbot: QtBot,
    window: MainWindow,
    collection_dir,
    monkeypatch: pytest.MonkeyPatch,
    current_index: int,
    direction: int,
    neighbor_indexes: list[int],
) -> None:
    session = open_three_item_collection(qtbot, window, collection_dir)
    display_order = list(session.state.result_set)
    media_paths = {
        media.id: session.collection.root / media.relative_path
        for media in session.media.list_all()
    }
    requested = []
    monkeypatch.setattr(window.viewer, "preload", requested.append)
    window._display_order = display_order  # noqa: SLF001
    window._nav_direction = direction  # noqa: SLF001

    window._preload_neighbors(display_order[current_index])  # noqa: SLF001

    assert requested == [media_paths[display_order[index]] for index in neighbor_indexes]


class _InlinePool:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def submit(self, function: Callable[..., object], *args: object) -> object:
        self.paths.append(args[-1])  # type: ignore[arg-type]
        return function(*args)


def test_preload_warms_images_and_skips_videos(qtbot: QtBot, monkeypatch) -> None:
    image = solid_image(3, 2)
    monkeypatch.setattr("prismic.media.loader.load_image", lambda _path: image)
    pool = _InlinePool()
    viewer = MediaViewer(worker_pool=lambda: pool)  # type: ignore[arg-type]
    qtbot.addWidget(viewer)
    photo = Path("photo.png")
    video = Path("clip.webm")

    viewer.preload(photo)
    viewer.preload(video)

    assert pool.paths == [photo]
    assert viewer._image_loader._cache.get(str(photo)) is not None  # noqa: SLF001


def test_preload_without_a_worker_pool_is_a_no_op(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    viewer.preload(Path("photo.png"))


def test_a_decode_for_an_old_generation_cannot_repopulate_the_cache(qtbot: QtBot) -> None:
    provider = ThumbnailProvider()
    stale_generation = provider._generation  # noqa: SLF001
    provider.reset()
    ready: list[int] = []
    provider.thumbnail_ready.connect(ready.append)
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(0x336699)

    provider._on_done(  # noqa: SLF001
        media_id=17,
        generation=stale_generation,
        dimension=32,
        image=image,
    )

    assert provider.get(17) is None
    assert ready == []


def test_a_request_for_one_pixel_still_starts_a_decode(qtbot: QtBot) -> None:
    submitted: list[tuple[object, ...]] = []

    class Pool:
        def submit(self, *args: object) -> Future[object]:
            submitted.append(args)
            return Future()

    provider = ThumbnailProvider()
    provider.request(4, Path("photo.png"), Pool(), dimension=1)  # type: ignore[arg-type]

    assert len(submitted) == 1
    assert submitted[0][-1] == 1


def test_request_without_a_dimension_caps_the_decode_at_160_pixels(
    qtbot: QtBot, tmp_path: Path
) -> None:
    source = QImage(400, 300, QImage.Format.Format_RGB32)
    source.fill(0x336699)
    image_path = tmp_path / "large.png"
    assert source.save(str(image_path))

    provider, pool = make_provider_and_pool()
    try:
        provider.request(1, image_path, pool)
        qtbot.waitUntil(lambda: provider.get(1) is not None, timeout=5000)

        pixmap = provider.get(1)
        assert pixmap is not None
        assert pixmap.size() == QSize(160, 120)
    finally:
        pool.shutdown(wait=True)
