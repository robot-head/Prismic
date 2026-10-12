"""Default-size regression coverage for ThumbnailProvider."""

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from pytestqt.qtbot import QtBot

from tests.gui.test_thumbnail_provider import make_provider_and_pool


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
