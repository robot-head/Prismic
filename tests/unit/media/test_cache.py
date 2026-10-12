from pathlib import Path

from PySide6.QtGui import QImage
from pytestqt.qtbot import QtBot

from prismic.media.cache import ImageCache
from prismic.media.image import ImageLoadError, load_image


def _load(fixtures_dir: Path, name: str) -> QImage:
    result = load_image(fixtures_dir / name)
    assert not isinstance(result, ImageLoadError)
    return result


def test_put_then_get_round_trips(qtbot: QtBot, fixtures_dir: Path) -> None:
    image = _load(fixtures_dir, "supported_image.png")
    cache = ImageCache()

    cache.put("a", image)

    assert cache.get("a") is image
    assert len(cache) == 1
    assert cache.current_bytes == image.sizeInBytes()


def test_get_on_a_missing_key_returns_none() -> None:
    cache = ImageCache()

    assert cache.get("missing") is None


def test_put_replacing_an_existing_key_updates_the_byte_count(
    qtbot: QtBot, fixtures_dir: Path
) -> None:
    small = _load(fixtures_dir, "supported_image.png")
    large = _load(fixtures_dir, "large_image.png")
    cache = ImageCache()

    cache.put("a", small)
    cache.put("a", large)

    assert len(cache) == 1
    assert cache.current_bytes == large.sizeInBytes()


def test_eviction_drops_the_least_recently_used_entry_once_over_budget(
    qtbot: QtBot, fixtures_dir: Path
) -> None:
    image = _load(fixtures_dir, "supported_image.png")
    # A budget that fits exactly two of this image but not three.
    cache = ImageCache(max_bytes=image.sizeInBytes() * 2)

    cache.put("first", image)
    cache.put("second", image)
    cache.put("third", image)

    assert len(cache) == 2
    assert cache.get("first") is None  # evicted, least recently used
    assert cache.get("second") is not None
    assert cache.get("third") is not None


def test_get_marks_an_entry_as_recently_used_protecting_it_from_eviction(
    qtbot: QtBot, fixtures_dir: Path
) -> None:
    image = _load(fixtures_dir, "supported_image.png")
    cache = ImageCache(max_bytes=image.sizeInBytes() * 2)

    cache.put("first", image)
    cache.put("second", image)
    cache.get("first")  # touch: now more recently used than "second"
    cache.put("third", image)

    assert cache.get("first") is not None
    assert cache.get("second") is None  # evicted instead
    assert cache.get("third") is not None


def test_default_image_cache_budget_is_256_mib() -> None:
    assert ImageCache().max_bytes == 256 * 1024 * 1024
