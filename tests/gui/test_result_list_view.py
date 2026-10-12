from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView
from pytestqt.qtbot import QtBot

from prismic.domain.media import Media, MediaState
from prismic.ui.result_list_view import ResultListView
from prismic.ui.result_model import ResultListModel


def _media(media_id: int, path: str) -> Media:
    return Media(
        id=media_id,
        relative_path=path,
        content_hash=path,
        size=0,
        mtime=0.0,
        state=MediaState.ACTIVE,
    )


def _build(qtbot: QtBot, count: int = 6) -> ResultListView:
    model = ResultListModel()
    model.set_media([_media(i, f"{i}.jpg") for i in range(count)])
    view = ResultListView()
    view.setModel(model)
    qtbot.addWidget(view)
    view.resize(200, 400)
    view.show()
    qtbot.waitExposed(view)
    return view


def _click(
    qtbot: QtBot,
    view: ResultListView,
    row: int,
    modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> None:
    model = view.model()
    assert model is not None
    index = model.index(row, 0)
    rect = view.visualRect(index)
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, modifier, pos=rect.center())


def _selected_rows(view: ResultListView) -> list[int]:
    return sorted(i.row() for i in view.selectionModel().selectedIndexes())


def _select_first_and_third(qtbot: QtBot, view: ResultListView) -> None:
    _click(qtbot, view, 1)
    _click(qtbot, view, 3, Qt.KeyboardModifier.ControlModifier)


def _view_with_first_and_third_selected(qtbot: QtBot) -> ResultListView:
    view = _build(qtbot)
    _select_first_and_third(qtbot, view)
    return view


def test_extended_selection_mode_is_set(qtbot: QtBot) -> None:
    # `qtbot` is unused beyond guaranteeing a `QApplication` exists before
    # any widget is constructed -- without it, this crashes the whole
    # process natively rather than raising a catchable Python error.
    view = ResultListView()
    qtbot.addWidget(view)

    assert view.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection


def test_plain_click_selects_only_that_row(qtbot: QtBot) -> None:
    view = _build(qtbot)

    _click(qtbot, view, 1)
    _click(qtbot, view, 3)

    assert _selected_rows(view) == [3]


def test_ctrl_click_adds_an_unselected_row(qtbot: QtBot) -> None:
    view = _view_with_first_and_third_selected(qtbot)

    assert _selected_rows(view) == [1, 3]


def test_ctrl_click_on_an_already_selected_row_deselects_it(qtbot: QtBot) -> None:
    """Ctrl-click is a full toggle, same as Qt's own default -- the one
    respect in which this view doesn't override the default behavior."""
    view = _build(qtbot)

    _click(qtbot, view, 2)
    _click(qtbot, view, 2, Qt.KeyboardModifier.ControlModifier)

    assert _selected_rows(view) == []


def test_ctrl_click_deselecting_one_row_leaves_others_selected(qtbot: QtBot) -> None:
    view = _view_with_first_and_third_selected(qtbot)  # 1 and 3 selected
    _click(qtbot, view, 1, Qt.KeyboardModifier.ControlModifier)  # deselect 1

    assert _selected_rows(view) == [3]


def test_shift_click_selects_inclusive_range_from_nearest_selected(qtbot: QtBot) -> None:
    view = _build(qtbot)

    _click(qtbot, view, 1)
    _click(qtbot, view, 4, Qt.KeyboardModifier.ShiftModifier)

    assert _selected_rows(view) == [1, 2, 3, 4]


def test_shift_click_does_not_deselect_existing_selection_outside_the_range(qtbot: QtBot) -> None:
    view = _build(qtbot)

    _click(qtbot, view, 0)
    _click(qtbot, view, 5, Qt.KeyboardModifier.ControlModifier)  # 0 and 5 both selected
    _click(qtbot, view, 2, Qt.KeyboardModifier.ShiftModifier)  # nearest to row 2 is row 0

    assert _selected_rows(view) == [0, 1, 2, 5]


def test_shift_click_uses_the_nearest_selected_row_not_the_first(qtbot: QtBot) -> None:
    view = _build(qtbot, count=9)

    _click(qtbot, view, 2)
    _click(qtbot, view, 7, Qt.KeyboardModifier.ControlModifier)  # 2 and 7 both selected
    _click(qtbot, view, 4, Qt.KeyboardModifier.ShiftModifier)  # row 2 is three rows away

    assert _selected_rows(view) == [2, 3, 4, 7]


def test_shift_click_with_nothing_selected_behaves_like_a_plain_add(qtbot: QtBot) -> None:
    view = _build(qtbot)

    _click(qtbot, view, 2, Qt.KeyboardModifier.ShiftModifier)

    assert _selected_rows(view) == [2]
