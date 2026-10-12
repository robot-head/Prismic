"""The shuffle/full-screen toolbar row above the item-tags panel."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPainterPath, QPaintEvent, QPixmap
from pytestqt.qtbot import QtBot

from prismic.domain.media import Media
from prismic.ui import panel_toolbar, theme
from prismic.ui.main_window import MainWindow
from prismic.ui.panel_toolbar import (
    FullScreenButton,
    PanelToolbar,
    RedoButton,
    ShuffleButton,
    UndoButton,
)
from tests.gui._media_helpers import make_media


@pytest.fixture
def open_window(qtbot: QtBot, window: MainWindow, collection_dir: Path) -> MainWindow:
    window.open_collection(collection_dir)
    qtbot.waitUntil(lambda: window.result_model.rowCount() == 2, timeout=5000)
    return window


def _toggle_shuffle_once(
    qtbot: QtBot, window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> list[int]:
    session = window.session
    assert session is not None
    original_order = list(session.state.result_set)
    monkeypatch.setattr("random.shuffle", lambda seq: seq.reverse())
    qtbot.mouseClick(window.panel_toolbar.shuffle_button, Qt.MouseButton.LeftButton)
    return original_order


def _create_tag_change(window: MainWindow):
    session = window.session
    assert session is not None
    window._on_tag_create("vacation")
    return session


@pytest.fixture
def shuffled_state(
    qtbot: QtBot, open_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> tuple[MainWindow, list[int]]:
    return open_window, _toggle_shuffle_once(qtbot, open_window, monkeypatch)


def _media(media_id: int, path: str) -> Media:
    return make_media(media_id=media_id, relative_path=path)


def _enter_fullscreen(qtbot: QtBot, window: MainWindow) -> None:
    qtbot.mouseClick(window.panel_toolbar.fullscreen_button, Qt.MouseButton.LeftButton)
    assert window.isFullScreen()


def _exit_fullscreen(qtbot: QtBot, window: MainWindow) -> None:
    qtbot.mouseClick(window.panel_toolbar.fullscreen_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not window.isFullScreen(), timeout=1000)


# -- The row itself -----------------------------------------------------------


def test_the_toolbar_has_a_shuffle_and_a_fullscreen_button(window: MainWindow) -> None:
    assert window.panel_toolbar.shuffle_button.isCheckable()
    assert window.panel_toolbar.fullscreen_button.isCheckable()
    assert not window.panel_toolbar.shuffle_button.isChecked()
    assert not window.panel_toolbar.fullscreen_button.isChecked()


def test_the_toolbar_has_undo_and_redo_buttons_disabled_with_no_history(window: MainWindow) -> None:
    assert not window.panel_toolbar.undo_button.isCheckable()
    assert not window.panel_toolbar.redo_button.isCheckable()
    assert not window.panel_toolbar.undo_button.isEnabled()
    assert not window.panel_toolbar.redo_button.isEnabled()


def test_toolbar_icon_colors_follow_toggle_and_enabled_state(window: MainWindow) -> None:
    toolbar = window.panel_toolbar

    assert toolbar.shuffle_button._icon_color() == theme.TEXT_SECONDARY
    toolbar.shuffle_button.setChecked(True)
    assert toolbar.shuffle_button._icon_color() == theme.KEYCAP_BORDER
    assert not toolbar.undo_button.isEnabled()
    assert toolbar.undo_button._icon_color() == theme.BORDER
    toolbar.undo_button.setEnabled(True)
    assert toolbar.undo_button._icon_color() == theme.TEXT_SECONDARY
    toolbar.undo_button.setEnabled(False)
    assert toolbar.undo_button._icon_color() == theme.BORDER
    toolbar.undo_button.setEnabled(False)
    assert toolbar.undo_button._icon_color() == theme.BORDER


def test_a_tag_change_enables_undo_and_a_click_reverts_it(
    qtbot: QtBot, open_window: MainWindow
) -> None:
    session = _create_tag_change(open_window)
    assert open_window.panel_toolbar.undo_button.isEnabled()
    assert not open_window.panel_toolbar.redo_button.isEnabled()

    qtbot.mouseClick(open_window.panel_toolbar.undo_button, Qt.MouseButton.LeftButton)

    assert session.tags.list_all() == []
    assert not open_window.panel_toolbar.undo_button.isEnabled()
    assert open_window.panel_toolbar.redo_button.isEnabled()


def test_a_click_on_redo_reapplies_the_undone_change(qtbot: QtBot, open_window: MainWindow) -> None:
    session = _create_tag_change(open_window)
    qtbot.mouseClick(open_window.panel_toolbar.undo_button, Qt.MouseButton.LeftButton)

    qtbot.mouseClick(open_window.panel_toolbar.redo_button, Qt.MouseButton.LeftButton)

    assert [t.name for t in session.tags.list_all()] == ["vacation"]
    assert open_window.panel_toolbar.undo_button.isEnabled()
    assert not open_window.panel_toolbar.redo_button.isEnabled()


def test_the_toolbar_matches_the_panel_titles_own_height(window: MainWindow) -> None:
    """ "The same height as the box containing the label 'Edit this
    file'" -- queried from that label directly rather than a hard-coded
    guess at it, so a font/padding change to one keeps the other in
    step."""
    assert window.panel_toolbar.height() == window.item_tag_panel.title_label.sizeHint().height()


def test_focus_mode_hides_the_toolbar_too(qtbot: QtBot, window: MainWindow) -> None:
    """Focus Mode hides `_left_column` as a whole, not `_tag_splitter`
    directly -- the toolbar sits in that same column, above the
    splitter, and should disappear right along with it."""
    window.result_list.setFocus()
    qtbot.waitUntil(lambda: window.result_list.hasFocus(), timeout=1000)

    qtbot.keyClick(window.result_list, Qt.Key.Key_Space)

    assert window.panel_toolbar.isVisible() is False


# -- _reordered_by_shuffle, in isolation ---------------------------------------
# No session or collection needed -- the method only ever touches
# `self._shuffled_order`.


def test_a_fresh_shuffle_list_contains_every_id_exactly_once(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each new id is spliced in at a random position relative to what's
    already placed -- with nothing placed yet, that's still a genuine
    random choice per insertion (not necessarily arrival order), so this
    only pins membership, not a specific arrangement. `random.randint` is
    pinned to "always append" here purely to make the assertion
    deterministic to write, not because that's the only order this could
    produce."""
    monkeypatch.setattr("random.randint", lambda _lo, hi: hi)
    media = [_media(1, "a"), _media(2, "b"), _media(3, "c")]

    reordered = window._reordered_by_shuffle(media)

    assert {m.id for m in reordered} == {1, 2, 3}
    assert window._shuffled_order == [1, 2, 3]


def test_an_established_order_is_not_reshuffled_on_a_later_call(window: MainWindow) -> None:
    media = [_media(1, "a"), _media(2, "b"), _media(3, "c")]
    window._shuffled_order = [3, 1, 2]  # some arrangement from an earlier shuffle

    reordered = window._reordered_by_shuffle(media)

    assert [m.id for m in reordered] == [3, 1, 2]


def test_an_item_that_is_no_longer_eligible_is_dropped(window: MainWindow) -> None:
    window._shuffled_order = [3, 1, 2]

    reordered = window._reordered_by_shuffle([_media(1, "a"), _media(2, "b")])  # 3 is gone

    assert [m.id for m in reordered] == [1, 2]
    assert window._shuffled_order == [1, 2]


def test_a_newly_eligible_item_is_spliced_in_at_a_random_position(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window._shuffled_order = [1, 2]
    monkeypatch.setattr("random.randint", lambda _lo, _hi: 1)  # deterministic: the middle

    reordered = window._reordered_by_shuffle([_media(1, "a"), _media(2, "b"), _media(3, "c")])

    assert [m.id for m in reordered] == [1, 3, 2]


# -- Shuffle, through the real button ------------------------------------------


def test_toggling_shuffle_reorders_the_result_list(
    shuffled_state: tuple[MainWindow, list[int]],
) -> None:
    open_window, original_order = shuffled_state

    assert open_window._display_order == list(reversed(original_order))
    assert open_window.result_model.media_at(0).id == original_order[-1]


def test_the_shuffled_arrangement_survives_an_unrelated_refresh(
    qtbot: QtBot, open_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tagging a file re-triggers `_refresh_all()`, which re-runs the
    shuffle logic -- it must reapply the existing arrangement, not draw a
    brand-new random one on every unrelated change."""
    monkeypatch.setattr("random.shuffle", lambda seq: seq.reverse())
    qtbot.mouseClick(open_window.panel_toolbar.shuffle_button, Qt.MouseButton.LeftButton)
    shuffled_order = list(open_window._display_order)

    open_window._on_tag_create("vacation")

    assert open_window._display_order == shuffled_order


def test_toggling_shuffle_off_restores_the_natural_order(
    qtbot: QtBot, shuffled_state: tuple[MainWindow, list[int]]
) -> None:
    open_window, original_order = shuffled_state

    qtbot.mouseClick(open_window.panel_toolbar.shuffle_button, Qt.MouseButton.LeftButton)

    assert open_window._display_order == original_order


def test_turning_shuffle_on_again_draws_a_fresh_order_not_the_old_one(
    qtbot: QtBot, open_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[int]] = []

    def fake_shuffle(seq: list[int]) -> None:
        calls.append(list(seq))
        seq.reverse()

    monkeypatch.setattr("random.shuffle", fake_shuffle)

    qtbot.mouseClick(open_window.panel_toolbar.shuffle_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(open_window.panel_toolbar.shuffle_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(open_window.panel_toolbar.shuffle_button, Qt.MouseButton.LeftButton)

    assert len(calls) == 2  # once per turning-on, not on the turning-off in between


def test_navigation_follows_the_shuffled_order(
    qtbot: QtBot, open_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = open_window.session
    assert session is not None
    monkeypatch.setattr("random.shuffle", lambda seq: seq.reverse())
    qtbot.mouseClick(open_window.panel_toolbar.shuffle_button, Qt.MouseButton.LeftButton)
    shuffled_first, shuffled_second = open_window._display_order
    session.state.current_item = shuffled_first
    open_window._sync_result_selection()

    qtbot.keyClick(open_window.result_list, Qt.Key.Key_Right)

    assert session.state.current_item == shuffled_second


# -- True full screen -----------------------------------------------------------


def test_toggling_fullscreen_enters_real_fullscreen(qtbot: QtBot, window: MainWindow) -> None:
    _enter_fullscreen(qtbot, window)


def test_toggling_fullscreen_off_leaves_it(qtbot: QtBot, window: MainWindow) -> None:
    _enter_fullscreen(qtbot, window)
    _exit_fullscreen(qtbot, window)


@pytest.mark.parametrize("was_maximized", [True, False], ids=["maximized", "normal"])
def test_leaving_fullscreen_restores_the_previous_window_state(
    qtbot: QtBot, window: MainWindow, was_maximized: bool
) -> None:
    if was_maximized:
        window.showMaximized()
        qtbot.waitUntil(lambda: window.isMaximized(), timeout=1000)
    else:
        window.showNormal()
        qtbot.waitUntil(
            lambda: not window.isMaximized() and not window.isFullScreen(), timeout=1000
        )
        window.setGeometry(50, 60, 700, 500)
        original_geometry = window.geometry()

    _enter_fullscreen(qtbot, window)
    _exit_fullscreen(qtbot, window)
    assert window.isMaximized() is was_maximized
    if not was_maximized:
        assert window.geometry() == original_geometry


def test_any_key_exits_fullscreen(qtbot: QtBot, window: MainWindow) -> None:
    _enter_fullscreen(qtbot, window)

    qtbot.keyClick(window, Qt.Key.Key_A)

    assert not window.isFullScreen()
    assert not window.panel_toolbar.fullscreen_button.isChecked()


def test_any_click_exits_fullscreen(qtbot: QtBot, window: MainWindow) -> None:
    _enter_fullscreen(qtbot, window)

    qtbot.mouseClick(window.item_tag_panel.header, Qt.MouseButton.LeftButton)

    assert not window.isFullScreen()


def test_the_exiting_click_does_nothing_else(qtbot: QtBot, window: MainWindow) -> None:
    """The whole point of "any key or click" is that it's swallowed
    entirely -- a click that would otherwise have toggled shuffle just
    exits full screen instead, on the first click. A second click is a
    perfectly ordinary one again."""
    qtbot.mouseClick(window.panel_toolbar.fullscreen_button, Qt.MouseButton.LeftButton)
    assert window.isFullScreen()

    qtbot.mouseClick(window.panel_toolbar.shuffle_button, Qt.MouseButton.LeftButton)

    assert not window.isFullScreen()
    assert not window.panel_toolbar.shuffle_button.isChecked()

    qtbot.mouseClick(window.panel_toolbar.shuffle_button, Qt.MouseButton.LeftButton)

    assert window.panel_toolbar.shuffle_button.isChecked()


# -- Keyboard shortcuts -------------------------------------------------------
# Both buttons are plain QToolButtons with no QAction behind them, so
# these go through KeyboardController's generic dispatch rather than a
# QAction's own QShortcut -- worth covering directly rather than trusting
# the wiring by inspection.


def test_ctrl_r_shuffles_by_default(qtbot: QtBot, open_window: MainWindow) -> None:
    """Rescan is menu-only (no shortcut of its own -- see `shortcuts.py`),
    so Shuffle's default of Ctrl+R doesn't collide with anything and just
    fires directly."""
    open_window.result_list.setFocus()
    qtbot.waitUntil(lambda: open_window.result_list.hasFocus(), timeout=1000)

    qtbot.keyClick(open_window.result_list, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)

    assert open_window.panel_toolbar.shuffle_button.isChecked()


def test_ctrl_f_toggles_fullscreen(qtbot: QtBot, open_window: MainWindow) -> None:
    open_window.result_list.setFocus()
    qtbot.waitUntil(lambda: open_window.result_list.hasFocus(), timeout=1000)

    qtbot.keyClick(open_window.result_list, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)

    assert open_window.panel_toolbar.fullscreen_button.isChecked()
    assert open_window.isFullScreen()


class _Pen:
    def color(self) -> str:
        return "icon-color"


class _Painter:
    """Small recorder for the geometric arguments passed to QPainter."""

    def __init__(self) -> None:
        self.paths: list[QPainterPath] = []
        self.polygons: list[object] = []
        self.lines: list[tuple[int, int, int, int]] = []
        self.pixmaps: list[tuple[object, QPixmap]] = []
        self.fills: list[tuple[object, object]] = []
        self.clip_paths: list[QPainterPath] = []
        self.pens: list[object] = []
        self.save_depth = 0

    def setRenderHint(self, _hint: object) -> None:
        pass

    def pen(self) -> _Pen:
        return _Pen()

    def setPen(self, _pen: object) -> None:
        self.pens.append(_pen)

    def setBrush(self, _brush: object) -> None:
        pass

    def drawPath(self, path: QPainterPath) -> None:
        self.paths.append(path)

    def drawPolygon(self, polygon: object) -> None:
        self.polygons.append(polygon)

    def drawLine(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.lines.append((x1, y1, x2, y2))

    def save(self) -> None:
        self.save_depth += 1

    def restore(self) -> None:
        self.save_depth -= 1

    def setClipPath(self, path: QPainterPath) -> None:
        self.clip_paths.append(path)

    def drawPixmap(self, point: object, pixmap: QPixmap) -> None:
        self.pixmaps.append((point, pixmap))

    def fillRect(self, rect: object, color: object) -> None:
        self.fills.append((rect, color))


def _path_points(path: QPainterPath) -> list[tuple[float, float]]:
    return [(path.elementAt(i).x, path.elementAt(i).y) for i in range(path.elementCount())]


def test_toolbar_icons_keep_their_size_and_point_the_chevrons_outward(qtbot) -> None:
    undo = UndoButton()
    redo = RedoButton()
    qtbot.addWidget(undo)
    qtbot.addWidget(redo)

    assert undo.size().width() == undo.size().height() == 22
    assert redo.size().width() == redo.size().height() == 22

    rect = QRect(10, 20, 40, 30)
    undo_painter = _Painter()
    redo_painter = _Painter()
    undo._paint_icon(undo_painter, rect)  # type: ignore[arg-type]
    redo._paint_icon(redo_painter, rect)  # type: ignore[arg-type]

    assert sum(_path_points(undo_painter.paths[0]), ()) == pytest.approx(
        (40.2, 23.8, 17.8, 34, 40.2, 44.2)
    )
    assert sum(_path_points(redo_painter.paths[0]), ()) == pytest.approx(
        (17.8, 23.8, 40.2, 34, 17.8, 44.2)
    )


class _EventPainter(_Painter):
    class RenderHint:
        Antialiasing = object()

    last: _EventPainter | None = None

    def __init__(self, *_args: object) -> None:
        super().__init__()
        _EventPainter.last = self

    def end(self) -> None:
        pass


def test_button_paints_inside_the_five_pixel_icon_margin(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    button = UndoButton()
    qtbot.addWidget(button)
    button.show()
    qtbot.waitExposed(button)
    painted_rects: list[QRect] = []
    monkeypatch.setattr(
        UndoButton,
        "_paint_icon",
        lambda _self, _painter, rect: painted_rects.append(rect),
    )
    monkeypatch.setattr(panel_toolbar, "QPainter", _EventPainter)

    button.paintEvent(QPaintEvent(button.rect()))

    assert painted_rects[-1] == QRect(5, 5, 12, 12)
    painter = _EventPainter.last
    assert painter is not None
    assert [pen.widthF() for pen in painter.pens] == [1.5]  # type: ignore[attr-defined]


def test_toolbar_layout_keeps_its_spacing_and_side_margins(qtbot) -> None:
    toolbar = PanelToolbar()
    qtbot.addWidget(toolbar)
    layout = toolbar.layout()
    assert layout is not None

    assert layout.contentsMargins().left() == 8
    assert layout.contentsMargins().right() == 8
    assert layout.contentsMargins().top() == layout.contentsMargins().bottom() == 0
    assert layout.spacing() == 6
    assert [layout.itemAt(i).widget() for i in range(4)] == [
        toolbar.undo_button,
        toolbar.redo_button,
        toolbar.shuffle_button,
        toolbar.fullscreen_button,
    ]


def _polygon_points(polygon: object) -> list[tuple[int, int]]:
    return [(polygon.at(i).x(), polygon.at(i).y()) for i in range(polygon.count())]  # type: ignore[attr-defined]


def test_shuffle_icon_draws_shallow_crossing_arrows_with_separated_heads(qtbot) -> None:
    painter = _Painter()
    ShuffleButton()._paint_icon(painter, QRect(10, 20, 40, 30))  # type: ignore[arg-type]

    assert len(painter.paths) == 2
    assert _path_points(painter.paths[0]) == pytest.approx(
        [(10, 44.36), (23.6, 44.36), (23.6, 24.64), (46, 24.64)]
    )
    assert _path_points(painter.paths[1]) == pytest.approx(
        [(10, 24.64), (23.6, 24.64), (23.6, 44.36), (46, 44.36)]
    )
    assert [_polygon_points(polygon) for polygon in painter.polygons] == [
        [(49, 25), (46, 22), (46, 27)],
        [(49, 44), (46, 42), (46, 47)],
    ]


def test_fullscreen_icon_draws_eight_corner_arms_of_the_expected_length(qtbot) -> None:
    painter = _Painter()
    FullScreenButton()._paint_icon(painter, QRect(1, 2, 19, 16))  # type: ignore[arg-type]

    assert painter.lines == [
        (1, 7, 1, 2),
        (1, 2, 6, 2),
        (14, 2, 19, 2),
        (19, 2, 19, 7),
        (1, 12, 1, 17),
        (1, 17, 6, 17),
        (14, 17, 19, 17),
        (19, 17, 19, 12),
    ]


def test_fullscreen_icon_keeps_a_three_pixel_minimum_arm(qtbot) -> None:
    painter = _Painter()
    FullScreenButton()._paint_icon(painter, QRect(0, 3, 6, 6))  # type: ignore[arg-type]

    assert painter.lines == [
        (0, 6, 0, 3),
        (0, 3, 3, 3),
        (2, 3, 5, 3),
        (5, 3, 5, 6),
        (0, 5, 0, 8),
        (0, 8, 3, 8),
        (2, 8, 5, 8),
        (5, 8, 5, 5),
    ]


def test_fullscreen_icon_uses_addition_for_non_aligned_coordinates(qtbot) -> None:
    painter = _Painter()
    FullScreenButton()._paint_icon(painter, QRect(1, 3, 19, 16))  # type: ignore[arg-type]

    assert painter.lines == [
        (1, 8, 1, 3),
        (1, 3, 6, 3),
        (14, 3, 19, 3),
        (19, 3, 19, 8),
        (1, 13, 1, 18),
        (1, 18, 6, 18),
        (14, 18, 19, 18),
        (19, 18, 19, 13),
    ]


def test_shuffle_icon_curve_uses_the_offset_from_its_left_edge(qtbot: QtBot) -> None:
    class _Painter:
        def __init__(self) -> None:
            self.paths = []

        def drawPath(self, path) -> None:
            self.paths.append(path)

        def pen(self):
            class _Pen:
                def color(self):
                    return None

            return _Pen()

        def __getattr__(self, _name: str):
            return lambda *_args, **_kwargs: None

    button = ShuffleButton()
    qtbot.addWidget(button)
    painter = _Painter()

    button._paint_icon(painter, QRect(8, 3, 44, 20))  # noqa: SLF001

    assert painter.paths[0].elementAt(1).x == 23


def test_panel_toolbar_keeps_an_expanding_spacer(qtbot: QtBot) -> None:
    toolbar = PanelToolbar()
    qtbot.addWidget(toolbar)

    assert toolbar.layout().stretch(4) > 0
