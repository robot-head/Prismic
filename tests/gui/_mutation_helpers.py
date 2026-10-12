"""Shared test doubles for Qt mutation-survivor coverage."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QByteArray, QEvent, QModelIndex, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QStyleOptionViewItem

from prismic.ui.instance_bridge import InstanceBridge


class SocketReply:
    def __init__(self, payload: bytes) -> None:
        self._payload = QByteArray(payload)

    def readAll(self) -> QByteArray:
        return self._payload

    def disconnectFromServer(self) -> None:
        pass


def assert_raise_not_requested(bridge: InstanceBridge, payload: bytes) -> None:
    received: list[bool] = []
    bridge.raise_requested.connect(lambda: received.append(True))

    bridge._on_ready_read(SocketReply(payload))  # noqa: SLF001 - exercise message validation

    assert received == []


class RecordingCalls:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __getattr__(self, name: str) -> Callable[..., None]:
        def record(*args: object) -> None:
            self.calls.append((name, args))

        return record

    def calls_for(self, name: str) -> list[tuple[object, ...]]:
        return [args for call_name, args in self.calls if call_name == name]


class _RecordingFontMetrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Qt.TextElideMode, int]] = []
        self.widths: list[int] = []

    def elidedText(self, text: str, mode: Qt.TextElideMode, width: int) -> str:
        self.calls.append((text, mode, width))
        self.widths.append(width)
        return text


class _RecordingFont:
    def __init__(self) -> None:
        self.pixel_size = 12
        self.bold = False

    def setPixelSize(self, size: int) -> None:
        self.pixel_size = size

    def setBold(self, bold: bool) -> None:
        self.bold = bold


class RecordingPainter(RecordingCalls):
    def __init__(self) -> None:
        super().__init__()
        self.metrics = _RecordingFontMetrics()
        self.font_value = _RecordingFont()

    def fontMetrics(self) -> _RecordingFontMetrics:
        return self.metrics

    def font(self) -> _RecordingFont:
        return self.font_value


def assert_editor_geometry(delegate: Any, option: QStyleOptionViewItem, expected: QRect) -> None:
    class Editor:
        geometry: QRect | None = None

        def setGeometry(self, geometry: QRect) -> None:
            self.geometry = geometry

    editor = Editor()
    delegate.updateEditorGeometry(editor, option, QModelIndex())
    assert editor.geometry == expected


def mouse_event(event_type: QEvent.Type, button: Qt.MouseButton) -> QMouseEvent:
    point = QPointF(1, 1)
    return QMouseEvent(
        event_type,
        point,
        point,
        point,
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


def left_mouse_release_at(position: QPointF) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        position,
        position,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def wheel_event(delta: int) -> QWheelEvent:
    position = QPointF(10, 10)
    return QWheelEvent(
        position,
        position,
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
