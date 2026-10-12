"""Shared rendering setup for thumbnail badge pixel tests."""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from prismic.ui._thumbnail_badge import paint_play_badge


def render_play_badge() -> tuple[QImage, QColor]:
    background = QColor("#ff00ff")
    image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(background)
    painter = QPainter(image)
    paint_play_badge(painter, QRectF(10, 20, 80, 60), size_fraction=0.25)
    painter.end()
    return image, background
