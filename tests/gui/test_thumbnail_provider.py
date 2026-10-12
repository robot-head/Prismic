"""Coverage for `ThumbnailProvider`'s per-request dimension: a cache hit
at a smaller decode size than what's now being asked for must trigger a
re-decode, since `SelectionGridView` relies on this to sharpen a cell's
thumbnail as it grows (a window resize, or a selection shrinking to
fewer, larger cells) rather than leaving it blurry at whatever size it
first decoded at.
"""

from pathlib import Path

from PySide6.QtGui import QPixmap
from pytestqt.qtbot import QtBot

from prismic.application.worker_pool import WorkerPool
from prismic.ui.thumbnail_provider import ThumbnailProvider

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
