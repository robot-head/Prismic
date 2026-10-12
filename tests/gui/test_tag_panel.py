from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from prismic.domain.tag import Tag
from prismic.ui.tag_panel import TagPanel

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


def test_enter_always_creates_even_when_a_filtered_match_exists(qtbot: QtBot) -> None:
    """Enter's outcome is exactly what was typed, never a row picked off
    the filtered list underneath -- even though "sun" fuzzy-matches
    "sunset" (and would sort first among the matches), Enter must create
    a literal "sun" tag, not toggle "sunset"."""
    panel = _make_panel(qtbot)
    toggled: list[int] = []
    created: list[str] = []
    panel.toggle_requested.connect(toggled.append)
    panel.create_and_check_requested.connect(created.append)

    panel.search_box.setText("sun")
    qtbot.keyClick(panel.search_box, Qt.Key.Key_Return)

    assert created == ["sun"]
    assert toggled == []
    assert panel.search_box.text() == ""


def test_enter_with_no_match_requests_create_and_check(qtbot: QtBot) -> None:
    panel = _make_panel(qtbot)
    created: list[str] = []
    panel.create_and_check_requested.connect(created.append)

    panel.search_box.setText("vacation")
    qtbot.keyClick(panel.search_box, Qt.Key.Key_Return)

    assert created == ["vacation"]
    assert panel.search_box.text() == ""


def test_enter_with_empty_search_does_nothing(qtbot: QtBot) -> None:
    panel = _make_panel(qtbot)
    toggled: list[int] = []
    created: list[str] = []
    panel.toggle_requested.connect(toggled.append)
    panel.create_and_check_requested.connect(created.append)

    qtbot.keyClick(panel.search_box, Qt.Key.Key_Return)

    assert toggled == []
    assert created == []


def test_clear_search_keep_focus_restores_focus_if_it_had_it(qtbot: QtBot) -> None:
    panel = _make_panel(qtbot)
    panel.show()
    qtbot.waitExposed(panel)
    panel.search_box.setText("sun")
    panel.search_box.setFocus()
    qtbot.waitUntil(lambda: panel.search_box.hasFocus(), timeout=1000)

    panel.clear_search_keep_focus()

    assert panel.search_box.text() == ""
    assert panel.search_box.hasFocus()


def test_clear_search_keep_focus_does_not_steal_focus_if_it_lacked_it(qtbot: QtBot) -> None:
    panel = _make_panel(qtbot)
    panel.show()
    qtbot.waitExposed(panel)
    panel.search_box.setText("sun")
    panel.list_view.setFocus()
    qtbot.waitUntil(lambda: panel.list_view.hasFocus(), timeout=1000)

    panel.clear_search_keep_focus()

    assert panel.search_box.text() == ""
    assert not panel.search_box.hasFocus()


def test_focus_search_gives_the_search_box_focus(qtbot: QtBot) -> None:
    panel = _make_panel(qtbot)
    panel.show()
    qtbot.waitExposed(panel)

    panel.focus_search()
    qtbot.waitUntil(lambda: panel.search_box.hasFocus(), timeout=1000)

    assert panel.search_box.hasFocus()
