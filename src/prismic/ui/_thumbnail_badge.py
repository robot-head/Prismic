"""Shared painting for the video marker used on thumbnail widgets."""

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap

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


def paint_thumbnail(
    painter: QPainter,
    rect: QRectF,
    scaled_pixmap: QPixmap | None,
    draw_position: QPoint | QPointF | None,
    *,
    is_video: bool,
    size_fraction: float = 0.26,
) -> None:
    if scaled_pixmap is None:
        painter.fillRect(rect, QColor(theme.THUMB_PLACEHOLDER))
    elif isinstance(draw_position, QPoint):
        painter.drawPixmap(draw_position.x(), draw_position.y(), scaled_pixmap)
    elif isinstance(draw_position, QPointF):
        painter.drawPixmap(draw_position, scaled_pixmap)
    else:
        raise ValueError("a scaled thumbnail needs its draw position")
    if is_video:
        paint_play_badge(painter, rect, size_fraction=size_fraction)
