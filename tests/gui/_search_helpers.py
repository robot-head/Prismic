"""Assertions for search-box state shared across tag-panel tests."""

from PySide6.QtWidgets import QLineEdit


def assert_search_box_is_empty(search_box: QLineEdit, *, keeps_focus: bool) -> None:
    assert search_box.text() == ""
    assert search_box.hasFocus() is keeps_focus
