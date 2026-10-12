"""Boundary-pixel checks for the shared video play badge."""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from pytestqt.qtbot import QtBot

from prismic.ui import theme
from prismic.ui._thumbnail_badge import paint_play_badge


def test_play_triangle_keeps_its_expected_bounds(qtbot: QtBot) -> None:
    image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#ff00ff"))
    painter = QPainter(image)
    paint_play_badge(painter, QRectF(10, 20, 80, 60), size_fraction=0.25)
    painter.end()

    primary = QColor(theme.TEXT_PRIMARY)
    # The triangle has a narrow left edge, a 13.5px half-height, and a tip
    # just to the right of x=57. The surrounding pixels are inside the badge
    # circle but outside the glyph, so size and vertex changes remain visible.
    assert image.pixelColor(45, 50) == primary
    assert image.pixelColor(44, 50) != primary
    assert image.pixelColor(50, 44) != primary
    assert image.pixelColor(50, 55) != primary
    assert image.pixelColor(57, 50) != primary
    assert image.pixelColor(60, 50) != primary
