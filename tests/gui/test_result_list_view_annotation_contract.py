from typing import get_type_hints

from PySide6.QtWidgets import QWidget

from prismic.ui.result_list_view import ResultListView


def test_constructor_parent_annotation_resolves_to_optional_widget() -> None:
    assert get_type_hints(ResultListView.__init__)["parent"] == QWidget | None
