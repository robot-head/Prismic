"""Minimal painter doubles shared by delegate contract tests."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter


class _FontMetrics:
    def elidedText(self, text: str, _mode: Qt.TextElideMode, _width: int) -> str:
        return text


class PaintStub:
    def save(self) -> None:
        pass

    def restore(self) -> None:
        pass

    def setRenderHint(self, _hint: QPainter.RenderHint) -> None:
        pass

    def setPen(self, _pen: object) -> None:
        pass

    def fontMetrics(self) -> _FontMetrics:
        return _FontMetrics()

    def drawText(self, _rect: QRectF, _alignment: Qt.AlignmentFlag, _text: str) -> None:
        pass

    def setClipPath(self, _path: object) -> None:
        pass

    def drawPixmap(self, _x: int, _y: int, _pixmap: object) -> None:
        pass

    def fillRect(self, _rect: QRectF, _color: object) -> None:
        pass
