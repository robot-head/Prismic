"""Shared paint operations used by item delegates."""

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter

from prismic.ui import theme


def paint_selection_wash(
    painter: QPainter, rect: QRect | QRectF, *, selected: bool, hovered: bool
) -> None:
    if selected:
        painter.fillRect(rect, QColor(theme.SELECTED_WASH))
    elif hovered:
        painter.fillRect(rect, QColor(theme.HOVER_WASH))


def draw_elided_item_text(
    painter: QPainter, text: str, rect: QRect | QRectF, max_width: int
) -> None:
    elided = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, max_width)
    painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
