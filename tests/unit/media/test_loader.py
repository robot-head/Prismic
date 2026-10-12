from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from pytestqt.qtbot import QtBot

import prismic.media.loader as loader_module
from prismic.media.loader import ImageLoader, ImageLoadResult


def _fresh_request() -> tuple[ImageLoader, int]:
    loader = ImageLoader()
    return loader, loader.begin_request()


def _stale_request() -> tuple[ImageLoader, int]:
    loader = ImageLoader()
    request_id = loader.begin_request()
    loader.begin_request()
    return loader, request_id


def _load_fixture(
    fixtures_dir: Path, filename: str
) -> tuple[ImageLoader, int, ImageLoadResult | None]:
    loader, request_id = _fresh_request()
    result = loader.load(request_id, fixtures_dir / filename)
    return loader, request_id, result


def test_load_returns_the_decoded_image_for_a_fresh_request(
    qtbot: QtBot, fixtures_dir: Path
) -> None:
    _loader, request_id, result = _load_fixture(fixtures_dir, "supported_image.png")

    assert result is not None
    assert result.request_id == request_id
    assert result.error is None
    assert result.image is not None
    assert result.image.isNull() is False


def test_load_on_corrupt_content_returns_an_error_result_not_none(
    qtbot: QtBot, fixtures_dir: Path
) -> None:
    _loader, _request_id, result = _load_fixture(fixtures_dir, "corrupt_image.jpg")

    assert result is not None
    assert result.image is None
    assert result.error is not None


def test_load_with_an_already_stale_request_id_returns_none(
    fixtures_dir: Path,
) -> None:
    loader, stale_request_id = _stale_request()

    result = loader.load(stale_request_id, fixtures_dir / "supported_image.png")

    assert result is None


def test_load_discards_a_result_that_becomes_stale_during_decode(
    qtbot: QtBot, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same staleness protection, but for a request that was current
    when it started and only became stale while the (slow) decode was in
    flight -- exercising the post-decode recheck, not just the pre-decode
    one."""
    loader = ImageLoader()
    request_id = loader.begin_request()
    real_load_image = loader_module.load_image

    def _load_image_then_go_stale(path: Path) -> object:
        loader.begin_request()  # simulates a newer request arriving mid-decode
        return real_load_image(path)

    monkeypatch.setattr(loader_module, "load_image", _load_image_then_go_stale)

    result = loader.load(request_id, fixtures_dir / "supported_image.png")

    assert result is None


def test_load_caches_the_decoded_image_across_requests(qtbot: QtBot, fixtures_dir: Path) -> None:
    loader = ImageLoader()
    path = fixtures_dir / "supported_image.png"

    first = loader.load(loader.begin_request(), path)
    second = loader.load(loader.begin_request(), path)

    assert first is not None and second is not None
    assert first.image is second.image  # same cached QImage instance


def test_preload_warms_the_cache_so_a_later_load_never_redecodes(
    qtbot: QtBot, fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loader = ImageLoader()
    path = fixtures_dir / "supported_image.png"

    loader.preload(loader.begin_request(), path)

    call_count = 0
    real_load_image = loader_module.load_image

    def _counting_load_image(p: Path) -> object:
        nonlocal call_count
        call_count += 1
        return real_load_image(p)

    monkeypatch.setattr(loader_module, "load_image", _counting_load_image)

    result = loader.load(loader.begin_request(), path)

    assert result is not None
    assert result.image is not None
    assert call_count == 0  # served entirely from the preload-warmed cache


def test_preload_with_a_stale_request_id_does_nothing(fixtures_dir: Path) -> None:
    loader, stale_request_id = _stale_request()

    loader.preload(stale_request_id, fixtures_dir / "supported_image.png")

    assert len(loader._cache) == 0  # noqa: SLF001 - verifying the no-op directly


def test_rapid_navigation_only_the_final_request_ever_produces_a_result(
    qtbot: QtBot, fixtures_dir: Path
) -> None:
    """Simulates a user navigating past several items faster than they
    decode: only the last request in the burst should ever come back
    non-None -- none of the superseded ones may clobber "current"."""
    loader = ImageLoader()
    path = fixtures_dir / "supported_image.png"

    request_ids = [loader.begin_request() for _ in range(5)]
    results = [loader.load(request_id, path) for request_id in request_ids]

    assert results[:-1] == [None, None, None, None]
    assert results[-1] is not None
    assert results[-1].request_id == request_ids[-1]


def test_equal_but_distinct_request_ids_are_not_stale(qtbot: QtBot) -> None:
    loader = ImageLoader()
    request_id = 0
    for _ in range(300):
        request_id = loader.begin_request()
    equal_but_distinct_id = int(str(request_id))

    assert equal_but_distinct_id == request_id
    assert id(equal_but_distinct_id) != id(request_id)
    assert loader.is_stale(equal_but_distinct_id) is False


def test_default_loader_downsamples_to_2048_pixels(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoded = QImage(4096, 2048, QImage.Format.Format_RGB32)
    monkeypatch.setattr(loader_module, "load_image", lambda _path: decoded)
    loader = ImageLoader()

    result = loader.load(loader.begin_request(), tmp_path / "large.jpg")

    assert result is not None
    assert result.image is not None
    assert (result.image.width(), result.image.height()) == (2048, 1024)
