from pathlib import Path

from PySide6.QtGui import QImage
from pytestqt.qtbot import QtBot

from prismic.media.image import ImageLoadError, downsample, load_image


def test_load_image_decodes_a_supported_image(qtbot: QtBot, fixtures_dir: Path) -> None:
    result = load_image(fixtures_dir / "supported_image.png")

    assert not isinstance(result, ImageLoadError)
    assert result.isNull() is False
    assert result.size().width() == 64
    assert result.size().height() == 64


def test_load_image_on_corrupt_data_returns_a_handled_error(
    qtbot: QtBot, fixtures_dir: Path
) -> None:
    result = load_image(fixtures_dir / "corrupt_image.jpg")

    assert isinstance(result, ImageLoadError)
    assert "corrupt_image.jpg" in result.reason


def test_load_image_on_a_missing_file_returns_a_handled_error(qtbot: QtBot, tmp_path: Path) -> None:
    result = load_image(tmp_path / "does_not_exist.png")

    assert isinstance(result, ImageLoadError)


def test_load_image_on_unsupported_content_returns_a_handled_error(
    qtbot: QtBot, fixtures_dir: Path
) -> None:
    """Extension filtering is the Phase 2 scanner's job, not this
    function's — but attempting to decode a plain-text file as an image
    should still fail cleanly rather than crash, as a defensive backstop."""
    result = load_image(fixtures_dir / "unsupported.txt")

    assert isinstance(result, ImageLoadError)


def test_downsample_is_a_no_op_when_already_within_bounds(qtbot: QtBot, fixtures_dir: Path) -> None:
    image = load_image(fixtures_dir / "supported_image.png")
    assert not isinstance(image, ImageLoadError)

    result = downsample(image, max_dimension=1024)

    assert result.size() == image.size()


def test_downsample_scales_down_a_large_image_preserving_aspect_ratio(
    qtbot: QtBot, fixtures_dir: Path
) -> None:
    image = load_image(fixtures_dir / "large_image.png")
    assert not isinstance(image, ImageLoadError)
    original_aspect = image.width() / image.height()

    result = downsample(image, max_dimension=500)

    assert max(result.width(), result.height()) <= 500
    assert result.width() < image.width()
    assert result.height() < image.height()
    new_aspect = result.width() / result.height()
    assert abs(new_aspect - original_aspect) < 0.01


def test_downsample_keeps_an_image_unchanged_at_the_dimension_boundary(qtbot: QtBot) -> None:
    for width, height in ((64, 32), (32, 64)):
        image = QImage(width, height, QImage.Format.Format_RGB32)

        assert downsample(image, max_dimension=64) is image


def test_downsample_scales_when_only_one_dimension_exceeds_the_bound(qtbot: QtBot) -> None:
    image = QImage(300, 100, QImage.Format.Format_RGB32)

    result = downsample(image, max_dimension=200)

    assert result.width() == 200
    assert result.height() < 100
