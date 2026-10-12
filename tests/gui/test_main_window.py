from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QByteArray, QSettings, QSignalBlocker, Qt
from PySide6.QtWidgets import QApplication, QFileDialog
from pytestqt.qtbot import QtBot

from prismic.application.commands.mapping_commands import MappingAddCommand
from prismic.application.input import shortcuts
from prismic.domain.tag import Tag
from prismic.persistence.errors import CollectionLockedError
from prismic.ui.column_splitter import ColumnSplitter, _ColumnSplitterHandle
from prismic.ui.main_window import MainWindow
from prismic.ui.result_list_view import ResultListView
from tests.gui._search_helpers import assert_search_box_is_empty
from tests.gui.helpers import (
    create_tag,
    open_and_create_tag,
    open_and_wait,
    refresh_and_hover_item_tag,
)


def _broken_collection(tmp_path: Path) -> Path:
    root = tmp_path / "broken"
    root.mkdir()
    (root / "broken.prismic").write_bytes(b"not a real database")
    return root


def _broken_collection_with_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[str]]:
    return _broken_collection(tmp_path), _capture_critical_messages(monkeypatch)


def _capture_critical_messages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(
        "prismic.ui.main_window.MessageDialog.critical",
        lambda *args, **kwargs: messages.append(args[-1]),
    )
    return messages


def _create_tag_on_current_item(window: MainWindow, name: str) -> tuple[Tag, int]:
    window._on_tag_create(name)
    session = window.session
    assert session is not None
    tag = session.tags.list_all()[0]
    current_id = session.state.result_set[0]
    session.state.current_item = current_id
    window._refresh_all()
    return tag, current_id


def _select_first_item(window: MainWindow) -> int:
    session = window.session
    assert session is not None
    current_id = session.state.result_set[0]
    session.state.current_item = current_id
    window._refresh_all()
    return current_id


def _open_show_and_wait(qtbot: QtBot, window: MainWindow, collection_dir: Path) -> None:
    open_and_wait(qtbot, window, collection_dir)
    window.show()
    qtbot.waitExposed(window)


@pytest.fixture
def shown_window(qtbot: QtBot, window: MainWindow, collection_dir: Path) -> MainWindow:
    _open_show_and_wait(qtbot, window, collection_dir)
    return window


def _assert_no_hover_hint(window: MainWindow, row: int = 10) -> None:
    window._on_item_tag_hover(row)
    assert window._hover_bar._key_labels == []
    assert window._hover_bar._text_label.text() == ""


def _create_tags_on_first_item(
    window: MainWindow, names: tuple[str, ...]
) -> tuple[int, int, dict[str, int]]:
    session = window.session
    assert session is not None
    for name in names:
        window._on_tag_create(name)
    first_id, second_id = session.state.result_set
    session.state.current_item = first_id
    window._refresh_all()
    return first_id, second_id, {tag.name: tag.id for tag in session.tags.list_all()}


def test_initial_path_opens_after_construction_not_synchronously_in_init(
    qtbot: QtBot, collection_dir: Path
) -> None:
    """The open is deferred (QTimer.singleShot(0, ...)) specifically so the
    window is already shown by the time any "could not open" dialog could
    appear -- see the comment in MainWindow.__init__. Constructing must not
    have opened it yet; pumping the event loop afterward should."""
    win = MainWindow(initial_path=collection_dir)
    qtbot.addWidget(win)

    assert win.session is None  # not yet -- still deferred

    qtbot.waitUntil(lambda: win.session is not None, timeout=2000)
    qtbot.waitUntil(lambda: win.result_model.rowCount() == 2, timeout=5000)


def test_initial_path_failure_still_shows_the_error_after_construction(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, shown_messages = _broken_collection_with_messages(tmp_path, monkeypatch)

    win = MainWindow(initial_path=root)
    qtbot.addWidget(win)

    qtbot.waitUntil(lambda: len(shown_messages) == 1, timeout=2000)
    assert win.session is None


def test_window_has_title(window: MainWindow) -> None:
    assert window.windowTitle() == "Prismic"


def test_column_splitter_handle_hitbox_is_wider_than_its_drawn_line(window: MainWindow) -> None:
    # The drawn line itself is still 1px -- see column_splitter.py -- but
    # the draggable area is much wider, so the tags|files and files|viewer
    # dividers are actually easy to grab with the mouse.
    assert window._splitter.handleWidth() == 20
    assert isinstance(window._splitter.handle(1), _ColumnSplitterHandle)


def test_column_splitter_sizes_persist_across_windows(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        "prismic.ui.main_window.QSettings",
        lambda: QSettings(settings_path, QSettings.Format.IniFormat),
    )

    first = MainWindow()
    qtbot.addWidget(first)
    first._splitter.setSizes([111, 222, 333])
    first.close()

    # The write side: closing persists whatever sizes() reported right
    # before close -- not necessarily [111, 222, 333] verbatim, since a
    # never-shown splitter's setSizes() is only a ratio the real layout
    # pass (which never ran here) would otherwise reconcile against each
    # pane's own minimum/size-hint constraints.
    persisted = QSettings(settings_path, QSettings.Format.IniFormat).value(
        "window/columnSplitterSizes"
    )
    assert [int(size) for size in persisted] == first._splitter.sizes()

    # The read side: a fresh window's splitter is seeded from that
    # persisted list, not the hardcoded [190, 260, 830] default.
    captured_sizes: list[list[int]] = []
    monkeypatch.setattr(
        "prismic.ui.column_splitter.ColumnSplitter.setSizes",
        lambda self, sizes: captured_sizes.append(list(sizes)),
    )

    second = MainWindow()
    qtbot.addWidget(second)

    assert captured_sizes == [first._splitter.sizes()]


def test_starts_with_no_collection_open(window: MainWindow) -> None:
    assert window.session is None


def test_opening_a_collection_populates_the_result_list(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)

    assert window.session is not None
    assert window.result_model.rowCount() == 2


def test_scan_progress_bar_is_hidden_once_the_initial_scan_completes(
    shown_window: MainWindow,
) -> None:
    assert shown_window._scan_progress_bar.isHidden()


def test_rescanning_shows_progress_that_reaches_completion(
    qtbot: QtBot, shown_window: MainWindow
) -> None:
    # Nothing changed on disk, so this rescan has the same 2 files -- and
    # the previous scan (opening the collection) also saw 2, so this is the
    # simple case where the progress bar's denominator is exactly right.
    shown_window._rescan()

    assert shown_window._scan_progress_bar.isVisible()
    assert shown_window._scan_progress_bar.maximum() == 0  # reset to indeterminate first
    qtbot.waitUntil(lambda: shown_window._scan_progress_bar.isHidden(), timeout=5000)
    assert shown_window._scan_progress_bar.maximum() == 2
    assert shown_window._scan_progress_bar.value() == 2


def test_opening_a_bad_collection_shows_an_error_not_a_crash(
    qtbot: QtBot, window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, shown_messages = _broken_collection_with_messages(tmp_path, monkeypatch)

    window.open_collection(root)

    assert window.session is None
    assert len(shown_messages) == 1


def test_created_tag_appears_in_the_filter_panel_and_item_tag_hint(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_create_tag(qtbot, window, collection_dir)

    assert [t.name for t in window.session.tags.list_all()] == ["vacation"]  # type: ignore[union-attr]
    assert window.filter_panel.model.rowCount() == 1
    refresh_and_hover_item_tag(window, 0)

    assert [label.text() for label in window._hover_bar._key_labels] == ["1"]
    assert window._hover_bar._text_label.text() == 'Toggle "vacation" on the current item'


@pytest.mark.parametrize("delete", [False, True], ids=["rename", "delete"])
def test_renaming_or_deleting_a_tag_via_the_ui(
    qtbot: QtBot, window: MainWindow, collection_dir: Path, delete: bool
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    tag = create_tag(window)

    if delete:
        window._on_tag_delete(tag.id)
        expected_names = []
    else:
        window._on_tag_rename(tag.id, "travel")
        expected_names = ["travel"]

    assert [tag.name for tag in window.session.tags.list_all()] == expected_names  # type: ignore[union-attr]
    assert window.filter_panel.model.rowCount() == len(expected_names)


def test_filter_selection_narrows_the_result_view(qtbot: QtBot, shown_window: MainWindow) -> None:
    tag = create_tag(shown_window)
    first_media = shown_window.session.media.list_all()[0]  # type: ignore[union-attr]
    shown_window.session.execute(  # type: ignore[union-attr]
        MappingAddCommand(media_id=first_media.id, tag_id=tag.id)
    )
    shown_window._refresh_all()

    shown_window._on_filter_toggle(tag.id)

    assert shown_window.result_model.rowCount() == 1
    assert shown_window.result_model.media_at(0).id == first_media.id

    shown_window._on_filter_toggle(tag.id)  # deselect

    assert shown_window.result_model.rowCount() == 2


def test_item_create_and_check_creates_the_tag_and_maps_it_in_one_step(
    shown_window: MainWindow,
) -> None:
    current_id = _select_first_item(shown_window)

    shown_window._on_item_create_and_check("vacation")

    tags = shown_window.session.tags.list_all()  # type: ignore[union-attr]
    assert [t.name for t in tags] == ["vacation"]
    assert [t.id for t in shown_window.session.mappings.tags_for_media(current_id)] == [  # type: ignore[union-attr]
        tags[0].id
    ]


def test_filter_create_and_check_creates_the_tag_and_activates_the_filter(
    shown_window: MainWindow,
) -> None:
    shown_window._on_filter_create_and_check("vacation")

    tags = shown_window.session.tags.list_all()  # type: ignore[union-attr]
    assert [t.name for t in tags] == ["vacation"]
    assert shown_window.session.state.selected_tag_ids == [tags[0].id]  # type: ignore[union-attr]
    # Nothing is mapped to any file yet -- creating a tag from the filter
    # box narrows the browse list, it doesn't tag whatever's on screen.
    assert shown_window.result_model.rowCount() == 0


def test_item_create_and_check_with_an_existing_exact_name_reuses_it_silently(
    qtbot: QtBot, window: MainWindow, collection_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The search box's Enter flow always asks to "create" the typed name,
    even when a tag by that exact name already exists (see
    `TagPanel._commit_search`'s docstring: Enter never falls back to
    picking a filtered row instead). That's expected, not a mistake, so it
    must apply the existing tag with no duplicate-name warning dialog."""
    open_and_wait(qtbot, window, collection_dir)
    current_id = _select_first_item(window)
    existing = create_tag(window)

    shown: list[str] = []
    monkeypatch.setattr(
        "prismic.ui.main_window.MessageDialog.warning",
        lambda *args, **kwargs: shown.append(args[-1]),
    )

    window._on_item_create_and_check("vacation")

    assert shown == []
    assert [t.name for t in window.session.tags.list_all()] == ["vacation"]  # type: ignore[union-attr]
    assert [t.id for t in window.session.mappings.tags_for_media(current_id)] == [  # type: ignore[union-attr]
        existing.id
    ]


def test_filter_create_and_check_then_deselect_restores_the_full_list(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    """Mirrors a live computer-use repro: create a tag via the filter
    search box (narrows to zero, since nothing's mapped to it yet), then
    toggle it back off and confirm the full list actually comes back --
    not just that `selected_tag_ids` is empty."""
    open_and_wait(qtbot, window, collection_dir)

    window._on_filter_create_and_check("vacation")
    assert window.result_model.rowCount() == 0

    tag = window.session.tags.list_all()[0]  # type: ignore[union-attr]
    window._on_filter_toggle(tag.id)

    assert window.session.state.selected_tag_ids == []  # type: ignore[union-attr]
    assert window.result_model.rowCount() == 2


def test_in_viewer_tag_toggle_maps_the_current_item(
    shown_window: MainWindow,
) -> None:
    tag, current_id = _create_tag_on_current_item(shown_window, "vacation")

    shown_window._on_item_tag_toggle(tag.id)

    assert [t.id for t in shown_window.session.mappings.tags_for_media(current_id)] == [  # type: ignore[union-attr]
        tag.id
    ]

    shown_window._on_item_tag_toggle(tag.id)  # toggle back off

    assert shown_window.session.mappings.tags_for_media(current_id) == []  # type: ignore[union-attr]


@pytest.mark.parametrize("scope", ["item", "filter"])
def test_tag_toggle_clears_its_search_box_without_losing_focus(
    qtbot: QtBot, shown_window: MainWindow, scope: str
) -> None:
    if scope == "item":
        tag, _current_id = _create_tag_on_current_item(shown_window, "vacation")
        panel = shown_window.item_tag_panel
        toggle = shown_window._on_item_tag_toggle
    else:
        tag = create_tag(shown_window)
        shown_window._refresh_all()
        panel = shown_window.filter_panel
        toggle = shown_window._on_filter_toggle

    panel.search_box.setText("vac")
    panel.search_box.setFocus()
    qtbot.waitUntil(lambda: panel.search_box.hasFocus(), timeout=1000)

    toggle(tag.id)

    assert_search_box_is_empty(panel.search_box, keeps_focus=True)


def test_item_tag_hover_past_the_shortcut_group_in_its_own_active_group_clears(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    """Past the first 10 unchecked tags, rows no longer carry a shortcut
    digit (see `_shortcut_digit_for_position`) -- but the unselected group
    is *already* the numbered one by default, so Ctrl can't get this row a
    digit; it would only take the numbering away from unselected tags
    entirely and hand it to selected ones instead. There's no move that
    helps this row, so the hint should go quiet rather than name a group
    that's already numbered (misleadingly implying Ctrl would number it)."""
    open_and_wait(qtbot, window, collection_dir)
    for i in range(11):
        window._on_tag_create(f"tag{i:02d}")
    window._refresh_all()

    _assert_no_hover_hint(window)  # 11th row -- past the 0..9 shortcut group


def test_item_tag_hover_over_selected_group_names_selected_tags(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    """By default shortcuts number the *unselected* group, so a selected
    (checked) tag never shows a digit -- hovering it should say Ctrl
    would move shortcuts to "selected tags", not the generic/wrong
    "unselected tags" text a mode-based (rather than row-based) check
    would produce."""
    open_and_wait(qtbot, window, collection_dir)
    tag = create_tag(window)
    current_id = window.session.state.result_set[0]  # type: ignore[union-attr]
    window.session.state.current_item = current_id  # type: ignore[union-attr]
    window._on_item_tag_toggle(tag.id)  # select it -- moves it into the checked group
    window._refresh_all()

    window._on_item_tag_hover(0)

    assert [label.text() for label in window._hover_bar._key_labels] == ["Ctrl"]
    assert window._hover_bar._text_label.text() == "Move quick-select shortcuts to selected tags"


def test_item_tag_hover_past_the_shortcut_group_mirrors_for_selected_mode(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    """Same overflow-within-the-active-group case as the unselected-mode
    test above, mirrored: with "Number Selected Tags Instead" turned on,
    it's the *selected* group that's numbered, so an 11th+ selected tag
    should clear the hint rather than claim Ctrl would move shortcuts to
    selected tags -- they're already there, and Ctrl would only take them
    away."""
    open_and_wait(qtbot, window, collection_dir)
    for i in range(11):
        window._on_tag_create(f"tag{i:02d}")
    current_id = window.session.state.result_set[0]  # type: ignore[union-attr]
    window.session.state.current_item = current_id  # type: ignore[union-attr]
    for tag in window.session.tags.list_all():  # type: ignore[union-attr]
        window._on_item_tag_toggle(tag.id)  # select every tag
    window._tag_shortcut_mode_action.setChecked(True)  # number the selected group
    window._refresh_all()

    _assert_no_hover_hint(window)  # 11th row -- past the 0..9 shortcut group


def test_recently_clicked_tag_floats_to_the_top_of_both_panels(
    shown_window: MainWindow,
) -> None:
    shown_window._on_tag_create("alpha")
    shown_window._on_tag_create("beta")
    current_id = shown_window.session.state.result_set[0]  # type: ignore[union-attr]
    shown_window.session.state.current_item = current_id  # type: ignore[union-attr]
    shown_window._refresh_all()
    tags_by_name = {t.name: t.id for t in shown_window.session.tags.list_all()}  # type: ignore[union-attr]

    # Alphabetically/popularity "alpha" already sorts first; click "beta"
    # from the filter panel and it should jump ahead of "alpha" in *both*
    # list views, since they share one underlying recency ordering.
    shown_window._on_filter_toggle(tags_by_name["beta"])
    shown_window._on_filter_toggle(tags_by_name["beta"])  # deselect again, click still counts

    assert shown_window.filter_panel.model.tag_at(0).name == "beta"
    assert shown_window.item_tag_panel.model.tag_at(0).name == "beta"


def _create_tags_with_gamma_then_alpha_checked(
    window: MainWindow,
) -> dict[str, int]:
    _first_id, _second_id, tags_by_name = _create_tags_on_first_item(
        window, ("alpha", "beta", "gamma")
    )
    window._on_item_tag_toggle(tags_by_name["gamma"])
    window._on_item_tag_toggle(tags_by_name["alpha"])
    return tags_by_name


def test_checking_a_tag_appends_it_to_the_bottom_of_the_checked_group(
    shown_window: MainWindow,
) -> None:
    """Checking "alpha" after "gamma" should leave gamma on top -- the
    popularity/recency algorithm would in fact put alpha first (it's the
    more recently clicked one), so this only passes if checking really is
    appending to a stable order rather than re-running that algorithm."""
    _create_tags_with_gamma_then_alpha_checked(shown_window)

    assert shown_window.item_tag_panel.model.tag_at(0).name == "gamma"
    assert shown_window.item_tag_panel.model.tag_at(1).name == "alpha"


def test_unchecking_a_tag_drops_it_without_reordering_the_rest(
    shown_window: MainWindow,
) -> None:
    tags_by_name = _create_tags_with_gamma_then_alpha_checked(shown_window)
    shown_window._on_item_tag_toggle(tags_by_name["beta"])
    # stable order is now gamma, alpha, beta -- uncheck the middle one
    shown_window._on_item_tag_toggle(tags_by_name["alpha"])

    assert shown_window.item_tag_panel.model.tag_at(0).name == "gamma"
    assert shown_window.item_tag_panel.model.tag_at(1).name == "beta"


def test_switching_files_resorts_the_checked_group_by_the_usual_algorithm(
    shown_window: MainWindow,
) -> None:
    first_id, second_id, tags_by_name = _create_tags_on_first_item(shown_window, ("alpha", "gamma"))

    shown_window._on_item_tag_toggle(tags_by_name["gamma"])
    shown_window._on_item_tag_toggle(tags_by_name["alpha"])
    assert shown_window.item_tag_panel.model.tag_at(0).name == "gamma"  # stable append order

    # Switch to the other file and back -- reloading file 1 again should
    # re-sort it by the usual (recency) algorithm, which puts alpha first
    # since it was clicked more recently than gamma.
    shown_window.session.state.current_item = second_id  # type: ignore[union-attr]
    shown_window._refresh_all()
    shown_window.session.state.current_item = first_id  # type: ignore[union-attr]
    shown_window._refresh_all()

    assert shown_window.item_tag_panel.model.tag_at(0).name == "alpha"


@pytest.mark.parametrize(
    ("orientation", "expected_rect"),
    [
        (Qt.Orientation.Horizontal, (4, 0, 1, 40)),
        (Qt.Orientation.Vertical, (0, 19, 10, 1)),
    ],
    ids=["horizontal", "vertical"],
)
def test_column_splitter_draws_a_one_pixel_centered_line(
    qtbot: QtBot,
    orientation: Qt.Orientation,
    expected_rect: tuple[int, int, int, int],
) -> None:
    splitter = ColumnSplitter(orientation)
    qtbot.addWidget(splitter)
    handle = splitter.createHandle()
    handle.resize(10, 40)

    rect = handle._line_rect()

    assert (rect.x(), rect.y(), rect.width(), rect.height()) == expected_rect


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


@pytest.fixture
def opened_window(qtbot: QtBot, window: MainWindow, collection_dir: Path) -> MainWindow:
    open_and_wait(qtbot, window, collection_dir)
    return window


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
    def raise_locked(_cls: type[object], path: Path, **_kwargs: object) -> None:
        raise CollectionLockedError(path)

    monkeypatch.setattr("prismic.ui.main_window.PrismicSession.open", classmethod(raise_locked))
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
