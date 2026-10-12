from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIntValidator, QKeyEvent
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QScrollArea, QWidget
from pytestqt.qtbot import QtBot

from prismic.application.input import shortcuts
from prismic.application.input.shortcuts import SHORTCUTS, ShortcutBindings
from prismic.application.tag_ranking_settings import (
    DEFAULT_MEGA_POPULAR_THRESHOLD,
    TagRankingSettingsStore,
)
from prismic.persistence.preferences import PreferencesStore
from prismic.ui.frameless_dialog import MessageDialog, SizeGrip
from prismic.ui.settings_dialog import (
    KeyCaptureButton,
    SettingsDialog,
    ShortcutRow,
    TagRankingPanel,
    ThresholdRow,
    binding_display,
)


@pytest.fixture
def bindings(tmp_path: Path) -> ShortcutBindings:
    return ShortcutBindings(PreferencesStore(tmp_path / "preferences.json"))


@pytest.fixture
def dialog(qtbot: QtBot, bindings: ShortcutBindings) -> SettingsDialog:
    window = SettingsDialog(bindings)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


def row_for(dialog: SettingsDialog, shortcut_id: str) -> ShortcutRow:
    for row in dialog.shortcuts_panel.rows:
        if row.definition.id == shortcut_id:
            return row
    raise AssertionError(f"no row for {shortcut_id}")


def start_capture(
    qtbot: QtBot, dialog: SettingsDialog, shortcut_id: str = shortcuts.OPEN_COLLECTION_FOLDER
) -> KeyCaptureButton:
    button = row_for(dialog, shortcut_id)._editor
    assert isinstance(button, KeyCaptureButton)
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    return button


def capture_key(
    qtbot: QtBot,
    dialog: SettingsDialog,
    key: Qt.Key,
    modifiers: Qt.KeyboardModifier,
) -> KeyCaptureButton:
    button = start_capture(qtbot, dialog)
    qtbot.keyClick(button, key, modifiers)
    return button


def _key_release(key: Qt.Key, *, auto_repeat: bool = False, ignored: bool = False) -> QKeyEvent:
    event = QKeyEvent(
        QEvent.Type.KeyRelease,
        key,
        Qt.KeyboardModifier.NoModifier,
        "",
        auto_repeat,
    )
    if ignored:
        event.ignore()
    return event


def accept_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer Yes to every confirmation the dialog raises, so a test can
    drive a flow that passes through one without blocking on it."""
    monkeypatch.setattr(
        MessageDialog, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )


# -- The panel lists everything ----------------------------------------------


def test_the_dialog_has_a_shortcuts_panel(dialog: SettingsDialog) -> None:
    assert dialog.panel_list.count() == 2
    assert dialog.panel_list.item(0).text() == "Shortcuts"
    assert dialog.panel_list.item(1).text() == "Tag ranking"


def test_every_registered_shortcut_gets_a_row(dialog: SettingsDialog) -> None:
    """The whole point of the panel: not a hand-written list that drifts
    from the registry, but one row per `ShortcutDefinition`."""
    listed = [row.definition.id for row in dialog.shortcuts_panel.rows]

    assert listed == [definition.id for definition in SHORTCUTS]


def test_each_row_shows_the_key_currently_bound(dialog: SettingsDialog) -> None:
    editor = row_for(dialog, shortcuts.OPEN_COLLECTION_FILE)._editor
    assert isinstance(editor, KeyCaptureButton)

    assert editor.text() == "Ctrl + Shift + O"


def test_every_row_gets_the_same_editor(dialog: SettingsDialog) -> None:
    """No per-command variations. What a binding turns out to be -- a
    key, a combination, a bare modifier tap -- is decided by what the
    user presses into the box, not by the registry."""
    assert all(isinstance(row._editor, KeyCaptureButton) for row in dialog.shortcuts_panel.rows)


def test_a_bare_modifier_binding_says_it_is_a_tap(dialog: SettingsDialog) -> None:
    """ "Ctrl" alone would otherwise read as an unfinished combination."""
    editor = row_for(dialog, shortcuts.SWAP_TAG_NUMBERING)._editor
    assert isinstance(editor, KeyCaptureButton)

    assert editor.text() == "Ctrl (tapped alone)"


def test_the_type_literally_modifier_reads_as_held_not_tapped(dialog: SettingsDialog) -> None:
    """The same bare-modifier binding means something different on this
    one row -- held down for another key, not tapped and released -- so
    it needs different parenthetical text, not the generic "tapped
    alone" every other bare-modifier binding gets."""
    editor = row_for(dialog, shortcuts.TYPE_LITERALLY_MODIFIER)._editor
    assert isinstance(editor, KeyCaptureButton)

    assert editor.text() == "Ctrl (held)"


def test_an_unbound_shortcut_reads_as_not_set(
    dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "")
    dialog.shortcuts_panel.refresh()

    editor = row_for(dialog, shortcuts.OPEN_COLLECTION_FOLDER)._editor
    assert isinstance(editor, KeyCaptureButton)
    assert editor.text() == "Not set"


# -- Searching -----------------------------------------------------------------


def test_the_search_box_narrows_the_list(dialog: SettingsDialog) -> None:
    dialog.shortcuts_panel.search_box.setText("folder")

    visible = [row.definition.id for row in dialog.shortcuts_panel.visible_rows()]
    assert visible == [shortcuts.OPEN_COLLECTION_FOLDER]


def test_the_search_box_also_matches_the_key_itself(dialog: SettingsDialog) -> None:
    """Answering "what's on Ctrl+T again?" should be possible by typing
    the key, not just the feature's name."""
    dialog.shortcuts_panel.search_box.setText("ctrl + t")

    visible = [row.definition.id for row in dialog.shortcuts_panel.visible_rows()]
    assert visible == [shortcuts.TOGGLE_THUMBNAILS]


def test_clearing_the_search_box_brings_every_row_back(dialog: SettingsDialog) -> None:
    dialog.shortcuts_panel.search_box.setText("folder")
    dialog.shortcuts_panel.search_box.setText("")

    assert len(dialog.shortcuts_panel.visible_rows()) == len(SHORTCUTS)


# -- Capturing a new key --------------------------------------------------------


def test_clicking_the_key_box_starts_capturing(qtbot: QtBot, dialog: SettingsDialog) -> None:
    button = row_for(dialog, shortcuts.OPEN_COLLECTION_FOLDER)._editor
    assert isinstance(button, KeyCaptureButton)

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert button.is_capturing
    assert button.text() == "Press a key…"


def test_pressing_a_key_while_capturing_rebinds_the_shortcut(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    button = capture_key(qtbot, dialog, Qt.Key.Key_F5, Qt.KeyboardModifier.NoModifier)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "F5"
    assert not button.is_capturing
    assert button.text() == "F5"


def test_capturing_records_the_modifiers_too(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    capture_key(
        qtbot,
        dialog,
        Qt.Key.Key_K,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
    )

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+Alt+K"


def test_a_bare_modifier_does_not_end_the_capture(qtbot: QtBot, dialog: SettingsDialog) -> None:
    """Ctrl on its own is the user starting a combination, not finishing
    one -- the box keeps waiting for the rest."""
    button = start_capture(qtbot, dialog)

    qtbot.keyPress(button, Qt.Key.Key_Control)

    assert button.is_capturing


def test_closing_the_window_mid_capture_releases_the_keyboard(
    qtbot: QtBot, dialog: SettingsDialog
) -> None:
    """`grabKeyboard()` is application-wide: a grab left held by a hidden
    (or destroyed) widget would take every keystroke in the app with
    nothing on screen to explain why. Losing focus is the usual way out,
    but closing the window mid-capture doesn't reliably deliver a
    focus-out first."""
    button = start_capture(qtbot, dialog)
    assert button.is_capturing

    dialog.close()

    assert not button.is_capturing
    assert QWidget.keyboardGrabber() is not button


def test_escape_cancels_a_capture_without_changing_anything(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    button = capture_key(qtbot, dialog, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)

    assert not button.is_capturing
    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"
    assert dialog.isVisible()  # and it didn't close the dialog either


def test_capturing_tab_binds_tab_rather_than_moving_focus(
    qtbot: QtBot,
    dialog: SettingsDialog,
    bindings: ShortcutBindings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every key Qt normally spends on its own navigation has to be
    bindable -- Tab most of all, since it's a real default here. (It's
    already taken by the tag-search cycle, hence the conflict prompt.)"""
    accept_all(monkeypatch)
    button = start_capture(qtbot, dialog)

    qtbot.keyClick(button, Qt.Key.Key_Tab)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Tab"


def test_capturing_space_binds_space_rather_than_re_pressing_the_button(
    qtbot: QtBot,
    dialog: SettingsDialog,
    bindings: ShortcutBindings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Space would otherwise activate the focused capture button itself,
    ending the capture instead of being recorded by it."""
    accept_all(monkeypatch)
    button = row_for(dialog, shortcuts.OPEN_COLLECTION_FOLDER)._editor
    assert isinstance(button, KeyCaptureButton)
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    qtbot.keyClick(button, Qt.Key.Key_Space)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Space"


def test_tapping_a_modifier_alone_binds_the_modifier(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    """Pressed and released with nothing in between, a modifier is a
    binding in its own right -- which is how the numbering swap gets its
    default of plain Ctrl through the ordinary capture box."""
    button = start_capture(qtbot, dialog)

    qtbot.keyPress(button, Qt.Key.Key_Alt)
    qtbot.keyRelease(button, Qt.Key.Key_Alt)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Alt"
    assert not button.is_capturing


def test_a_modifier_released_after_a_combination_is_not_a_tap(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    """Ctrl+K is one binding, not Ctrl+K followed by a stray Ctrl tap --
    the capture has to already be finished by the time Ctrl comes up."""
    button = start_capture(qtbot, dialog)

    # Raw presses, in the order a real keyboard produces them. Passing
    # `modifiers=` to qtbot instead would make QTest synthesize its own
    # extra modifier press/release around the key, which is not what the
    # widget sees from a physical keyboard and would be testing QTest.
    qtbot.keyPress(button, Qt.Key.Key_Control)
    qtbot.keyPress(button, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyRelease(button, Qt.Key.Key_K)
    qtbot.keyRelease(button, Qt.Key.Key_Control)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+K"


def test_two_modifiers_held_together_are_not_a_tap(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    """Ctrl held while Shift goes down isn't either one tapped alone, so
    the box keeps waiting rather than guessing which was meant."""
    button = start_capture(qtbot, dialog)

    qtbot.keyPress(button, Qt.Key.Key_Control)
    qtbot.keyPress(button, Qt.Key.Key_Shift)
    qtbot.keyRelease(button, Qt.Key.Key_Shift)
    qtbot.keyRelease(button, Qt.Key.Key_Control)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"  # unchanged
    assert button.is_capturing  # still waiting for something bindable


# -- Clearing and resetting ------------------------------------------------------


def test_clear_unbinds_the_shortcut(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    row = row_for(dialog, shortcuts.OPEN_COLLECTION_FOLDER)

    qtbot.mouseClick(row._clear_button, Qt.MouseButton.LeftButton)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == ""


@pytest.mark.parametrize("reset", [False, True], ids=["clear-only", "clear-then-reset"])
def test_clear_enables_reset_and_reset_restores_the_default(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings, reset: bool
) -> None:
    row = row_for(dialog, shortcuts.OPEN_COLLECTION_FOLDER)
    assert not row._reset_button.isEnabled()

    qtbot.mouseClick(row._clear_button, Qt.MouseButton.LeftButton)

    assert row._reset_button.isEnabled()
    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == ""
    if reset:
        qtbot.mouseClick(row._reset_button, Qt.MouseButton.LeftButton)
        assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"


def test_restore_all_defaults_resets_every_shortcut(
    qtbot: QtBot,
    dialog: SettingsDialog,
    bindings: ShortcutBindings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accept_all(monkeypatch)
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "F5")
    bindings.set_binding(shortcuts.NAVIGATE_NEXT, "F6")

    qtbot.mouseClick(dialog.shortcuts_panel._restore_button, Qt.MouseButton.LeftButton)

    assert all(bindings.is_default(definition.id) for definition in SHORTCUTS)


def test_declining_restore_all_defaults_keeps_existing_bindings(
    qtbot: QtBot,
    dialog: SettingsDialog,
    bindings: ShortcutBindings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "F5")
    monkeypatch.setattr(
        MessageDialog, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel
    )

    qtbot.mouseClick(dialog.shortcuts_panel._restore_button, Qt.MouseButton.LeftButton)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "F5"


# -- Conflicts ---------------------------------------------------------------------


def test_taking_a_key_from_another_shortcut_asks_first_and_clears_it(
    qtbot: QtBot,
    dialog: SettingsDialog,
    bindings: ShortcutBindings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accept_all(monkeypatch)
    capture_key(qtbot, dialog, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+T"
    assert bindings.binding(shortcuts.TOGGLE_THUMBNAILS) == ""


def test_declining_the_conflict_leaves_both_shortcuts_alone(
    qtbot: QtBot,
    dialog: SettingsDialog,
    bindings: ShortcutBindings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        MessageDialog, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel
    )
    capture_key(qtbot, dialog, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"
    assert bindings.binding(shortcuts.TOGGLE_THUMBNAILS) == "Ctrl+T"


def test_a_conflict_already_in_the_file_is_shown_on_both_rows(
    qtbot: QtBot, bindings: ShortcutBindings
) -> None:
    """A hand-edited preferences file can produce a collision no prompt
    ever guarded, so the rows say so rather than silently leaving one of
    the two shortcuts dead."""
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "Ctrl+T")
    dialog = SettingsDialog(bindings)
    qtbot.addWidget(dialog)

    assert row_for(dialog, shortcuts.OPEN_COLLECTION_FOLDER)._conflict.isVisibleTo(dialog)
    assert row_for(dialog, shortcuts.TOGGLE_THUMBNAILS)._conflict.isVisibleTo(dialog)


def test_sharing_a_key_across_input_contexts_is_not_a_conflict(
    qtbot: QtBot, dialog: SettingsDialog
) -> None:
    """Focus Mode and the viewer's play/pause both ship on Space by
    design -- flagging the app's own defaults would make the warning
    worthless."""
    assert not row_for(dialog, shortcuts.FOCUS_MODE)._conflict.isVisibleTo(dialog)
    assert not row_for(dialog, shortcuts.VIEWER_PLAY_PAUSE)._conflict.isVisibleTo(dialog)


def test_the_type_literally_modifier_sharing_ctrl_is_not_a_conflict(dialog: SettingsDialog) -> None:
    """Both default to plain Ctrl -- tapped alone for the numbering swap,
    held down for this one -- which is exactly the "different input
    context" case `ShortcutScope` exists for, not a real collision."""
    assert not row_for(dialog, shortcuts.SWAP_TAG_NUMBERING)._conflict.isVisibleTo(dialog)
    assert not row_for(dialog, shortcuts.TYPE_LITERALLY_MODIFIER)._conflict.isVisibleTo(dialog)


# -- Reporting changes back -----------------------------------------------------------


def test_the_dialog_reports_every_change_so_the_app_can_re_apply_it(
    qtbot: QtBot, dialog: SettingsDialog
) -> None:
    row = row_for(dialog, shortcuts.OPEN_COLLECTION_FOLDER)

    with qtbot.waitSignal(dialog.bindings_changed, timeout=1000):
        qtbot.mouseClick(row._clear_button, Qt.MouseButton.LeftButton)


def test_binding_display_spells_out_an_unbound_shortcut() -> None:
    assert binding_display("") == "Not set"
    assert binding_display("Ctrl+R") == "Ctrl + R"


def test_binding_display_distinguishes_a_modifier_tap_from_a_hold() -> None:
    assert binding_display("Ctrl") == "Ctrl (tapped alone)"
    assert binding_display("Ctrl", held=True) == "Ctrl (held)"


def test_capture_button_defaults_to_a_tapped_modifier_display() -> None:
    button = KeyCaptureButton(parent=None)
    button.set_binding("Ctrl")

    assert button.text() == "Ctrl (tapped alone)"


def test_binding_display_accepts_binding_as_a_keyword_argument() -> None:
    assert binding_display(binding="Ctrl+R") == "Ctrl + R"


def test_unset_indicator_tracks_binding_and_capture_state(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    button = row_for(dialog, shortcuts.OPEN_COLLECTION_FOLDER)._editor
    assert isinstance(button, KeyCaptureButton)
    assert button.property("unset") is False

    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "")
    dialog.shortcuts_panel.refresh()
    assert button.property("unset") is True

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert button.property("unset") is False


def test_search_keeps_a_category_header_for_its_single_matching_row(dialog: SettingsDialog) -> None:
    panel = dialog.shortcuts_panel
    assert panel.search_box.isClearButtonEnabled()
    assert not panel._empty_label.isVisibleTo(panel)
    panel.search_box.setText("Previous file (works while typing)")

    assert [row.definition.id for row in panel.visible_rows()] == [
        shortcuts.NAVIGATE_PREVIOUS_WHILE_TYPING
    ]
    assert panel._headers["Navigation"].isVisibleTo(panel)
    assert not panel._empty_label.isVisibleTo(panel)

    panel.search_box.setText("nothing matches this")
    assert panel._empty_label.isVisibleTo(panel)
    assert not any(header.isVisibleTo(panel) for header in panel._headers.values())


def test_shortcut_override_is_accepted_while_capturing(
    qtbot: QtBot, dialog: SettingsDialog
) -> None:
    button = start_capture(qtbot, dialog)
    event = QKeyEvent(
        QEvent.Type.ShortcutOverride,
        Qt.Key.Key_T,
        Qt.KeyboardModifier.ControlModifier,
    )
    event.ignore()

    assert button.event(event)
    assert event.isAccepted()
    assert button.is_capturing


def test_bare_modifier_press_and_release_are_consumed_as_a_binding(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    button = start_capture(qtbot, dialog)
    press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Alt, Qt.KeyboardModifier.NoModifier)
    press.ignore()

    assert button.event(press)
    assert button.is_capturing

    release = QKeyEvent(
        QEvent.Type.KeyRelease,
        Qt.Key.Key_Alt,
        Qt.KeyboardModifier.NoModifier,
    )
    release.ignore()
    assert button.event(release)
    assert not button.is_capturing
    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Alt"


@pytest.mark.parametrize("unrelated_key", [Qt.Key.Key_Shift, Qt.Key.Key_Alt])
def test_unrelated_modifier_release_does_not_bind_the_pending_modifier(
    qtbot: QtBot,
    dialog: SettingsDialog,
    bindings: ShortcutBindings,
    unrelated_key: Qt.Key,
) -> None:
    button = start_capture(qtbot, dialog)
    button._pending_modifier = int(Qt.Key.Key_Control)
    release = _key_release(unrelated_key, ignored=True)

    assert button.event(release)
    assert button.is_capturing
    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"


def test_release_without_a_pending_modifier_is_consumed_without_binding(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    button = start_capture(qtbot, dialog)
    release = _key_release(Qt.Key.Key_F5, ignored=True)

    assert button.event(release)
    assert button.is_capturing
    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"


def test_auto_repeat_modifier_release_does_not_finish_capture(
    qtbot: QtBot, dialog: SettingsDialog, bindings: ShortcutBindings
) -> None:
    button = start_capture(qtbot, dialog)
    button._pending_modifier = int(Qt.Key.Key_Control)
    event = _key_release(Qt.Key.Key_Control, auto_repeat=True)

    assert button.event(event)
    assert button.is_capturing
    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"


def test_threshold_row_limits_percent_input_and_resets_changed_values(
    qtbot: QtBot,
) -> None:
    row = ThresholdRow("Threshold", "Description", default_fraction=0.5)
    qtbot.addWidget(row)
    validator = row._editor.validator()

    assert isinstance(validator, QIntValidator)
    assert (validator.bottom(), validator.top()) == (1, 100)
    assert row._editor.minimumWidth() == row._editor.maximumWidth() == 50
    row_layout = row.layout()
    assert row_layout is not None
    assert row_layout.getContentsMargins() == (10, 8, 10, 8)
    assert row_layout.spacing() == 10
    assert row_layout.count() == 4
    text_layout = row_layout.itemAt(0).layout()
    assert text_layout is not None
    assert text_layout.getContentsMargins() == (0, 0, 0, 0)
    assert text_layout.spacing() == 2
    assert text_layout.itemAt(1).widget().wordWrap()
    assert row_layout.stretch(0) == 1

    row.set_fraction(0.8)
    with qtbot.waitSignal(row.changed):
        row._reset_button.click()
    assert row.fraction == 0.5


def test_threshold_row_does_not_emit_for_an_equal_default_value(qtbot: QtBot) -> None:
    default = 0.35
    row = ThresholdRow("Threshold", "Description", default_fraction=default)
    qtbot.addWidget(row)
    row.set_fraction(float(str(default)))
    assert not row._reset_button.isEnabled()

    with qtbot.assertNotEmitted(row.changed):
        row._reset()


def test_tag_ranking_panel_persists_edits_and_emits_change(qtbot: QtBot, tmp_path: Path) -> None:
    store = TagRankingSettingsStore(PreferencesStore(tmp_path / "preferences.json"))
    panel = TagRankingPanel(store)
    qtbot.addWidget(panel)

    panel.correlation_row._editor.setText("60")
    with qtbot.waitSignal(panel.changed):
        panel.correlation_row._commit()

    saved = store.load()
    assert saved.correlation_threshold == 0.6
    assert saved.mega_popular_threshold == DEFAULT_MEGA_POPULAR_THRESHOLD


def test_settings_dialog_starts_on_shortcuts_and_switches_panels(dialog: SettingsDialog) -> None:
    assert dialog.panel_list.currentRow() == 0
    assert dialog._stack.currentWidget() is dialog.shortcuts_panel

    dialog.panel_list.setCurrentRow(1)
    assert dialog._stack.currentWidget() is dialog.tag_ranking_panel


def test_settings_layout_preserves_row_and_panel_geometry(dialog: SettingsDialog) -> None:
    shortcut_row = row_for(dialog, shortcuts.OPEN_COLLECTION_FOLDER)
    row_layout = shortcut_row.layout()
    assert row_layout is not None
    assert row_layout.getContentsMargins() == (10, 8, 10, 8)
    assert row_layout.spacing() == 10
    text_layout = row_layout.itemAt(0).layout()
    assert text_layout is not None
    assert text_layout.getContentsMargins() == (0, 0, 0, 0)
    assert text_layout.spacing() == 2
    assert row_layout.stretch(0) == 1
    assert shortcut_row._editor.minimumWidth() == shortcut_row._editor.maximumWidth() == 180

    shortcuts_layout = dialog.shortcuts_panel.layout()
    assert shortcuts_layout is not None
    assert shortcuts_layout.getContentsMargins() == (12, 12, 12, 12)
    assert shortcuts_layout.spacing() == 10
    assert shortcuts_layout.stretch(2) == 1
    scroll = dialog.shortcuts_panel.findChild(QScrollArea, "settingsScroll")
    assert scroll is not None and scroll.widget() is not None
    assert scroll.widgetResizable()
    content_layout = scroll.widget().layout()
    assert content_layout is not None
    assert content_layout.getContentsMargins() == (0, 0, 8, 0)
    assert content_layout.spacing() == 0
    assert content_layout.stretch(content_layout.count() - 1) == 1
    assert all(
        separator.minimumHeight() == separator.maximumHeight() == 1
        for separator in dialog.shortcuts_panel._separators_by_row.values()
    )

    footer_layout = shortcuts_layout.itemAt(3).layout()
    assert footer_layout is not None
    assert footer_layout.getContentsMargins() == (0, 0, 0, 0)
    assert footer_layout.stretch(1) == 1
    assert dialog.panel_list.width() == 150
    assert dialog.size().width() == 760
    assert dialog.size().height() == 620

    ranking_layout = dialog.tag_ranking_panel.layout()
    assert ranking_layout is not None
    assert ranking_layout.getContentsMargins() == (12, 12, 12, 12)
    assert ranking_layout.spacing() == 0
    assert ranking_layout.stretch(3) == 1

    dialog_layout = dialog.layout()
    assert dialog_layout is not None
    assert dialog_layout.getContentsMargins() == (0, 0, 0, 0)
    assert dialog_layout.spacing() == 0
    assert dialog_layout.stretch(1) == 1
    body_layout = dialog_layout.itemAt(1).layout()
    assert body_layout is not None
    assert body_layout.getContentsMargins() == (0, 0, 0, 0)
    assert body_layout.spacing() == 0
    assert body_layout.stretch(1) == 1

    close_button = next(
        button for button in dialog.findChildren(QPushButton) if button.text() == "Close"
    )
    assert close_button.isDefault()

    footer_widget = dialog_layout.itemAt(2).widget()
    assert footer_widget is not None and footer_widget.layout() is not None
    assert footer_widget.layout().stretch(0) == 1


def test_shortcut_rows_wrap_text_and_hide_conflicts_until_needed(dialog: SettingsDialog) -> None:
    row = row_for(dialog, shortcuts.OPEN_COLLECTION_FOLDER)
    assert row._description.wordWrap()
    assert row._conflict.wordWrap()
    assert not row._conflict.isVisibleTo(dialog)


def test_settings_dialog_uses_the_injected_tag_ranking_store(
    qtbot: QtBot, bindings: ShortcutBindings, tmp_path: Path
) -> None:
    store = TagRankingSettingsStore(PreferencesStore(tmp_path / "preferences.json"))
    dialog = SettingsDialog(bindings, tag_ranking_settings=store)
    qtbot.addWidget(dialog)

    assert dialog.tag_ranking_panel._store is store


# -- Window chrome -----------------------------------------------------------
# The window supplies its own, so the two jobs the native frame was
# doing -- somewhere to grab it by, and a way to close it -- have to be
# covered here instead.


def test_the_window_has_no_native_frame(dialog: SettingsDialog) -> None:
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint


def test_the_title_bar_names_the_window(dialog: SettingsDialog) -> None:
    """The native title bar showed `windowTitle()`; this one has to say
    the same thing, since nothing else does now."""
    label = dialog.title_bar.findChild(QLabel, "dialogTitle")
    assert label is not None
    assert label.text() == dialog.windowTitle() == "Settings"


def test_the_title_bar_close_button_closes_the_window(qtbot: QtBot, dialog: SettingsDialog) -> None:
    assert dialog.isVisible()

    qtbot.mouseClick(dialog.title_bar.close_button, Qt.MouseButton.LeftButton)

    assert not dialog.isVisible()


def test_escape_still_closes_the_window(qtbot: QtBot, dialog: SettingsDialog) -> None:
    """Losing the native frame must not leave the keyboard route out
    depending on the mouse finding a 44px button."""
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)

    assert not dialog.isVisible()


def test_the_close_button_is_not_the_default_button(dialog: SettingsDialog) -> None:
    """Return belongs to whatever the user is working in -- a title-bar
    X that answers it would close the window out from under them."""
    assert not dialog.title_bar.close_button.isDefault()
    assert not dialog.title_bar.close_button.autoDefault()


def test_the_window_can_still_be_resized(dialog: SettingsDialog) -> None:
    """A frameless window loses the native resize borders with the rest
    of the frame, and this list is long enough that height matters."""
    assert dialog.findChild(SizeGrip) is not None


# -- Opening without a flash ---------------------------------------------------
# Both of these were a visible flicker on the real window, found by
# logging the dialog's events across its first frames rather than by
# looking at it -- the whole thing is over in well under one frame's
# worth of wall clock.


def test_the_scroll_area_never_scrolls_horizontally(dialog: SettingsDialog) -> None:
    """Left on the default policy, the first layout pass -- before the
    vertical scrollbar's width comes out of the viewport -- makes the
    content momentarily too wide, and a horizontal scrollbar appears for
    exactly one frame before vanishing. Nothing here is ever meant to
    scroll sideways, so the bar is switched off outright (the same
    reasoning, and the same fix, as `TagPanel` and the result list)."""
    scroll = dialog.shortcuts_panel.findChild(QScrollArea, "settingsScroll")
    assert scroll is not None
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_a_parented_dialog_positions_itself_before_it_is_shown(
    qtbot: QtBot, bindings: ShortcutBindings
) -> None:
    """`QDialog::adjustPosition()` only runs while `Qt::WA_Moved` is
    unset, and it runs twice -- once before the window is mapped, when
    the frame margins read as zero, and again once they're real. The
    dialog therefore appeared and *then* jumped by the size of its own
    title bar. Positioning it ourselves up front sets WA_Moved, which is
    what stops the second pass; this asserts the flag rather than the
    coordinates, since the exact centre is the window manager's business
    and varies by screen."""
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(1200, 800)
    parent.show()
    qtbot.waitExposed(parent)

    child = SettingsDialog(bindings, parent)
    qtbot.addWidget(child)

    assert child.testAttribute(Qt.WidgetAttribute.WA_Moved)

    before = child.pos()
    child.show()
    qtbot.waitExposed(child)

    assert child.pos() == before  # nothing repositioned it on the way up


def test_a_parentless_dialog_is_left_to_the_platform(dialog: SettingsDialog) -> None:
    """The `dialog` fixture builds one with no parent -- there's nothing
    to centre on, so placing it stays the window manager's job."""
    assert not dialog.testAttribute(Qt.WidgetAttribute.WA_Moved)
