"""Regression checks for UI behavior exposed by the Cosmic Ray sweep."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import QMessageBox, QWidget
from pytestqt.qtbot import QtBot

from prismic.application.input import shortcuts
from prismic.application.input.shortcuts import ShortcutBindings
from prismic.persistence.preferences import PreferencesStore
from prismic.ui.frameless_dialog import FramelessDialog, MessageDialog, TitleBar
from prismic.ui.main_window import MainWindow
from prismic.ui.settings_dialog import KeyCaptureButton, ShortcutsPanel, ThresholdRow
from tests.gui.helpers import open_and_wait


def test_parented_message_dialog_centers_over_parent_before_showing(qtbot: QtBot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(420, 260)
    parent.move(100, 120)
    parent.show()
    qtbot.waitExposed(parent)

    dialog = MessageDialog(
        parent,
        "Title",
        "Text",
        QMessageBox.StandardButton.Ok,
        QMessageBox.StandardButton.Ok,
    )
    qtbot.addWidget(dialog)

    assert dialog.frameGeometry().center() == parent.frameGeometry().center()


def test_parented_message_dialog_clamps_its_frame_to_the_screen(qtbot: QtBot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(320, 220)
    parent.show()
    qtbot.waitExposed(parent)
    available = parent.screen().availableGeometry()
    parent.move(available.right() - 20, available.bottom() - 20)

    dialog = MessageDialog(
        parent,
        "Title",
        "Text",
        QMessageBox.StandardButton.Ok,
        QMessageBox.StandardButton.Ok,
    )
    qtbot.addWidget(dialog)

    frame = dialog.frameGeometry()
    assert available.contains(frame)
    assert frame.right() == available.right() - 1
    assert frame.bottom() == available.bottom() - 1


def test_resizable_frameless_dialog_keeps_its_grip_inside_the_lower_right_corner(
    qtbot: QtBot,
) -> None:
    dialog = FramelessDialog("Resizable", resizable=True)
    qtbot.addWidget(dialog)
    dialog.resize(320, 240)
    dialog.show()
    qtbot.waitExposed(dialog)

    grip = dialog._size_grip  # noqa: SLF001
    assert grip is not None
    assert grip.size() == QSize(16, 16)
    assert grip.pos() == QPoint(
        dialog.width() - grip.width() - 1, dialog.height() - grip.height() - 1
    )

    dialog.resize(500, 360)
    qtbot.waitUntil(
        lambda: (
            grip.pos()
            == QPoint(dialog.width() - grip.width() - 1, dialog.height() - grip.height() - 1)
        )
    )


def test_title_bar_starts_a_system_move_only_for_a_left_press(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    title_bar = TitleBar("Title")
    qtbot.addWidget(title_bar)
    title_bar.show()

    class MoveHandle:
        calls = 0

        def startSystemMove(self) -> bool:
            self.calls += 1
            return True

    handle = MoveHandle()

    class WindowStub:
        def windowHandle(self) -> MoveHandle:
            return handle

    monkeypatch.setattr(title_bar, "window", lambda: WindowStub())
    left_press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(1, 1),
        QPointF(1, 1),
        QPointF(1, 1),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    title_bar.mousePressEvent(left_press)
    assert left_press.isAccepted()
    assert handle.calls == 1

    right_press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(1, 1),
        QPointF(1, 1),
        QPointF(1, 1),
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    right_press.ignore()
    title_bar.mousePressEvent(right_press)

    assert handle.calls == 1
    assert not right_press.isAccepted()


def test_size_grip_draws_the_three_diagonals_in_its_lower_right_corner(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = FramelessDialog("Resizable", resizable=True)
    qtbot.addWidget(dialog)
    grip = dialog._size_grip  # noqa: SLF001
    assert grip is not None
    lines: list[tuple[int, int, int, int]] = []

    class RecordingPainter:
        RenderHint = QPainter.RenderHint

        def __init__(self, _widget: QWidget) -> None:
            pass

        def setRenderHint(self, *_args: object) -> None:
            pass

        def setPen(self, *_args: object) -> None:
            pass

        def drawLine(self, x1: int, y1: int, x2: int, y2: int) -> None:
            lines.append((x1, y1, x2, y2))

    monkeypatch.setattr("prismic.ui.frameless_dialog.QPainter", RecordingPainter)
    grip.paintEvent(None)  # type: ignore[arg-type]

    assert lines == [(14, 13, 13, 14), (14, 9, 9, 14), (14, 5, 5, 14)]


def test_starting_shortcut_capture_grabs_and_then_releases_the_keyboard(qtbot: QtBot) -> None:
    button = KeyCaptureButton()
    qtbot.addWidget(button)
    button.show()

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert button.is_capturing
    assert QWidget.keyboardGrabber() is button

    qtbot.keyClick(button, Qt.Key.Key_F7)

    assert not button.is_capturing
    assert QWidget.keyboardGrabber() is not button


def test_search_with_no_matches_hides_categories_and_shows_the_empty_state(
    qtbot: QtBot, tmp_path
) -> None:
    bindings = ShortcutBindings(PreferencesStore(tmp_path / "preferences.json"))
    panel = ShortcutsPanel(bindings)
    qtbot.addWidget(panel)

    panel.search_box.setText("no shortcut has this phrase")

    assert panel.visible_rows() == []
    assert panel._empty_label.isVisibleTo(panel)  # noqa: SLF001
    assert all(not header.isVisibleTo(panel) for header in panel._headers.values())  # noqa: SLF001


def test_assigning_the_existing_binding_does_not_report_a_change(qtbot: QtBot, tmp_path) -> None:
    bindings = ShortcutBindings(PreferencesStore(tmp_path / "preferences.json"))
    panel = ShortcutsPanel(bindings)
    qtbot.addWidget(panel)
    row = next(row for row in panel.rows if row.definition.id == shortcuts.OPEN_COLLECTION_FOLDER)
    current = bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER)
    same_value = (" " + current)[1:]
    assert same_value == current and same_value is not current
    changed: list[None] = []
    row.changed.connect(lambda: changed.append(None))

    row._assign(same_value)  # noqa: SLF001

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == current
    assert changed == []


def test_clearing_a_threshold_field_restores_its_current_value(qtbot: QtBot) -> None:
    row = ThresholdRow("Threshold", "Description", default_fraction=0.5)
    qtbot.addWidget(row)
    row.set_fraction(0.63)
    changed: list[None] = []
    row.changed.connect(lambda: changed.append(None))
    row._editor.clear()  # noqa: SLF001

    row._commit()  # noqa: SLF001

    assert row.fraction == 0.63
    assert row._editor.text() == "63"  # noqa: SLF001
    assert changed == []


@pytest.mark.parametrize(
    ("current_index", "direction", "neighbor_indexes"),
    [(0, 1, [1, 2]), (2, -1, [1, 0])],
    ids=["forward-from-first", "backward-from-last"],
)
def test_thumbnail_preloading_follows_direction_and_stays_within_display_order(
    qtbot: QtBot,
    window: MainWindow,
    collection_dir,
    monkeypatch: pytest.MonkeyPatch,
    current_index: int,
    direction: int,
    neighbor_indexes: list[int],
) -> None:
    (collection_dir / "c.png").write_bytes((collection_dir / "a.png").read_bytes())
    open_and_wait(qtbot, window, collection_dir, expected_count=3)
    session = window.session
    assert session is not None
    display_order = list(session.state.result_set)
    media_paths = {
        media.id: session.collection.root / media.relative_path
        for media in session.media.list_all()
    }
    requested = []
    monkeypatch.setattr(window.viewer, "preload", requested.append)
    window._display_order = display_order  # noqa: SLF001
    window._nav_direction = direction  # noqa: SLF001

    window._preload_neighbors(display_order[current_index])  # noqa: SLF001

    assert requested == [media_paths[display_order[index]] for index in neighbor_indexes]


def test_multi_selection_grid_keeps_display_order_and_skips_unselected_items(
    qtbot: QtBot, window: MainWindow, collection_dir
) -> None:
    (collection_dir / "c.png").write_bytes((collection_dir / "a.png").read_bytes())
    open_and_wait(qtbot, window, collection_dir, expected_count=3)
    session = window.session
    assert session is not None
    first, _middle, last = session.state.result_set
    session.state.current_item = first
    session.state.selected_items = frozenset({first, last})

    window._refresh_all()  # noqa: SLF001

    expected = [
        (media_id, session.collection.root / session.media.get(media_id).relative_path)
        for media_id in (first, last)
    ]
    assert window.selection_grid._items == expected  # noqa: SLF001
