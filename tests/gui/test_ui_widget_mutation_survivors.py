"""Behavior checks for UI widget/model mutants that survived the main suite."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyleOptionViewItem
from pytestqt.qtbot import QtBot

from prismic.domain.tag import Tag
from prismic.ui.instance_bridge import InstanceBridge
from prismic.ui.panel_toolbar import PanelToolbar, ShuffleButton
from prismic.ui.result_model import MediaIdRole, ResultListModel
from prismic.ui.tag_model import TagIdRole, TagListModel
from prismic.ui.tag_row_delegate import TagRowDelegate
from prismic.ui.transient_message_bar import TransientMessageBar
from tests.gui._media_helpers import make_media
from tests.gui._mutation_helpers import (
    RecordingCalls,
    RecordingPainter,
    assert_raise_not_requested,
    left_mouse_release_at,
)
from tests.gui._progress_test_helpers import report_progress
from tests.gui.helpers import make_scan_progress_bar


def _tag_delegate(qtbot: QtBot) -> tuple[QListView, TagListModel, TagRowDelegate]:
    view = QListView()
    qtbot.addWidget(view)
    model = TagListModel()
    model.set_tags([Tag(id=7, name="kittens")], frozenset())
    view.setModel(model)
    delegate = TagRowDelegate(view, view)
    view.setItemDelegate(delegate)
    return view, model, delegate


def test_result_model_returns_none_for_unknown_roles_and_far_past_end_rows() -> None:
    model = ResultListModel()
    model.set_media([make_media()])

    class ValidIndex:
        def isValid(self) -> bool:
            return True

        def row(self) -> int:
            return model.rowCount() + 1

    assert model.data(model.index(0, 0), -1) is None
    assert model.data(ValidIndex()) is None  # type: ignore[arg-type]
    assert model.data(model.index(0, 0), MediaIdRole + 1) is None


def test_scan_progress_bar_starts_in_later_scan_mode_and_clamps_its_range(qtbot: QtBot) -> None:
    bar = make_scan_progress_bar(qtbot)

    assert bar.format() == "Detecting any moved files"
    assert bar.isTextVisible()
    assert (bar.minimumWidth(), bar.maximumWidth()) == (300, 300)
    assert (bar.minimum(), bar.maximum(), bar.value()) == (0, 0, 0)

    report_progress(qtbot, bar)

    assert (bar.minimum(), bar.maximum()) == (0, 3)


def test_message_timer_is_inactive_after_clearing_a_transient_message(qtbot: QtBot) -> None:
    bar = TransientMessageBar()
    qtbot.addWidget(bar)

    bar.show_message("Temporary notice", timeout_ms=20)
    qtbot.waitUntil(lambda: bar.text() == "", timeout=1000)

    assert not bar._timer.isActive()  # noqa: SLF001 - verify one-shot timer behavior


def test_instance_bridge_rejects_a_raise_message_that_is_only_a_prefix() -> None:
    bridge = InstanceBridge()
    assert_raise_not_requested(bridge, b"rai")


def test_tag_row_editor_is_prefilled_and_blank_renames_are_ignored(qtbot: QtBot) -> None:
    view, model, delegate = _tag_delegate(qtbot)
    index = model.index(0, 0)
    editor = delegate.createEditor(view, QStyleOptionViewItem(), index)
    renamed: list[tuple[int, str]] = []
    delegate.rename_committed.connect(lambda tag_id, name: renamed.append((tag_id, name)))

    delegate.setEditorData(editor, index)
    assert editor.text() == "kittens"

    editor.setText("   ")
    delegate.setModelData(editor, model, index)

    assert renamed == []
    assert model.data(index) == "kittens"


def test_tag_row_escape_reverts_the_inline_editor(qtbot: QtBot) -> None:
    view, model, delegate = _tag_delegate(qtbot)
    editor = delegate.createEditor(view, QStyleOptionViewItem(), model.index(0, 0))
    closed: list[tuple[object, ...]] = []
    delegate.closeEditor.connect(lambda *args: closed.append(args))
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)

    assert delegate.eventFilter(editor, event) is True
    assert closed == [(editor, QStyledItemDelegate.EndEditHint.RevertModelCache)]


def test_tag_row_editor_ignores_a_rename_for_an_invalid_tag_id(qtbot: QtBot) -> None:
    view, model, delegate = _tag_delegate(qtbot)
    editor = delegate.createEditor(view, QStyleOptionViewItem(), model.index(0, 0))
    editor.setText("new name")

    class InvalidIdIndex:
        def data(self, role: int) -> object:
            return "invalid" if role == TagIdRole else None

    renamed: list[tuple[int, str]] = []
    delegate.rename_committed.connect(lambda tag_id, name: renamed.append((tag_id, name)))

    delegate.setModelData(editor, model, InvalidIdIndex())  # type: ignore[arg-type]

    assert renamed == []


def test_tag_row_delegate_consumes_a_delete_click(qtbot: QtBot) -> None:
    _view, model, delegate = _tag_delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 240, 32)
    delete_rect = delegate._rects(option.rect)[2]  # noqa: SLF001 - target the delete affordance
    position = QPointF(delete_rect.center())
    event = left_mouse_release_at(position)
    deleted: list[int] = []
    delegate.delete_requested.connect(deleted.append)

    consumed = delegate.editorEvent(event, model, option, model.index(0, 0))
    qtbot.waitUntil(lambda: deleted == [7], timeout=1000)

    assert consumed is True


def test_tag_row_paint_uses_expected_delete_icon_geometry(qtbot: QtBot) -> None:
    _view, _model, delegate = _tag_delegate(qtbot)
    painter = RecordingCalls()

    delegate._paint_icon(painter, QRect(1, 1, 18, 18), "delete")  # noqa: SLF001

    assert painter.calls_for("drawLine") == [
        (4, 5, 14, 5),
        (8, 8, 8, 12),
        (10, 8, 10, 12),
    ]
    assert painter.calls_for("drawRect") == [(6, 5, 6, 1)]
    assert painter.calls_for("drawRoundedRect") == [(5, 6, 8, 8, 1, 1)]


def test_tag_row_paint_preserves_border_strokes_and_text_width(qtbot: QtBot) -> None:
    _view, model, delegate = _tag_delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 241, 32)
    painter = RecordingPainter()

    delegate.paint(painter, option, model.index(0, 0))

    checkbox_path = painter.calls_for("drawPath")[0][0]
    assert checkbox_path.elementAt(0).y == 12
    assert checkbox_path.contains(QPointF(10, 9))
    assert painter.calls_for("setPen")[0][0].widthF() == 1.5
    assert painter.metrics.widths == [202]

    delete_painter = RecordingCalls()
    delegate._paint_icon(delete_painter, QRect(1, 1, 18, 18), "delete")  # noqa: SLF001
    assert delete_painter.calls_for("setPen")[0][0].widthF() == 1.6


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
