"""Small layout builders for the app's zero-margin widget stacks."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import QVBoxLayout, QWidget


def vertical_stack(
    parent: QWidget, widgets: Iterable[QWidget], *, stretch_index: int | None = None
) -> QVBoxLayout:
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if index == stretch_index else 0)
    return layout
