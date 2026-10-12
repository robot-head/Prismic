from PySide6.QtCore import QEvent, QMargins
from PySide6.QtWidgets import QHBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from prismic.application.input import shortcuts
from prismic.application.input.shortcuts import ShortcutBindings
from prismic.ui.hover_explainer_bar import HoverExplainerBar
from prismic.ui.hover_hint import HoverHintController
from prismic.ui.transient_message_bar import TransientMessageBar


def test_hover_hints_show_on_enter_and_clear_on_leave(qtbot: QtBot) -> None:
    bar = HoverExplainerBar()
    widget = TransientMessageBar()
    qtbot.addWidget(bar)
    qtbot.addWidget(widget)
    controller = HoverHintController(bar, shortcuts.ShortcutBindings())
    controller.register_widget(widget, shortcuts.NAVIGATE_NEXT, "Next item")

    controller.eventFilter(widget, QEvent(QEvent.Type.Enter))
    assert bar._text_label.text() == "Next item"

    controller.eventFilter(widget, QEvent(QEvent.Type.Leave))
    assert bar._text_label.text() == ""


def test_hover_explainer_keeps_keycap_and_message_layout_metrics(qtbot: QtBot) -> None:
    bar = HoverExplainerBar()
    qtbot.addWidget(bar)

    assert bar._keys_layout.contentsMargins() == QMargins(0, 0, 0, 0)
    assert bar._keys_layout.spacing() == 4
    assert bar.layout().contentsMargins() == QMargins(6, 0, 6, 0)
    assert bar.layout().spacing() == 8


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
