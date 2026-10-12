import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage, QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QWidget
from pytestqt.qtbot import QtBot

from prismic.application.input import shortcuts
from prismic.application.input.shortcuts import ShortcutBindings
from prismic.domain.tag import Tag
from prismic.ui.frameless_dialog import MessageDialog
from prismic.ui.hover_explainer_bar import HoverExplainerBar
from prismic.ui.hover_hint import HoverHintController
from prismic.ui.image_view import ImageView
from prismic.ui.keyboard import KeyboardController
from prismic.ui.settings_dialog import KeyCaptureButton, SettingsDialog, ThresholdRow
from prismic.ui.tag_model import (
    CheckedRole,
    TagIdRole,
    TagListModel,
    UncheckedSlotRole,
)
from prismic.ui.tag_panel import TagPanel


def test_hover_hints_only_change_on_enter_and_leave(qtbot: QtBot) -> None:
    bar = HoverExplainerBar()
    dynamic = QWidget()
    static = QWidget()
    qtbot.addWidget(bar)
    qtbot.addWidget(dynamic)
    qtbot.addWidget(static)
    controller = HoverHintController(bar, ShortcutBindings())
    controller.register_widget(dynamic, shortcuts.NAVIGATE_NEXT, "Next item")
    controller.register_static(static, ("Ctrl",), "Undo")

    for widget in (dynamic, static):
        bar.show_hint(("Keep",), "Current hint")
        for event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.Show):
            assert controller.eventFilter(widget, QEvent(event_type)) is False
            assert bar._text_label.text() == "Current hint"
            assert [label.text() for label in bar._key_labels] == ["Keep"]

        controller.eventFilter(widget, QEvent(QEvent.Type.Enter))
        expected = "Next item" if widget is dynamic else "Undo"
        assert bar._text_label.text() == expected

        for event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.Show):
            controller.eventFilter(widget, QEvent(event_type))
            assert bar._text_label.text() == expected

        controller.eventFilter(widget, QEvent(QEvent.Type.Leave))
        assert bar._text_label.text() == ""


def test_hover_hint_controller_ignores_unregistered_widgets(qtbot: QtBot) -> None:
    bar = HoverExplainerBar()
    widget = QWidget()
    qtbot.addWidget(bar)
    qtbot.addWidget(widget)
    controller = HoverHintController(bar, ShortcutBindings())
    bar.show_hint(("Keep",), "Current hint")

    assert controller.eventFilter(widget, QEvent(QEvent.Type.Enter)) is False
    assert bar._text_label.text() == "Current hint"


def test_hover_explainer_gives_its_text_label_the_layout_stretch(qtbot: QtBot) -> None:
    bar = HoverExplainerBar()
    qtbot.addWidget(bar)
    layout = bar.layout()

    assert isinstance(layout, QHBoxLayout)
    assert layout.stretch(1) == 1


def test_double_click_after_manual_zoom_fits_the_image_again(qtbot: QtBot) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(QImage(100, 100, QImage.Format.Format_RGB32))
    view.zoom_in()
    assert view.zoom == 1.25

    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton)

    assert view.zoom == 1.0


def _keyboard_controller() -> tuple[KeyboardController, list[str], list[int]]:
    calls: list[str] = []
    slots: list[int] = []
    controller = KeyboardController(
        ShortcutBindings(),
        on_navigate_previous=lambda: calls.append("previous"),
        on_navigate_next=lambda: calls.append("next"),
        on_history_back=lambda: calls.append("back"),
        on_history_forward=lambda: calls.append("forward"),
        on_undo=lambda: calls.append("undo"),
        on_redo=lambda: calls.append("redo"),
        on_focus_item_tags=lambda: calls.append("focus"),
        on_toggle_tag_shortcut=slots.append,
        on_toggle_focus_mode=lambda: calls.append("focus-mode"),
        on_swap_tag_numbering=lambda: calls.append("swap"),
        on_shuffle_results=lambda: calls.append("shuffle"),
        on_true_fullscreen=lambda: calls.append("fullscreen"),
    )
    return controller, calls, slots


def _key_event(
    key: Qt.Key, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
) -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers)


def test_keyboard_controller_reports_handled_commands_and_unknown_shortcuts() -> None:
    controller, calls, slots = _keyboard_controller()

    assert controller.run("unknown.shortcut") is False
    assert calls == []
    assert controller.run(shortcuts.FOCUS_MODE) is True
    assert calls == ["focus-mode"]

    assert controller.handle_key_press(_key_event(Qt.Key.Key_1), text_editing=False) is True
    assert slots == [0]
    assert controller.handle_key_press(_key_event(Qt.Key.Key_Up), text_editing=True) is True
    assert calls[-1] == "previous"
    assert (
        controller.handle_key_press(
            _key_event(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier), text_editing=False
        )
        is True
    )
    assert calls[-1] == "undo"
    assert (
        controller.handle_key_press(
            _key_event(Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier), text_editing=False
        )
        is True
    )
    assert calls[-1] == "redo"
    assert controller.handle_key_press(_key_event(Qt.Key.Key_F12), text_editing=False) is False


def test_key_capture_button_does_not_capture_when_not_armed(qtbot: QtBot) -> None:
    button = KeyCaptureButton()
    qtbot.addWidget(button)
    button.set_binding("Ctrl+O")
    captured: list[str] = []
    button.binding_captured.connect(captured.append)

    button.event(_key_event(Qt.Key.Key_F5))

    assert captured == []
    assert button.is_capturing is False
    assert button.text() == "Ctrl + O"


def test_key_capture_consumes_the_binding_key(qtbot: QtBot) -> None:
    button = KeyCaptureButton()
    qtbot.addWidget(button)
    button.setChecked(True)
    captured: list[str] = []
    button.binding_captured.connect(captured.append)
    event = _key_event(Qt.Key.Key_F5)

    assert button.event(event) is True
    assert captured == ["F5"]
    assert button.is_capturing is False


def test_settings_widget_constructors_accept_their_keyword_parameters(qtbot: QtBot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)

    button = KeyCaptureButton(parent=parent, held=True)
    row = ThresholdRow(
        label="Threshold", description="Description", default_fraction=0.5, parent=parent
    )
    dialog = SettingsDialog(ShortcutBindings(), parent=parent)

    assert button.parentWidget() is parent
    assert row.parentWidget() is parent
    assert dialog.parentWidget() is parent


def test_conflict_confirmation_does_not_accept_a_dismissed_dialog(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindings = ShortcutBindings()
    dialog = SettingsDialog(bindings)
    qtbot.addWidget(dialog)
    row = next(
        row
        for row in dialog.shortcuts_panel.rows
        if row.definition.id == shortcuts.OPEN_COLLECTION_FOLDER
    )
    monkeypatch.setattr(
        MessageDialog,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.NoButton,
    )

    assert row._confirm_conflicts("Ctrl+T") is False
    assert bindings.binding(shortcuts.TOGGLE_THUMBNAILS) == "Ctrl+T"


def test_restore_defaults_does_not_accept_a_dismissed_dialog(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindings = ShortcutBindings()
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "F5")
    dialog = SettingsDialog(bindings)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        MessageDialog,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.NoButton,
    )

    dialog.shortcuts_panel._restore_defaults()

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "F5"


def test_tag_model_returns_none_for_unassigned_roles() -> None:
    model = TagListModel()
    model.set_tags([Tag(id=5, name="checked")], frozenset({5}))
    index = model.index(0, 0)

    assert index.data(TagIdRole) == 5
    assert index.data(CheckedRole) is True
    assert index.data(UncheckedSlotRole) is None
    assert model.data(index, Qt.ItemDataRole.UserRole) is None
    assert model.data(index, Qt.ItemDataRole.UserRole + 5) is None


def test_tag_model_lookups_require_exact_ids_and_nonnegative_slots() -> None:
    model = TagListModel()
    model.set_tags(
        [Tag(id=20, name="first"), Tag(id=5, name="selected"), Tag(id=15, name="last")],
        frozenset({5}),
    )

    assert model.row_for_tag_id(5) == 1
    assert model.tag_id_for_slot(0, selected=False) == 20
    assert model.tag_id_for_slot(0, selected=True) == 5
    assert model.tag_id_for_slot(-1, selected=False) is None
    assert model.tag_id_for_slot(-1, selected=True) is None


def test_tag_panel_tracks_viewport_mouse_and_keeps_parent_keyword_usable(qtbot: QtBot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    panel = TagPanel("Item tags", parent=parent, show_shortcuts=True)

    assert panel.parentWidget() is parent
    assert panel.list_view.viewport().hasMouseTracking()
