from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from pytestqt.qtbot import QtBot

from prismic.application.input import shortcuts
from prismic.application.session import PrismicSession
from prismic.ui.main_window import MainWindow
from prismic.ui.settings_dialog import SettingsDialog


def _focus(qtbot: QtBot, widget: QWidget) -> None:
    widget.setFocus()
    qtbot.waitUntil(lambda: widget.hasFocus(), timeout=1000)


def _focus_item_tag_search(qtbot: QtBot, window: MainWindow) -> None:
    _focus(qtbot, window.item_tag_panel.search_box)


def _navigate_right_to(qtbot: QtBot, window: MainWindow, media_id: int) -> None:
    _focus(qtbot, window.result_list)
    qtbot.keyClick(window.result_list, Qt.Key.Key_Right)
    session = window.session
    assert session is not None
    assert session.state.current_item == media_id


def _set_current_item(window: MainWindow, index: int = 0) -> tuple[PrismicSession, int]:
    session = window.session
    assert session is not None
    media_id = session.state.result_set[index]
    session.state.current_item = media_id
    return session, media_id


def _set_first_of_two_results(window: MainWindow) -> tuple[PrismicSession, int, int]:
    session, first_id = _set_current_item(window)
    second_id = session.state.result_set[1]
    window._sync_result_selection()
    return session, first_id, second_id


def _tap_modifier(qtbot: QtBot, widget: QWidget, key: Qt.Key = Qt.Key.Key_Control) -> None:
    qtbot.keyPress(widget, key)
    qtbot.keyRelease(widget, key)


def _tap_modifier_and_expect_mode(qtbot: QtBot, window: MainWindow, expected: bool) -> None:
    _tap_modifier(qtbot, window.result_list)
    assert window._tag_shortcut_mode_action.isChecked() is expected


def _trigger_modifier_tap(qtbot: QtBot, window: MainWindow) -> None:
    _focus(qtbot, window.result_list)
    _tap_modifier(qtbot, window.result_list)


def _click_and_expect_focus(qtbot: QtBot, clicked: QWidget, expected: QWidget) -> None:
    qtbot.mouseClick(clicked, Qt.MouseButton.LeftButton)
    assert expected.hasFocus()


def _assert_focus_mode_exited(window: MainWindow) -> None:
    assert window._focus_mode_action.isChecked() is False
    assert window.result_list.isVisible()


def _create_one_tag(window: MainWindow, name: str = "vacation") -> PrismicSession:
    session = window.session
    assert session is not None
    window._on_tag_create(name)
    assert len(session.tags.list_all()) == 1
    return session


def _press_shortcut_and_read_tags(
    qtbot: QtBot, window: MainWindow, current_id: int, key: Qt.Key
) -> list[int]:
    qtbot.keyClick(window.result_list, key)
    session = window.session
    assert session is not None
    return [tag.id for tag in session.mappings.tags_for_media(current_id)]


def _capture_settings_exec(monkeypatch: pytest.MonkeyPatch) -> list[SettingsDialog]:
    opened: list[SettingsDialog] = []

    def capture(dialog: SettingsDialog) -> int:
        opened.append(dialog)
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", capture)
    return opened


def _create_current_tags(window: MainWindow, *names: str) -> tuple[PrismicSession, int]:
    session, media_id = _set_current_item(window)
    for name in names:
        window._on_tag_create(name)
    return session, media_id


def _first_unselected_tag(window: MainWindow) -> tuple[PrismicSession, int, int]:
    session, current_id = _create_current_tags(window, "a")
    tag_id = window.item_tag_panel.model.tag_id_for_slot(0, selected=False)
    assert tag_id is not None
    return session, current_id, tag_id


def _enter_focus_mode(qtbot: QtBot, window: MainWindow) -> None:
    _focus(qtbot, window.result_list)
    qtbot.keyClick(window.result_list, Qt.Key.Key_Space)
    assert window._focus_mode_action.isChecked() is True


def _show_two_item_history(qtbot: QtBot, window: MainWindow) -> tuple[PrismicSession, int, int]:
    session, first_id, second_id = _set_first_of_two_results(window)
    window._show_current_media()
    qtbot.keyClick(window, Qt.Key.Key_Right)
    return session, first_id, second_id


@pytest.fixture
def window(qtbot: QtBot, collection_dir: Path) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win.open_collection(collection_dir)
    qtbot.waitUntil(lambda: win.result_model.rowCount() == 2, timeout=5000)
    return win


@pytest.mark.parametrize(
    ("key", "current_index", "expected_index"),
    [
        (Qt.Key.Key_Right, 0, 1),
        (Qt.Key.Key_Down, 0, 1),
        (Qt.Key.Key_Left, 1, 0),
        (Qt.Key.Key_Up, 1, 0),
    ],
)
def test_arrow_keys_navigate_between_items(
    qtbot: QtBot,
    window: MainWindow,
    key: Qt.Key,
    current_index: int,
    expected_index: int,
) -> None:
    session = window.session
    assert session is not None
    expected_id = session.state.result_set[expected_index]
    session.state.current_item = session.state.result_set[current_index]
    window._sync_result_selection()

    qtbot.keyClick(window, key)

    assert session.state.current_item == expected_id


def test_up_down_navigate_even_while_a_tag_search_box_has_focus(
    qtbot: QtBot, window: MainWindow
) -> None:
    """Unlike every other global shortcut, Up/Down deliberately aren't
    exempted while text-editing has focus -- they have no meaning in a
    single-line box (unlike Left/Right, which move the caret), so result-
    list navigation should stay reachable no matter where the caret is."""
    session, first_id, second_id = _set_first_of_two_results(window)

    _focus(qtbot, window.item_tag_panel.search_box)

    qtbot.keyClick(window.item_tag_panel.search_box, Qt.Key.Key_Down)
    assert session.state.current_item == second_id

    qtbot.keyClick(window.item_tag_panel.search_box, Qt.Key.Key_Up)
    assert session.state.current_item == first_id

    # A plain letter, by contrast, must still land in the box as text --
    # confirms the exemption is narrowly scoped to Up/Down, not blanket.
    qtbot.keyClick(window.item_tag_panel.search_box, Qt.Key.Key_A)
    assert window.item_tag_panel.search_box.text() == "a"


def test_navigation_does_not_go_past_the_ends(qtbot: QtBot, window: MainWindow) -> None:
    session, second_id = _set_current_item(window, index=1)
    window._sync_result_selection()

    qtbot.keyClick(window, Qt.Key.Key_Right)  # already at the last item

    assert session.state.current_item == second_id


def test_navigation_with_no_current_item_selects_the_first(
    qtbot: QtBot, window: MainWindow
) -> None:
    session = window.session
    assert session is not None
    session.state.current_item = None

    qtbot.keyClick(window, Qt.Key.Key_Right)

    assert session.state.current_item == session.state.result_set[0]


@pytest.mark.parametrize(("redo", "expected_count"), [(False, 0), (True, 1)], ids=["undo", "redo"])
def test_undo_and_redo_shortcuts_update_tag_history(
    qtbot: QtBot, window: MainWindow, redo: bool, expected_count: int
) -> None:
    session = _create_one_tag(window)

    qtbot.keyClick(window, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    if redo:
        qtbot.keyClick(window, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)

    assert len(session.tags.list_all()) == expected_count


def test_undo_and_redo_do_not_touch_a_focused_search_box_while_reverting_tag_history(
    qtbot: QtBot, window: MainWindow
) -> None:
    """Ctrl+Z/Ctrl+Y must never fall through to a focused `QLineEdit`'s
    own built-in text-undo -- they're global tag-history commands, not
    text-editing ones, no matter what has focus."""
    session = _create_one_tag(window)

    _focus(qtbot, window.item_tag_panel.search_box)
    qtbot.keyClicks(window.item_tag_panel.search_box, "abc")
    assert window.item_tag_panel.search_box.text() == "abc"

    search_box = window.item_tag_panel.search_box
    qtbot.keyClick(search_box, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert session.tags.list_all() == []  # the tag-history undo fired
    assert search_box.text() == "abc"  # the typed text is untouched

    qtbot.keyClick(search_box, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert len(session.tags.list_all()) == 1  # the tag-history redo fired
    assert search_box.text() == "abc"  # still untouched


def test_global_shortcuts_still_work_when_the_result_list_has_focus(
    qtbot: QtBot, window: MainWindow
) -> None:
    """Regression test for a bug a computer-use pass caught: QAbstractItemView
    has its own built-in "type to search" behavior that swallows a plain
    letter key before it would ever reach a keyPressEvent override on the
    window itself. Earlier tests all sent keys straight to `window`
    (`qtbot.keyClick(window, ...)`), which never exercised real Qt focus
    routing through a child widget and so never caught this. Fixed by
    intercepting keys via an application-level event filter instead.

    "Tab" immediately focuses the item-tag ("Edit this file") search box
    (see `KeyboardController`'s `on_focus_item_tags` wiring in
    `MainWindow`) -- typing a name there and pressing Enter is what
    actually creates (and applies) the tag, exercised in
    `test_main_window.py`. A second "Tab", once focus is already inside
    that box, cycles to the filter search box instead -- that redirect is
    `MainWindow.eventFilter`/`_cycle_tag_search_focus`'s doing, checked
    ahead of ever calling into `KeyboardController`. A third "Tab" is a
    hidden third step in that cycle: it dismisses typing focus back to the
    result list rather than looping straight back to the first box, so a
    Tab-Tab-Tab burst always ends up not typing, instead of still typing in
    a different search box."""
    _focus(qtbot, window.result_list)

    qtbot.keyClick(window.result_list, Qt.Key.Key_Tab)

    assert window.item_tag_panel.search_box.hasFocus()

    qtbot.keyClick(window.item_tag_panel.search_box, Qt.Key.Key_Tab)

    assert window.filter_panel.search_box.hasFocus()

    qtbot.keyClick(window.filter_panel.search_box, Qt.Key.Key_Tab)

    assert window.result_list.hasFocus()  # dismissed, not cycled back

    qtbot.keyClick(window.result_list, Qt.Key.Key_Tab)

    assert window.item_tag_panel.search_box.hasFocus()  # loop starts over


# -- A bare letter with nothing focused jumps straight into the Edit box --


@pytest.mark.parametrize(
    ("modifiers", "expected_text"),
    [
        (Qt.KeyboardModifier.NoModifier, "v"),
        (Qt.KeyboardModifier.ShiftModifier, "V"),
    ],
    ids=["lowercase", "capital"],
)
def test_letter_keys_redirect_into_the_edit_search_box(
    qtbot: QtBot, window: MainWindow, modifiers: Qt.KeyboardModifier, expected_text: str
) -> None:
    _focus(qtbot, window.result_list)

    qtbot.keyClick(window.result_list, Qt.Key.Key_V, modifiers)

    assert window.item_tag_panel.search_box.hasFocus()
    assert window.item_tag_panel.search_box.text() == expected_text


def test_a_modified_letter_key_does_not_hijack_typing(qtbot: QtBot, window: MainWindow) -> None:
    """Ctrl+F is bound to full screen by default -- it must still trigger
    that shortcut, not be swallowed as if it were plain "f" typed into the
    Edit box."""
    _focus(qtbot, window.result_list)

    qtbot.keyClick(window.result_list, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)

    assert window.isFullScreen()
    assert not window.item_tag_panel.search_box.hasFocus()
    assert window.item_tag_panel.search_box.text() == ""


def test_a_letter_key_does_not_hijack_typing_already_in_a_search_box(
    qtbot: QtBot, window: MainWindow
) -> None:
    """The redirect only fires with nothing already focused for text entry
    -- typing into the filter box, say, must keep landing there, not jump
    to the item-tag box mid-word."""
    _focus(qtbot, window.filter_panel.search_box)

    qtbot.keyClick(window.filter_panel.search_box, Qt.Key.Key_V)

    assert window.filter_panel.search_box.hasFocus()
    assert window.filter_panel.search_box.text() == "v"
    assert window.item_tag_panel.search_box.text() == ""


def test_a_letter_key_is_a_no_op_while_the_edit_panel_is_hidden_in_focus_mode(
    qtbot: QtBot, window: MainWindow
) -> None:
    _focus(qtbot, window.result_list)
    qtbot.keyClick(window.result_list, Qt.Key.Key_Space)  # enter Focus Mode
    assert not window.item_tag_panel.isVisible()

    qtbot.keyClick(window, Qt.Key.Key_V)

    assert window.item_tag_panel.search_box.text() == ""


def test_escape_dismisses_typing_focus_from_either_search_box(
    qtbot: QtBot, window: MainWindow
) -> None:
    for search_box in (window.item_tag_panel.search_box, window.filter_panel.search_box):
        _focus(qtbot, search_box)
        qtbot.keyClick(search_box, Qt.Key.Key_Escape)
        assert window.result_list.hasFocus()


# -- Clicking outside a text input or a button also dismisses typing focus --
# Real clicks where a real click is safe (nothing it lands on has a side
# effect of its own); the private method directly where it isn't, per
# each test's own comment.


def test_clicking_blank_panel_space_dismisses_typing_focus(
    qtbot: QtBot, window: MainWindow
) -> None:
    """The header (title + search box) has no click handling of its own,
    so a real click actually lands on it -- exactly the "blank space
    around 'Edit this file'" case."""
    _click_and_expect_focus(qtbot, window.item_tag_panel.header, window.result_list)


def test_clicking_the_other_panels_blank_space_also_dismisses(
    qtbot: QtBot, window: MainWindow
) -> None:
    _focus(qtbot, window.filter_panel.search_box)
    _click_and_expect_focus(qtbot, window.filter_panel.header, window.result_list)


def test_clicking_inside_the_focused_search_box_does_not_dismiss_it(
    qtbot: QtBot, window: MainWindow
) -> None:
    _focus_item_tag_search(qtbot, window)
    _click_and_expect_focus(
        qtbot, window.item_tag_panel.search_box, window.item_tag_panel.search_box
    )


def test_clicking_the_menu_bar_dismisses_typing_focus(qtbot: QtBot, window: MainWindow) -> None:
    """The menu bar itself, not one of its menus -- opening File or View
    for real would block this test in QMenu's own event loop until
    something dismissed it. `_dismiss_typing_focus_unless_clicking` is
    called directly instead, with the menu bar as the "clicked" widget,
    which is exactly what `eventFilter` would have passed it -- Qt
    delivers a `MouseButtonPress` on the bar itself before ever opening
    the menu that press was for."""
    _focus(qtbot, window.item_tag_panel.search_box)

    window._dismiss_typing_focus_unless_clicking(window.menuBar())

    assert window.result_list.hasFocus()


def test_clicking_a_button_does_not_dismiss_typing_focus(qtbot: QtBot, window: MainWindow) -> None:
    """A real click on the viewer's play/pause button would actually
    toggle playback -- an unrelated side effect this test has no reason
    to trigger, so the private method is exercised directly with that
    button as the "clicked" widget instead."""
    _focus(qtbot, window.item_tag_panel.search_box)

    window._dismiss_typing_focus_unless_clicking(window.viewer.play_pause_button)

    assert window.item_tag_panel.search_box.hasFocus()


def test_clicking_elsewhere_is_a_no_op_when_nothing_is_being_typed_into(
    qtbot: QtBot, window: MainWindow
) -> None:
    _click_and_expect_focus(qtbot, window.item_tag_panel.header, window.result_list)


def test_navigation_still_works_when_the_result_list_has_focus(
    qtbot: QtBot, window: MainWindow
) -> None:
    _session, _first_id, second_id = _set_first_of_two_results(window)
    _navigate_right_to(qtbot, window, second_id)


def test_space_toggles_focus_mode_hiding_every_panel_but_the_viewer(
    qtbot: QtBot, window: MainWindow
) -> None:
    assert window.result_list.isVisible()
    assert window._tag_splitter.isVisible()
    _enter_focus_mode(qtbot, window)
    assert window.result_list.isVisible() is False
    assert window._tag_splitter.isVisible() is False
    assert window.menuBar().isVisible() is False
    assert window.statusBar().isVisible() is False
    assert window.viewer.isVisible()  # the one thing that stays

    qtbot.keyClick(window.result_list, Qt.Key.Key_Space)

    assert window._focus_mode_action.isChecked() is False
    assert window.result_list.isVisible()
    assert window._tag_splitter.isVisible()


def test_escape_exits_focus_mode(qtbot: QtBot, window: MainWindow) -> None:
    _enter_focus_mode(qtbot, window)

    qtbot.keyClick(window.result_list, Qt.Key.Key_Escape)

    _assert_focus_mode_exited(window)


def test_opening_a_collection_resets_focus_mode(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    _enter_focus_mode(qtbot, window)

    window.open_collection(collection_dir)

    _assert_focus_mode_exited(window)


def test_digit_toggles_the_unselected_tag_numbered_with_it(
    qtbot: QtBot, window: MainWindow
) -> None:
    _session, current_id = _create_current_tags(window, "a", "b")
    assert window._tag_shortcut_mode_action.isChecked() is False  # unselected by default
    tag_id = window.item_tag_panel.model.tag_id_for_slot(0, selected=False)
    assert tag_id is not None

    _focus(qtbot, window.result_list)
    assert _press_shortcut_and_read_tags(qtbot, window, current_id, Qt.Key.Key_1) == [tag_id]


def test_quick_select_toggles_from_search_and_after_rebinding(
    qtbot: QtBot, window: MainWindow
) -> None:
    session, current_id, tag_id = _first_unselected_tag(window)

    for search_box in (window.item_tag_panel.search_box, window.filter_panel.search_box):
        _focus(qtbot, search_box)
        qtbot.keyClick(search_box, Qt.Key.Key_1)

        assert search_box.text() == ""  # the digit toggles its tag instead of being typed
        assert [t.id for t in session.mappings.tags_for_media(current_id)] == [tag_id]
        window._on_item_tag_toggle(tag_id)  # reset before testing the other search box

    rebind(window, shortcuts.quick_select_id(0), "Q")
    _focus(qtbot, window.result_list)
    assert _press_shortcut_and_read_tags(qtbot, window, current_id, Qt.Key.Key_Q) == [tag_id]
    # The old digit is released after rebinding, so it must not toggle the tag off.
    assert _press_shortcut_and_read_tags(qtbot, window, current_id, Qt.Key.Key_1) == [tag_id]


@pytest.mark.parametrize(
    ("binding", "modifier", "expected_text"),
    [
        ("Ctrl", Qt.KeyboardModifier.ControlModifier, "1"),
        ("Alt", Qt.KeyboardModifier.AltModifier, "1"),
        ("Alt", Qt.KeyboardModifier.ControlModifier, ""),
        ("", Qt.KeyboardModifier.ControlModifier, ""),
    ],
    ids=["default-control", "rebound-alt", "old-control", "unbound"],
)
def test_type_literally_modifier_controls_digit_entry(
    qtbot: QtBot,
    window: MainWindow,
    binding: str,
    modifier: Qt.KeyboardModifier,
    expected_text: str,
) -> None:
    session, current_id = _create_current_tags(window, "a")
    if binding != "Ctrl":
        rebind(window, shortcuts.TYPE_LITERALLY_MODIFIER, binding)

    _focus(qtbot, window.item_tag_panel.search_box)
    qtbot.keyClick(window.item_tag_panel.search_box, Qt.Key.Key_1, modifier)

    # With Ctrl+digit no longer bound, Qt supplies no printable text for
    # that key combination, so the focused search box and tag both stay put.
    assert window.item_tag_panel.search_box.text() == expected_text
    assert session.mappings.tags_for_media(current_id) == []


def test_ctrl_tapped_alone_toggles_which_tags_are_numbered(
    qtbot: QtBot, window: MainWindow
) -> None:
    assert window._tag_shortcut_mode_action.isChecked() is False

    _focus(qtbot, window.result_list)
    _tap_modifier(qtbot, window.result_list)

    assert window._tag_shortcut_mode_action.isChecked() is True

    _tap_modifier_and_expect_mode(qtbot, window, expected=False)


def test_ctrl_plus_another_key_does_not_toggle_the_mode_on_release(
    qtbot: QtBot, window: MainWindow
) -> None:
    """Ctrl+Z (undo) holds Ctrl down for an unrelated shortcut -- its
    eventual release must not also count as "tapped alone."."""
    session = _create_one_tag(window)

    _focus(qtbot, window.result_list)
    qtbot.keyPress(window.result_list, Qt.Key.Key_Control)
    qtbot.keyPress(window.result_list, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyRelease(window.result_list, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyRelease(window.result_list, Qt.Key.Key_Control)

    assert session.tags.list_all() == []  # the undo itself still fired
    assert window._tag_shortcut_mode_action.isChecked() is False


def test_selected_tag_mode_numbers_and_toggles_checked_tags_instead(
    qtbot: QtBot, window: MainWindow
) -> None:
    session, current_id = _create_current_tags(window, "a", "b")
    tag_a = session.tags.list_all()[0]
    window._on_item_tag_toggle(tag_a.id)  # "a" is now checked on the current item

    window._toggle_tag_shortcut_mode()
    assert window._tag_shortcut_mode_action.isChecked() is True

    tag_id = window.item_tag_panel.model.tag_id_for_slot(0, selected=True)
    assert tag_id == tag_a.id

    _focus(qtbot, window.result_list)
    qtbot.keyClick(window.result_list, Qt.Key.Key_1)

    assert session.mappings.tags_for_media(current_id) == []  # toggled back off


# -- Configurable bindings ---------------------------------------------------
# Every key above is a *default*, not a constant. These check that
# rebinding one in Settings actually moves the behavior with it, rather
# than the new key being recorded and then ignored.


def rebind(window: MainWindow, shortcut_id: str, binding: str) -> None:
    """Do what the Settings dialog does: change a binding, then tell the
    window to re-apply. `MainWindow.open_settings` wires exactly this pair
    together via the dialog's `bindings_changed` signal."""
    window.bindings.set_binding(shortcut_id, binding)
    window._apply_bindings()


def test_rebinding_navigation_moves_it_to_the_new_key(qtbot: QtBot, window: MainWindow) -> None:
    session, first_id, second_id = _set_first_of_two_results(window)
    rebind(window, shortcuts.NAVIGATE_NEXT, "F5")

    _focus(qtbot, window.result_list)
    qtbot.keyClick(window.result_list, Qt.Key.Key_F5)

    assert session.state.current_item == second_id

    # ...and off the old one, rather than answering to both.
    session.state.current_item = first_id
    qtbot.keyClick(window.result_list, Qt.Key.Key_Right)

    assert session.state.current_item == first_id


def test_an_unbound_shortcut_stops_responding(qtbot: QtBot, window: MainWindow) -> None:
    rebind(window, shortcuts.FOCUS_MODE, "")

    _focus(qtbot, window.result_list)
    qtbot.keyClick(window.result_list, Qt.Key.Key_Space)

    assert window._focus_mode_action.isChecked() is False


def test_escape_still_leaves_focus_mode_when_dismiss_is_unbound(
    qtbot: QtBot, window: MainWindow
) -> None:
    """A deliberate safety hatch: focus mode hides the menu bar, so a user
    who clears both Dismiss and Focus Mode would otherwise be stuck in it
    with no way back short of quitting."""
    _enter_focus_mode(qtbot, window)
    rebind(window, shortcuts.DISMISS, "")

    qtbot.keyClick(window.result_list, Qt.Key.Key_Escape)

    assert window._focus_mode_action.isChecked() is False


def test_rebinding_dismiss_moves_it_off_escape(qtbot: QtBot, window: MainWindow) -> None:
    rebind(window, shortcuts.DISMISS, "F4")
    _focus(qtbot, window.item_tag_panel.search_box)

    qtbot.keyClick(window.item_tag_panel.search_box, Qt.Key.Key_F4)

    assert window.result_list.hasFocus()


def test_rebinding_the_tag_search_cycle_moves_the_whole_cycle(
    qtbot: QtBot, window: MainWindow
) -> None:
    rebind(window, shortcuts.FOCUS_TAG_SEARCH, "F2")
    _focus(qtbot, window.result_list)

    qtbot.keyClick(window.result_list, Qt.Key.Key_F2)
    assert window.item_tag_panel.search_box.hasFocus()

    qtbot.keyClick(window.item_tag_panel.search_box, Qt.Key.Key_F2)
    assert window.filter_panel.search_box.hasFocus()

    qtbot.keyClick(window.filter_panel.search_box, Qt.Key.Key_F2)
    assert window.result_list.hasFocus()


def test_rebinding_a_menu_shortcut_updates_the_action(window: MainWindow) -> None:
    rebind(window, shortcuts.OPEN_SETTINGS, "F5")

    assert window._shortcut_actions[shortcuts.OPEN_SETTINGS].shortcut() == QKeySequence("F5")


def test_unbinding_a_menu_shortcut_leaves_the_action_with_no_key(window: MainWindow) -> None:
    rebind(window, shortcuts.OPEN_SETTINGS, "")

    assert window._shortcut_actions[shortcuts.OPEN_SETTINGS].shortcut().isEmpty()


def test_the_focus_mode_menu_entry_shows_its_current_key(window: MainWindow) -> None:
    """It has no QShortcut of its own -- one would go ambiguous against
    the viewer's play/pause button -- so its key is menu text instead,
    which still has to follow a rebind rather than keep advertising
    Space."""
    rebind(window, shortcuts.FOCUS_MODE, "F9")

    assert window._focus_mode_action.text() == "Focus Mode\tF9"

    rebind(window, shortcuts.FOCUS_MODE, "")

    assert window._focus_mode_action.text() == "Focus Mode"


def test_rebinding_play_pause_moves_the_viewer_button_shortcut(window: MainWindow) -> None:
    rebind(window, shortcuts.VIEWER_PLAY_PAUSE, "F10")

    assert window.viewer.play_pause_button.shortcut() == QKeySequence("F10")


def test_a_rebound_quick_select_key_is_still_typeable_with_ctrl(
    qtbot: QtBot, window: MainWindow
) -> None:
    """The escape hatch generalizes past digits: whatever key a
    quick-select shortcut is spent on, Ctrl+it types that character."""
    session, _current_id = _create_current_tags(window, "a")
    rebind(window, shortcuts.quick_select_id(0), "Q")

    _focus(qtbot, window.item_tag_panel.search_box)
    qtbot.keyClick(
        window.item_tag_panel.search_box, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier
    )

    assert window.item_tag_panel.search_box.text() == "q"
    assert session.mappings.tags_for_media(session.state.current_item) == []


def test_the_tag_rows_label_whichever_key_is_bound(window: MainWindow) -> None:
    window._on_tag_create("a")
    assert window._quick_select_labels()[0] == "1"

    rebind(window, shortcuts.quick_select_id(0), "Ctrl+Q")

    # The last key of the combination -- the checkbox has no room for the
    # whole thing, and "Q" is the part that identifies it.
    assert window._quick_select_labels()[0] == "Q"

    rebind(window, shortcuts.quick_select_id(0), "")

    assert 0 not in window._quick_select_labels()


def test_rebinding_the_numbering_swap_moves_it_to_another_modifier(
    qtbot: QtBot, window: MainWindow
) -> None:
    rebind(window, shortcuts.SWAP_TAG_NUMBERING, "Alt")
    _focus(qtbot, window.result_list)

    qtbot.keyPress(window.result_list, Qt.Key.Key_Alt)
    qtbot.keyRelease(window.result_list, Qt.Key.Key_Alt)

    assert window._tag_shortcut_mode_action.isChecked() is True

    # Ctrl is an ordinary modifier again, with no gesture attached.
    _tap_modifier_and_expect_mode(qtbot, window, expected=True)


def test_unbinding_the_numbering_swap_disables_the_gesture(
    qtbot: QtBot, window: MainWindow
) -> None:
    rebind(window, shortcuts.SWAP_TAG_NUMBERING, "")
    _focus(qtbot, window.result_list)

    _tap_modifier_and_expect_mode(qtbot, window, expected=False)


def test_the_numbering_swap_works_on_an_ordinary_key_too(qtbot: QtBot, window: MainWindow) -> None:
    """It's a regular input now -- bound to something that isn't a
    modifier, it fires on the press like any other shortcut rather than
    needing a tap-and-release."""
    rebind(window, shortcuts.SWAP_TAG_NUMBERING, "F8")
    _focus(qtbot, window.result_list)

    qtbot.keyClick(window.result_list, Qt.Key.Key_F8)

    assert window._tag_shortcut_mode_action.isChecked() is True

    qtbot.keyClick(window.result_list, Qt.Key.Key_F8)

    assert window._tag_shortcut_mode_action.isChecked() is False


def test_any_shortcut_can_be_bound_to_a_modifier_tap(qtbot: QtBot, window: MainWindow) -> None:
    """Nothing singles out which commands accept the tap gesture -- the
    capture box takes one for every row, so dispatch has to honour it
    for every command, or binding one would silently do nothing."""
    session = window.session
    assert session is not None
    first_id, second_id = session.state.result_set
    session.state.current_item = first_id
    window._sync_result_selection()
    rebind(window, shortcuts.SWAP_TAG_NUMBERING, "")  # free Ctrl up first
    rebind(window, shortcuts.NAVIGATE_NEXT, "Ctrl")

    _trigger_modifier_tap(qtbot, window)

    assert session.state.current_item == second_id


def test_a_menu_command_can_be_bound_to_a_modifier_tap(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Menu commands run as QActions rather than through the keyboard
    controller, so the tap dispatcher has to reach those too."""
    opened = _capture_settings_exec(monkeypatch)
    rebind(window, shortcuts.SWAP_TAG_NUMBERING, "")
    rebind(window, shortcuts.OPEN_SETTINGS, "Ctrl")

    _trigger_modifier_tap(qtbot, window)

    assert len(opened) == 1


def test_a_quick_select_shortcut_can_be_bound_to_a_modifier_tap(
    qtbot: QtBot, window: MainWindow
) -> None:
    session, current_id = _create_current_tags(window, "a")
    tag_id = window.item_tag_panel.model.tag_id_for_slot(0, selected=False)
    assert tag_id is not None
    rebind(window, shortcuts.SWAP_TAG_NUMBERING, "")
    rebind(window, shortcuts.quick_select_id(0), "Ctrl")

    _trigger_modifier_tap(qtbot, window)

    assert [t.id for t in session.mappings.tags_for_media(current_id)] == [tag_id]


def test_shortcuts_stand_down_while_a_modal_dialog_is_open(
    qtbot: QtBot, window: MainWindow
) -> None:
    """Otherwise a keystroke meant for the Settings window's capture box
    would also fire whatever command it's currently bound to."""
    session = window.session
    assert session is not None
    first_id = session.state.result_set[0]
    session.state.current_item = first_id
    window._sync_result_selection()

    blocker = QDialog(window)
    blocker.setWindowModality(Qt.WindowModality.ApplicationModal)
    qtbot.addWidget(blocker)
    blocker.show()
    qtbot.waitExposed(blocker)
    qtbot.waitUntil(lambda: QApplication.activeModalWidget() is blocker, timeout=1000)

    qtbot.keyClick(blocker, Qt.Key.Key_Right)

    assert session.state.current_item == first_id

    blocker.close()
    qtbot.waitUntil(lambda: QApplication.activeModalWidget() is None, timeout=1000)
    _navigate_right_to(qtbot, window, session.state.result_set[1])


def test_opening_settings_applies_what_is_changed_in_it(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The connection between the two halves of the feature. Every other
    test here calls `_apply_bindings()` by hand; this is the one that
    checks `open_settings` actually subscribes to the dialog, rather than
    recording a rebind that never reaches the running UI. `exec()` is
    stubbed out because it would otherwise block on its own event loop."""
    opened = _capture_settings_exec(monkeypatch)

    window.open_settings()

    assert len(opened) == 1
    row = next(
        r for r in opened[0].shortcuts_panel.rows if r.definition.id == shortcuts.TOGGLE_THUMBNAILS
    )
    qtbot.mouseClick(row._clear_button, Qt.MouseButton.LeftButton)

    assert window.bindings.binding(shortcuts.TOGGLE_THUMBNAILS) == ""
    assert window._shortcut_actions[shortcuts.TOGGLE_THUMBNAILS].shortcut().isEmpty()


def test_the_settings_menu_entry_opens_the_window(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = _capture_settings_exec(monkeypatch)

    window._shortcut_actions[shortcuts.OPEN_SETTINGS].trigger()

    assert len(opened) == 1


def test_bindings_persist_across_windows(qtbot: QtBot) -> None:
    """A rebind is a preference, not session state -- it has to survive
    the app being closed and reopened."""
    first = MainWindow()
    qtbot.addWidget(first)
    first.bindings.set_binding(shortcuts.OPEN_SETTINGS, "F5")

    second = MainWindow()
    qtbot.addWidget(second)

    assert second.bindings.binding(shortcuts.OPEN_SETTINGS) == "F5"
    assert second._shortcut_actions[shortcuts.OPEN_SETTINGS].shortcut() == QKeySequence("F5")


def test_ctrl_left_and_right_step_back_and_forward_through_view_history(
    qtbot: QtBot, window: MainWindow
) -> None:
    session, first_id, second_id = _show_two_item_history(qtbot, window)
    assert session.state.current_item == second_id

    qtbot.keyClick(window, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    assert session.state.current_item == first_id

    qtbot.keyClick(window, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert session.state.current_item == second_id


def test_view_history_reaches_a_file_the_results_no_longer_include(
    qtbot: QtBot, window: MainWindow
) -> None:
    session, first_id, second_id = _show_two_item_history(qtbot, window)
    # As if a filter had since dropped the first file from the list.
    window._display_order = [second_id]

    qtbot.keyClick(window, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)

    assert session.state.current_item == first_id
    first = session.media.get(first_id)
    assert first is not None
    assert window.viewer.current_path is not None
    assert window.viewer.current_path.name == Path(first.relative_path).name


def test_view_history_shortcuts_work_while_a_tag_search_box_has_focus(
    qtbot: QtBot, window: MainWindow
) -> None:
    session, first_id, _second_id = _show_two_item_history(qtbot, window)
    window.item_tag_panel.focus_search()

    qtbot.keyClick(window, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)

    assert session.state.current_item == first_id
