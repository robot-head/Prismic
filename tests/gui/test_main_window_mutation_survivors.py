"""Regression tests for MainWindow behaviors left uncovered by mutation testing."""

from __future__ import annotations

from pathlib import Path
from typing import get_type_hints

import pytest
from PySide6.QtCore import QByteArray, QSignalBlocker, Qt
from PySide6.QtWidgets import QApplication, QFileDialog
from pytestqt.qtbot import QtBot

from prismic.application.input import shortcuts
from prismic.application.input.shortcuts import ShortcutBindings
from prismic.application.tag_ranking_settings import TagRankingSettingsStore
from prismic.domain.tag import Tag
from prismic.persistence.errors import CollectionLockedError
from prismic.ui.main_window import MainWindow
from prismic.ui.result_list_view import ResultListView
from tests.gui.helpers import (
    create_tag,
    open_and_wait,
    refresh_and_hover_item_tag,
)


@pytest.fixture
def opened_window(qtbot: QtBot, window: MainWindow, collection_dir: Path) -> MainWindow:
    open_and_wait(qtbot, window, collection_dir)
    return window


def test_main_window_union_annotations_resolve_to_their_declared_types() -> None:
    constructor_hints = get_type_hints(MainWindow.__init__)

    assert constructor_hints["initial_path"] == Path | None
    assert constructor_hints["bindings"] == ShortcutBindings | None
    assert constructor_hints["tag_ranking_settings"] == TagRankingSettingsStore | None
    assert get_type_hints(MainWindow._create_tag_and_find)["return"] == Tag | None
    assert get_type_hints(MainWindow._on_item_tag_hover)["row"] == int | None
    assert get_type_hints(MainWindow._resolve_media_path)["return"] == Path | None


@pytest.mark.parametrize(
    ("saved_geometry", "expected_call"),
    [(None, "maximize"), (QByteArray(b"saved geometry"), "restore")],
    ids=["no-saved-geometry", "saved-geometry"],
)
def test_window_uses_saved_geometry_or_maximizes_by_default(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    saved_geometry: QByteArray | None,
    expected_call: str,
) -> None:
    calls: list[tuple[str, object]] = []

    class SettingsStub:
        def value(self, key: str) -> object:
            return saved_geometry if key == "window/geometry" else None

        def setValue(self, _key: str, _value: object) -> None:
            pass

    monkeypatch.setattr("prismic.ui.main_window.QSettings", SettingsStub)
    monkeypatch.setattr(
        MainWindow, "restoreGeometry", lambda self, value: calls.append(("restore", value))
    )
    monkeypatch.setattr(MainWindow, "showMaximized", lambda self: calls.append(("maximize", None)))
    window = MainWindow()
    qtbot.addWidget(window)

    assert calls == [(expected_call, saved_geometry if expected_call == "restore" else None)]


def test_view_history_deduplicates_the_current_id_by_value(window: MainWindow) -> None:
    media_id = int("1000")
    same_id = int("1000")
    assert media_id is not same_id

    window._record_view(media_id)
    window._record_view(same_id)

    assert window._view_history == [media_id]
    assert window._view_history_index == 0


def test_view_history_discards_forward_entries_after_a_new_visit(window: MainWindow) -> None:
    for media_id in (101, 202, 303):
        window._record_view(media_id)
    window._view_history_index = 1

    window._record_view(404)

    assert window._view_history == [101, 202, 404]
    assert window._view_history_index == 2


def test_stable_item_tag_order_uses_value_equal_media_ids(window: MainWindow) -> None:
    stored_id = int("1000")
    current_id = int("1000")
    assert stored_id is not current_id
    window._item_tag_order = [2, 1]
    window._item_tag_order_item_id = stored_id

    ordered = window._stable_item_tags(
        [Tag(id=1, name="alpha"), Tag(id=2, name="beta")],
        frozenset({1, 2}),
        current_id,
    )

    assert [tag.id for tag in ordered] == [2, 1]


def test_view_history_keeps_only_its_most_recent_thousand_entries(window: MainWindow) -> None:
    for media_id in range(1001):
        window._record_view(media_id)

    assert window._view_history == list(range(1, 1001))
    assert window._view_history_index == 999


@pytest.mark.parametrize(
    ("index", "delta"),
    [(0, -1), (1, 1)],
    ids=["back-at-first-entry", "forward-at-last-entry"],
)
def test_view_history_does_not_wrap_at_either_end(
    qtbot: QtBot,
    window: MainWindow,
    collection_dir: Path,
    index: int,
    delta: int,
) -> None:
    session = open_and_wait(qtbot, window, collection_dir)
    history = list(session.state.result_set)
    window._view_history = history
    window._view_history_index = index
    session.state.current_item = history[index]

    window._step_history(delta)

    assert window._view_history_index == index
    assert session.state.current_item == history[index]


def test_view_history_skips_a_file_that_has_been_removed(
    opened_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = opened_window.session
    assert session is not None
    first_id, removed_id = session.state.result_set
    original_get = session.media.get
    monkeypatch.setattr(
        session.media,
        "get",
        lambda media_id: None if media_id == removed_id else original_get(media_id),
    )
    opened_window._view_history = [first_id, removed_id]
    opened_window._view_history_index = 1
    session.state.current_item = removed_id

    opened_window._step_history(-1)

    assert opened_window._view_history_index == 0
    assert session.state.current_item == first_id


@pytest.mark.parametrize("open_folder", [True, False], ids=["folder", "file"])
def test_canceling_an_open_picker_does_not_open_a_path(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, open_folder: bool
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(window, "open_collection", lambda path: opened.append(path))
    if open_folder:
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: "")
        window._prompt_open_folder()
    else:
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: ("", ""))
        window._prompt_open_file()

    assert opened == []


def test_initial_path_uses_startup_lock_handling(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    second = MainWindow(initial_path=collection_dir)
    qtbot.addWidget(second)
    second.show()
    qtbot.waitUntil(lambda: not second.isVisible(), timeout=5000)

    assert second.session is None


def test_manual_open_that_routes_to_an_existing_window_keeps_this_window_open(
    window: MainWindow, collection_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_locked(
        _cls: type[object], path: Path, **_kwargs: object
    ) -> None:
        raise CollectionLockedError(path)

    monkeypatch.setattr(
        "prismic.ui.main_window.PrismicSession.open", classmethod(raise_locked)
    )
    monkeypatch.setattr("prismic.ui.main_window.request_focus", lambda _path: True)
    closed: list[bool] = []
    messages: list[tuple[str, int]] = []
    monkeypatch.setattr(window, "close", lambda: closed.append(True))
    monkeypatch.setattr(
        window._transient_bar,
        "show_message",
        lambda text, timeout: messages.append((text, timeout)),
    )

    window.open_collection(collection_dir)

    assert closed == []
    assert messages == [
        ("That collection is already open — brought its window to the front.", 5000)
    ]
    assert window._central_stack.currentWidget() is window._placeholder


@pytest.mark.parametrize(
    "starting_state",
    [
        Qt.WindowState.WindowMinimized | Qt.WindowState.WindowMaximized,
        Qt.WindowState.WindowMaximized | Qt.WindowState.WindowActive,
    ],
    ids=["restore-minimized", "preserve-existing-active-state"],
)
def test_raise_request_restores_and_activates_the_window(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, starting_state: Qt.WindowState
) -> None:
    requested_states: list[Qt.WindowState] = []
    calls: list[str] = []
    monkeypatch.setattr(window, "windowState", lambda: starting_state)
    monkeypatch.setattr(window, "setWindowState", requested_states.append)
    monkeypatch.setattr(window, "show", lambda: calls.append("show"))
    monkeypatch.setattr(window, "raise_", lambda: calls.append("raise"))
    monkeypatch.setattr(window, "activateWindow", lambda: calls.append("activate"))

    monkeypatch.setattr(
        QApplication,
        "alert",
        lambda _window: calls.append("alert"),
    )

    window._on_raise_requested()

    assert requested_states == [Qt.WindowState.WindowMaximized | Qt.WindowState.WindowActive]
    assert calls == ["show", "raise", "activate", "alert"]


@pytest.mark.parametrize(
    ("operation", "expected_title"),
    [
        ("create", "Could not create tag"),
        ("rename", "Could not rename tag"),
        ("search-create", "Could not create tag"),
    ],
    ids=["create", "rename", "search-create"],
)
def test_unexpected_tag_command_errors_are_reported(
    qtbot: QtBot,
    window: MainWindow,
    collection_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    expected_title: str,
) -> None:
    session = open_and_wait(qtbot, window, collection_dir)
    original_tag = create_tag(window) if operation == "rename" else None

    def fail_execute(_command: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(session, "execute", fail_execute)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "prismic.ui.main_window.MessageDialog.warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    if operation == "create":
        window._on_tag_create("new tag")
    elif operation == "rename":
        assert original_tag is not None
        window._on_tag_rename(original_tag.id, "renamed tag")
    else:
        assert window._create_tag_and_find("new tag") is None

    assert warnings == [(expected_title, "database unavailable")]
    if original_tag is None:
        assert session.tags.list_all() == []
    else:
        assert [tag.name for tag in session.tags.list_all()] == [original_tag.name]


def test_media_path_resolution_handles_missing_session_and_media(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    assert window._resolve_media_path(1) is None

    open_and_wait(qtbot, window, collection_dir)
    session = window.session
    assert session is not None
    media = session.media.list_all()[0]

    assert window._resolve_media_path(media.id) == session.collection.root / media.relative_path
    assert window._resolve_media_path(-1) is None


def test_thumbnail_ready_repaints_only_the_matching_result_row(
    opened_window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_id = opened_window.result_model.media_at(0).id
    updates = []
    monkeypatch.setattr(ResultListView, "update", lambda _self, index: updates.append(index))

    opened_window._on_thumbnail_ready(media_id)
    opened_window._on_thumbnail_ready(-1)

    row = opened_window.result_model.row_for_media_id(media_id)
    assert row is not None
    assert updates == [opened_window.result_model.index(row, 0)]


def test_thumbnail_viewport_tracks_mouse_for_hover_painting(window: MainWindow) -> None:
    assert window.result_list.viewport().hasMouseTracking()


def test_show_thumbnails_menu_action_is_checkable(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    action = window._shortcut_actions[shortcuts.TOGGLE_THUMBNAILS]

    assert action.isCheckable()


def test_unchecked_tag_explains_how_to_number_its_group(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    create_tag(window)
    window._tag_shortcut_mode_action.setChecked(True)
    refresh_and_hover_item_tag(window, 0)

    assert [label.text() for label in window._hover_bar._key_labels] == ["Ctrl"]
    assert window._hover_bar._text_label.text() == "Move quick-select shortcuts to unselected tags"


def test_nonprintable_quick_select_binding_does_not_insert_text(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    window.bindings.set_binding(shortcuts.quick_select_id(0), "F1")
    window._apply_bindings()
    session = window.session
    assert session is not None
    current_item = session.state.result_set[0]
    session.state.current_item = current_item
    window._on_tag_create("a")
    search_box = window.item_tag_panel.search_box
    search_box.setFocus()
    qtbot.waitUntil(lambda: search_box.hasFocus(), timeout=1000)

    qtbot.keyClick(
        window.item_tag_panel.search_box, Qt.Key.Key_F1, Qt.KeyboardModifier.ControlModifier
    )

    assert window.item_tag_panel.search_box.text() == ""
    assert session.mappings.tags_for_media(current_item) == []


@pytest.mark.parametrize(
    ("selected", "message"),
    [
        (True, "Numbering selected tags"),
        (False, "Numbering unselected tags"),
    ],
    ids=["selected", "unselected"],
)
def test_tag_numbering_mode_reports_which_group_is_numbered(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    selected: bool,
    message: str,
) -> None:
    shown: list[tuple[str, int]] = []
    monkeypatch.setattr(
        window._transient_bar, "show_message", lambda text, timeout: shown.append((text, timeout))
    )

    window._apply_tag_shortcut_mode(selected)

    assert shown == [(message, 2000)]


def test_viewer_error_shows_a_five_second_transient_message(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[tuple[str, int]] = []
    monkeypatch.setattr(
        window._transient_bar,
        "show_message",
        lambda text, timeout: shown.append((text, timeout)),
    )

    window._on_viewer_error("unsupported media")

    assert shown == [("Could not load media: unsupported media", 5000)]


@pytest.mark.parametrize(
    ("key", "expected_text"),
    [(Qt.Key.Key_A, "a"), (Qt.Key.Key_Z, "z")],
    ids=["first-letter", "last-letter"],
)
def test_type_ahead_accepts_both_ends_of_the_letter_range(
    qtbot: QtBot,
    window: MainWindow,
    collection_dir: Path,
    key: Qt.Key,
    expected_text: str,
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    window.result_list.setFocus()
    qtbot.waitUntil(lambda: window.result_list.hasFocus(), timeout=1000)

    qtbot.keyClick(window.result_list, key)

    assert window.item_tag_panel.search_box.text() == expected_text


@pytest.mark.parametrize(
    ("focus_mode", "fullscreen"),
    [(False, False), (True, False), (False, True), (True, True)],
    ids=["normal", "focus", "fullscreen", "both"],
)
def test_viewer_controls_are_suppressed_in_either_chrome_free_mode(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
    focus_mode: bool,
    fullscreen: bool,
) -> None:
    focus_blocker = QSignalBlocker(window._focus_mode_action)
    fullscreen_blocker = QSignalBlocker(window.panel_toolbar.fullscreen_button)
    window._focus_mode_action.setChecked(focus_mode)
    window.panel_toolbar.fullscreen_button.setChecked(fullscreen)
    del focus_blocker, fullscreen_blocker
    suppressed: list[bool] = []
    monkeypatch.setattr(window.viewer, "set_controls_suppressed", suppressed.append)

    window._update_viewer_controls()

    assert suppressed == [focus_mode or fullscreen]
