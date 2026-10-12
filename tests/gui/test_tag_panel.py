import pytest
from PySide6.QtCore import QEvent, QMargins, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from prismic.domain.tag import Tag
from prismic.ui.tag_panel import TagPanel
from tests.gui._search_helpers import assert_search_box_is_empty

_TAGS = [Tag(id=1, name="kittens"), Tag(id=2, name="sunset"), Tag(id=3, name="sunrise")]


def _names(panel: TagPanel) -> list[str]:
    return [panel.model.tag_at(row).name for row in range(panel.model.rowCount())]


def _make_panel(
    qtbot: QtBot,
    tags: list[Tag] | None = None,
    checked: frozenset[int] = frozenset(),
) -> TagPanel:
    panel = TagPanel("Item tags")
    qtbot.addWidget(panel)
    panel.set_tags(_TAGS if tags is None else tags, checked)
    return panel


def test_checked_tags_are_sorted_to_the_top(qtbot: QtBot) -> None:
    panel = _make_panel(qtbot, checked=frozenset({2}))

    assert _names(panel) == ["sunset", "kittens", "sunrise"]


def test_search_narrows_only_the_unchecked_tags(qtbot: QtBot) -> None:
    panel = _make_panel(qtbot, checked=frozenset({2}))  # "sunset" checked

    panel.search_box.setText("sun")

    # "sunset" stays visible (checked, pinned) even though the query also
    # matches it; "sunrise" is the only *unchecked* match; "kittens" drops out.
    assert _names(panel) == ["sunset", "sunrise"]


def test_search_is_fuzzy_not_just_substring(qtbot: QtBot) -> None:
    panel = _make_panel(qtbot, [*_TAGS, Tag(id=4, name="vacation")])

    panel.search_box.setText("aion")

    # "aion" isn't a substring of "vacation" (v-A-c-a-t-I-O-N) -- only a
    # subsequence, in order but not contiguous. None of the other tags
    # contain a,i,o,n in order at all, so this only passes if matching is
    # genuinely fuzzy.
    assert _names(panel) == ["vacation"]


@pytest.mark.parametrize(
    ("query", "has_match"),
    [("sun", True), ("vacation", False), ("", False)],
    ids=["matching-filtered-row", "no-match", "empty-search"],
)
def test_enter_creates_the_typed_tag_without_toggling_a_filtered_row(
    qtbot: QtBot, query: str, has_match: bool
) -> None:
    """Enter creates exactly what was typed, even if the filtered list
    underneath contains a fuzzy match such as "sun" and "sunset"."""
    panel = _make_panel(qtbot)
    toggled: list[int] = []
    created: list[str] = []
    panel.toggle_requested.connect(toggled.append)
    panel.create_and_check_requested.connect(created.append)

    panel.search_box.setText(query)
    if query:
        assert bool(_names(panel)) is has_match
    qtbot.keyClick(panel.search_box, Qt.Key.Key_Return)

    assert created == ([query] if query else [])
    assert toggled == []
    assert panel.search_box.text() == ""


@pytest.mark.parametrize("focus_search", [True, False], ids=["had-focus", "did-not-have-focus"])
def test_clear_search_preserves_whether_search_had_focus(qtbot: QtBot, focus_search: bool) -> None:
    panel = _make_panel(qtbot)
    panel.show()
    qtbot.waitExposed(panel)
    panel.search_box.setText("sun")
    focus_target = panel.search_box if focus_search else panel.list_view
    focus_target.setFocus()
    qtbot.waitUntil(lambda: focus_target.hasFocus(), timeout=1000)

    panel.clear_search_keep_focus()

    assert_search_box_is_empty(panel.search_box, keeps_focus=focus_search)


def test_focus_search_gives_the_search_box_focus(qtbot: QtBot) -> None:
    panel = _make_panel(qtbot)
    panel.show()
    qtbot.waitExposed(panel)

    panel.focus_search()
    qtbot.waitUntil(lambda: panel.search_box.hasFocus(), timeout=1000)

    assert panel.search_box.hasFocus()


def test_tag_panel_reports_hovered_row_from_viewport_event(qtbot: QtBot) -> None:
    panel = TagPanel("Item tags")
    qtbot.addWidget(panel)
    panel.resize(260, 180)
    panel.set_tags([Tag(id=11, name="vacation")], frozenset())
    assert panel._delegate._show_shortcuts is False
    panel.show()
    qtbot.waitExposed(panel)
    row_rect = panel.list_view.visualRect(panel.model.index(0, 0))
    assert row_rect.isValid()
    rows: list[int | None] = []
    panel.hover_row_changed.connect(rows.append)
    position = QPointF(row_rect.center())
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        position,
        position,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )

    panel.eventFilter(panel.list_view.viewport(), event)

    assert rows == [0]


def test_tag_panel_keeps_header_spacing_and_stretches_the_tag_list(qtbot: QtBot) -> None:
    panel = TagPanel("Item tags")
    qtbot.addWidget(panel)

    assert panel.header.layout().contentsMargins() == QMargins(0, 0, 0, 0)
    assert panel.header.layout().spacing() == 0
    assert panel.layout().contentsMargins() == QMargins(0, 0, 0, 0)
    assert panel.layout().spacing() == 0
    assert panel.layout().stretch(1) == 1


def test_tag_panel_tracks_viewport_mouse_and_keeps_parent_keyword_usable(qtbot: QtBot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    panel = TagPanel("Item tags", parent=parent, show_shortcuts=True)

    assert panel.parentWidget() is parent
    assert panel.list_view.viewport().hasMouseTracking()
