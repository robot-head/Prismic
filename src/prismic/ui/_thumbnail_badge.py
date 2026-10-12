"""Shared painting for the video marker used on thumbnail widgets."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath

from prismic.ui import theme


def paint_play_badge(painter: QPainter, rect: QRectF, *, size_fraction: float) -> None:
    center = rect.center()
    radius = min(rect.width(), rect.height()) * size_fraction
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.THUMB_VIDEO_BADGE))
    painter.drawEllipse(center, radius, radius)
    triangle = QPainterPath()
    side = radius * 0.9
    triangle.moveTo(center.x() - side * 0.35, center.y() - side * 0.5)
    triangle.lineTo(center.x() - side * 0.35, center.y() + side * 0.5)
    triangle.lineTo(center.x() + side * 0.55, center.y())
    triangle.closeSubpath()
    painter.setBrush(QColor(theme.TEXT_PRIMARY))
    painter.drawPath(triangle)
