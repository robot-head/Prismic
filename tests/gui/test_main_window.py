from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from prismic.application.commands.mapping_commands import MappingAddCommand
from prismic.domain.tag import Tag
from prismic.ui.column_splitter import _ColumnSplitterHandle
from prismic.ui.main_window import MainWindow
from tests.gui.helpers import open_and_wait, refresh_and_hover_item_tag


def _broken_collection(tmp_path: Path) -> Path:
    root = tmp_path / "broken"
    root.mkdir()
    (root / "broken.prismic").write_bytes(b"not a real database")
    return root


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
    root = _broken_collection(tmp_path)
    shown_messages = _capture_critical_messages(monkeypatch)

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
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)

    assert window._scan_progress_bar.isHidden()


def test_rescanning_shows_progress_that_reaches_completion(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    _open_show_and_wait(qtbot, window, collection_dir)

    # Nothing changed on disk, so this rescan has the same 2 files -- and
    # the previous scan (opening the collection) also saw 2, so this is the
    # simple case where the progress bar's denominator is exactly right.
    window._rescan()

    assert window._scan_progress_bar.isVisible()
    assert window._scan_progress_bar.maximum() == 0  # reset to indeterminate first
    qtbot.waitUntil(lambda: window._scan_progress_bar.isHidden(), timeout=5000)
    assert window._scan_progress_bar.maximum() == 2
    assert window._scan_progress_bar.value() == 2


def test_opening_a_bad_collection_shows_an_error_not_a_crash(
    qtbot: QtBot, window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _broken_collection(tmp_path)
    shown_messages = _capture_critical_messages(monkeypatch)

    window.open_collection(root)

    assert window.session is None
    assert len(shown_messages) == 1


def test_create_tag_via_the_ui_appears_in_the_filter_panel(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)

    window._on_tag_create("vacation")

    assert [t.name for t in window.session.tags.list_all()] == ["vacation"]  # type: ignore[union-attr]
    assert window.filter_panel.model.rowCount() == 1


@pytest.mark.parametrize("delete", [False, True], ids=["rename", "delete"])
def test_renaming_or_deleting_a_tag_via_the_ui(
    qtbot: QtBot, window: MainWindow, collection_dir: Path, delete: bool
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    window._on_tag_create("vacation")
    tag = window.session.tags.list_all()[0]  # type: ignore[union-attr]

    if delete:
        window._on_tag_delete(tag.id)
        expected_names = []
    else:
        window._on_tag_rename(tag.id, "travel")
        expected_names = ["travel"]

    assert [tag.name for tag in window.session.tags.list_all()] == expected_names  # type: ignore[union-attr]
    assert window.filter_panel.model.rowCount() == len(expected_names)


def test_filter_selection_narrows_the_result_view(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    window._on_tag_create("vacation")
    tag = window.session.tags.list_all()[0]  # type: ignore[union-attr]
    first_media = window.session.media.list_all()[0]  # type: ignore[union-attr]
    window.session.execute(  # type: ignore[union-attr]
        MappingAddCommand(media_id=first_media.id, tag_id=tag.id)
    )
    window._refresh_all()

    window._on_filter_toggle(tag.id)

    assert window.result_model.rowCount() == 1
    assert window.result_model.media_at(0).id == first_media.id

    window._on_filter_toggle(tag.id)  # deselect

    assert window.result_model.rowCount() == 2


def test_item_create_and_check_creates_the_tag_and_maps_it_in_one_step(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    current_id = _select_first_item(window)

    window._on_item_create_and_check("vacation")

    tags = window.session.tags.list_all()  # type: ignore[union-attr]
    assert [t.name for t in tags] == ["vacation"]
    assert [t.id for t in window.session.mappings.tags_for_media(current_id)] == [  # type: ignore[union-attr]
        tags[0].id
    ]


def test_filter_create_and_check_creates_the_tag_and_activates_the_filter(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)

    window._on_filter_create_and_check("vacation")

    tags = window.session.tags.list_all()  # type: ignore[union-attr]
    assert [t.name for t in tags] == ["vacation"]
    assert window.session.state.selected_tag_ids == [tags[0].id]  # type: ignore[union-attr]
    # Nothing is mapped to any file yet -- creating a tag from the filter
    # box narrows the browse list, it doesn't tag whatever's on screen.
    assert window.result_model.rowCount() == 0


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
    window._on_tag_create("vacation")
    existing = window.session.tags.list_all()[0]  # type: ignore[union-attr]

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
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    tag, current_id = _create_tag_on_current_item(window, "vacation")

    window._on_item_tag_toggle(tag.id)

    assert [t.id for t in window.session.mappings.tags_for_media(current_id)] == [  # type: ignore[union-attr]
        tag.id
    ]

    window._on_item_tag_toggle(tag.id)  # toggle back off

    assert window.session.mappings.tags_for_media(current_id) == []  # type: ignore[union-attr]


def test_item_tag_toggle_clears_its_search_box_without_losing_focus(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    _open_show_and_wait(qtbot, window, collection_dir)
    tag, _current_id = _create_tag_on_current_item(window, "vacation")
    window.item_tag_panel.search_box.setText("vac")
    window.item_tag_panel.search_box.setFocus()
    qtbot.waitUntil(lambda: window.item_tag_panel.search_box.hasFocus(), timeout=1000)

    window._on_item_tag_toggle(tag.id)

    assert window.item_tag_panel.search_box.text() == ""
    assert window.item_tag_panel.search_box.hasFocus()


def test_filter_toggle_clears_its_search_box_without_losing_focus(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    _open_show_and_wait(qtbot, window, collection_dir)
    window._on_tag_create("vacation")
    tag = window.session.tags.list_all()[0]  # type: ignore[union-attr]
    window._refresh_all()
    window.filter_panel.search_box.setText("vac")
    window.filter_panel.search_box.setFocus()
    qtbot.waitUntil(lambda: window.filter_panel.search_box.hasFocus(), timeout=1000)

    window._on_filter_toggle(tag.id)

    assert window.filter_panel.search_box.text() == ""
    assert window.filter_panel.search_box.hasFocus()


def test_item_tag_hover_shows_digit_hint_within_the_shortcut_group(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    window._on_tag_create("vacation")
    refresh_and_hover_item_tag(window, 0)

    assert [label.text() for label in window._hover_bar._key_labels] == ["1"]
    assert window._hover_bar._text_label.text() == 'Toggle "vacation" on the current item'


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
    window._on_tag_create("vacation")
    tag = window.session.tags.list_all()[0]  # type: ignore[union-attr]
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
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    window._on_tag_create("alpha")
    window._on_tag_create("beta")
    current_id = window.session.state.result_set[0]  # type: ignore[union-attr]
    window.session.state.current_item = current_id  # type: ignore[union-attr]
    window._refresh_all()
    tags_by_name = {t.name: t.id for t in window.session.tags.list_all()}  # type: ignore[union-attr]

    # Alphabetically/popularity "alpha" already sorts first; click "beta"
    # from the filter panel and it should jump ahead of "alpha" in *both*
    # list views, since they share one underlying recency ordering.
    window._on_filter_toggle(tags_by_name["beta"])
    window._on_filter_toggle(tags_by_name["beta"])  # deselect again, click still counts

    assert window.filter_panel.model.tag_at(0).name == "beta"
    assert window.item_tag_panel.model.tag_at(0).name == "beta"


def _create_tags_with_gamma_then_alpha_checked(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> dict[str, int]:
    open_and_wait(qtbot, window, collection_dir)
    _first_id, _second_id, tags_by_name = _create_tags_on_first_item(
        window, ("alpha", "beta", "gamma")
    )
    window._on_item_tag_toggle(tags_by_name["gamma"])
    window._on_item_tag_toggle(tags_by_name["alpha"])
    return tags_by_name


def test_checking_a_tag_appends_it_to_the_bottom_of_the_checked_group(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    """Checking "alpha" after "gamma" should leave gamma on top -- the
    popularity/recency algorithm would in fact put alpha first (it's the
    more recently clicked one), so this only passes if checking really is
    appending to a stable order rather than re-running that algorithm."""
    _create_tags_with_gamma_then_alpha_checked(qtbot, window, collection_dir)

    assert window.item_tag_panel.model.tag_at(0).name == "gamma"
    assert window.item_tag_panel.model.tag_at(1).name == "alpha"


def test_unchecking_a_tag_drops_it_without_reordering_the_rest(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    tags_by_name = _create_tags_with_gamma_then_alpha_checked(qtbot, window, collection_dir)
    window._on_item_tag_toggle(tags_by_name["beta"])
    # stable order is now gamma, alpha, beta -- uncheck the middle one
    window._on_item_tag_toggle(tags_by_name["alpha"])

    assert window.item_tag_panel.model.tag_at(0).name == "gamma"
    assert window.item_tag_panel.model.tag_at(1).name == "beta"


def test_switching_files_resorts_the_checked_group_by_the_usual_algorithm(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> None:
    open_and_wait(qtbot, window, collection_dir)
    first_id, second_id, tags_by_name = _create_tags_on_first_item(window, ("alpha", "gamma"))

    window._on_item_tag_toggle(tags_by_name["gamma"])
    window._on_item_tag_toggle(tags_by_name["alpha"])
    assert window.item_tag_panel.model.tag_at(0).name == "gamma"  # stable append order

    # Switch to the other file and back -- reloading file 1 again should
    # re-sort it by the usual (recency) algorithm, which puts alpha first
    # since it was clicked more recently than gamma.
    window.session.state.current_item = second_id  # type: ignore[union-attr]
    window._refresh_all()
    window.session.state.current_item = first_id  # type: ignore[union-attr]
    window._refresh_all()

    assert window.item_tag_panel.model.tag_at(0).name == "alpha"
