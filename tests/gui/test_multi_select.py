"""End-to-end coverage for bulk file selection: additive shift/ctrl-click
in the result list, the tag-intersection editing it drives, and the grid
display that replaces the single-item viewer while more than one file is
selected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtCore
from pytestqt.qtbot import QtBot

from prismic.domain.tag import Tag
from prismic.ui.main_window import MainWindow
from tests.gui.helpers import checked_tag_names, open_and_wait, open_three_item_collection


def _select_both(window: MainWindow) -> tuple[int, int]:
    assert window.session is not None
    a_id, b_id = window.session.state.result_set
    window.session.state.current_item = b_id
    window.session.state.selected_items = frozenset({a_id, b_id})
    window._refresh_all()
    return a_id, b_id


def _create_common_tag(window: MainWindow, name: str) -> tuple[int, int, Tag]:
    session = window.session
    assert session is not None
    a_id, b_id = session.state.result_set
    window._on_tag_create(name)
    tag = session.tags.list_all()[0]
    session.mappings.add(a_id, tag.id)
    session.mappings.add(b_id, tag.id)
    return a_id, b_id, tag


def _click(
    qtbot: QtBot, window: MainWindow, row: int, modifier: QtCore.Qt.KeyboardModifier
) -> None:
    index = window.result_model.index(row, 0)
    window.result_list.scrollTo(index)
    qtbot.waitUntil(
        lambda: (
            window.result_list.visualRect(index).width() > 0
            and window.result_list.visualRect(index).height() > 0
        ),
        timeout=1000,
    )
    rect = window.result_list.visualRect(index)
    qtbot.mouseClick(
        window.result_list.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        modifier,
        pos=rect.center(),
    )


def _select_two_through_list(qtbot: QtBot, window: MainWindow) -> None:
    _click(qtbot, window, 0, QtCore.Qt.KeyboardModifier.NoModifier)
    _click(qtbot, window, 1, QtCore.Qt.KeyboardModifier.ControlModifier)


def _open_and_select_two_through_list(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    _select_two_through_list(qtbot, window)


@pytest.fixture
def two_selected_window(qtbot: QtBot, window: MainWindow, collection_dir: Path) -> MainWindow:
    _open_and_select_two_through_list(qtbot, window, collection_dir)
    return window


# -- The grid replaces the viewer for a multi-selection -----------------------


def test_selecting_two_items_shows_the_grid_instead_of_the_viewer(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)

    _select_both(window)

    assert window._media_stack.currentWidget() is window.selection_grid


def test_a_single_selection_shows_the_ordinary_viewer(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    a_id, _b_id = _select_both(window)

    window.session.state.current_item = a_id  # type: ignore[union-attr]
    window.session.state.selected_items = frozenset({a_id})  # type: ignore[union-attr]
    window._refresh_all()

    assert window._media_stack.currentWidget() is window.viewer


# -- Additive selection through real clicks on the result list ----------------


def test_ctrl_click_through_the_real_list_selects_both_and_shows_the_grid(
    two_selected_window: MainWindow,
) -> None:
    session = two_selected_window.session
    assert session is not None
    assert session.state.selected_items == frozenset(session.state.result_set)
    assert two_selected_window._media_stack.currentWidget() is two_selected_window.selection_grid


def test_ctrl_click_on_a_selected_row_deselects_it_and_falls_back_to_the_viewer(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    """Deselecting the row that was `current_item` (the just-clicked one)
    must not leave `current_item` pointing at a no-longer-selected id --
    it has to fall back to whatever's still selected, so single-item
    display resumes showing the right file."""
    open_and_wait(qtbot, window, collection_dir)
    first_id, _second_id = window.session.state.result_set  # type: ignore[union-attr]

    _click(qtbot, window, 0, QtCore.Qt.KeyboardModifier.NoModifier)
    _click(
        qtbot, window, 1, QtCore.Qt.KeyboardModifier.ControlModifier
    )  # both selected, row 1 current
    _click(qtbot, window, 1, QtCore.Qt.KeyboardModifier.ControlModifier)  # deselect row 1

    assert window.session.state.selected_items == frozenset({first_id})  # type: ignore[union-attr]
    assert window.session.state.current_item == first_id  # type: ignore[union-attr]
    assert window._media_stack.currentWidget() is window.viewer


def test_a_later_plain_click_collapses_back_to_a_single_item(
    qtbot: QtBot, two_selected_window: MainWindow
) -> None:
    _click(qtbot, two_selected_window, 0, QtCore.Qt.KeyboardModifier.NoModifier)

    session = two_selected_window.session
    assert session is not None
    assert session.state.selected_items == {session.state.result_set[0]}
    assert two_selected_window._media_stack.currentWidget() is two_selected_window.viewer


# -- Multi-select tag editing shows/writes the intersection -------------------


def test_multi_select_tag_panel_shows_only_tags_common_to_every_selected_file(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    a_id, _b_id, _kittens = _create_common_tag(window, "kittens")
    window._on_tag_create("beach")
    tags_by_name = {t.name: t.id for t in window.session.tags.list_all()}  # type: ignore[union-attr]
    window.session.mappings.add(a_id, tags_by_name["beach"])  # type: ignore[union-attr]  # only a has it

    _select_both(window)

    assert checked_tag_names(window) == {"kittens"}


def test_toggling_a_common_tag_removes_it_from_every_selected_file(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    a_id, b_id, kittens = _create_common_tag(window, "kittens")
    _select_both(window)

    window._on_item_tag_toggle(kittens.id)

    assert window.session.mappings.tags_for_media(a_id) == []  # type: ignore[union-attr]
    assert window.session.mappings.tags_for_media(b_id) == []  # type: ignore[union-attr]


def test_toggling_a_non_common_tag_adds_it_to_every_selected_file(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    """The product's own example: selecting "beach" while both files are
    selected and only one already has it must leave both with it."""
    open_and_wait(qtbot, window, collection_dir)
    a_id, b_id = window.session.state.result_set  # type: ignore[union-attr]
    window._on_tag_create("beach")
    beach = window.session.tags.list_all()[0]  # type: ignore[union-attr]
    window.session.mappings.add(a_id, beach.id)  # type: ignore[union-attr]  # only a has it
    _select_both(window)

    window._on_item_tag_toggle(beach.id)

    assert [t.id for t in window.session.mappings.tags_for_media(a_id)] == [beach.id]  # type: ignore[union-attr]
    assert [t.id for t in window.session.mappings.tags_for_media(b_id)] == [beach.id]  # type: ignore[union-attr]


def test_undoing_a_multi_select_add_is_one_step_and_only_reverts_what_changed(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    a_id, b_id = window.session.state.result_set  # type: ignore[union-attr]
    window._on_tag_create("beach")
    beach = window.session.tags.list_all()[0]  # type: ignore[union-attr]
    window.session.mappings.add(a_id, beach.id)  # type: ignore[union-attr]  # only a has it, going in
    _select_both(window)
    window._on_item_tag_toggle(beach.id)  # adds it to b too, one undo step

    window._undo()

    assert [t.id for t in window.session.mappings.tags_for_media(a_id)] == [beach.id]  # type: ignore[union-attr]
    assert window.session.mappings.tags_for_media(b_id) == []  # type: ignore[union-attr]


def test_multi_selection_grid_keeps_display_order_and_skips_unselected_items(
    qtbot: QtBot, window: MainWindow, collection_dir
) -> None:
    session = open_three_item_collection(qtbot, window, collection_dir)
    first, _middle, last = session.state.result_set
    session.state.current_item = first
    session.state.selected_items = frozenset({first, last})

    window._refresh_all()  # noqa: SLF001

    expected = [
        (media_id, session.collection.root / session.media.get(media_id).relative_path)
        for media_id in (first, last)
    ]
    assert window.selection_grid._items == expected  # noqa: SLF001
