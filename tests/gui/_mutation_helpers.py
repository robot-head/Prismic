"""Shared test doubles for Qt mutation-survivor coverage."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QModelIndex, QRect
from PySide6.QtWidgets import QStyleOptionViewItem


class RecordingCalls:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __getattr__(self, name: str) -> Callable[..., None]:
        def record(*args: object) -> None:
            self.calls.append((name, args))

        return record

    def calls_for(self, name: str) -> list[tuple[object, ...]]:
        return [args for call_name, args in self.calls if call_name == name]


def assert_editor_geometry(delegate: Any, option: QStyleOptionViewItem, expected: QRect) -> None:
    class Editor:
        geometry: QRect | None = None

        def setGeometry(self, geometry: QRect) -> None:
            self.geometry = geometry

    editor = Editor()
    delegate.updateEditorGeometry(editor, option, QModelIndex())
    assert editor.geometry == expected
