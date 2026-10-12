from pathlib import Path

from PySide6.QtCore import QEvent, QMargins, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from pytestqt.qtbot import QtBot

from prismic.application.input import shortcuts
from prismic.domain.tag import Tag
from prismic.media import loader as loader_module
from prismic.media.loader import ImageLoader
from prismic.ui import viewer as viewer_module
from prismic.ui.column_splitter import ColumnSplitter
from prismic.ui.hover_explainer_bar import HoverExplainerBar
from prismic.ui.hover_hint import HoverHintController
from prismic.ui.image_view import ImageView
from prismic.ui.instance_bridge import InstanceBridge
from prismic.ui.keyboard import KeyboardController, literal_character
from prismic.ui.result_model import MediaIdRole, ResultListModel
from prismic.ui.tag_panel import TagPanel
from prismic.ui.transient_message_bar import TransientMessageBar
from prismic.ui.viewer import MediaViewer
from tests.gui._media_helpers import make_media
from tests.gui._mutation_helpers import assert_raise_not_requested, wheel_event

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "media"


def test_literal_character_only_accepts_single_character_bindings() -> None:
    assert literal_character("Q") == "q"
    assert literal_character("1") == "1"
    assert literal_character("Left") is None
    assert literal_character("") is None


def test_bare_modifier_key_event_is_not_consumed(qtbot: QtBot) -> None:
    bindings = shortcuts.ShortcutBindings()
    controller = KeyboardController(
        bindings,
        on_navigate_previous=lambda: None,
        on_navigate_next=lambda: None,
        on_history_back=lambda: None,
        on_history_forward=lambda: None,
        on_undo=lambda: None,
        on_redo=lambda: None,
        on_focus_item_tags=lambda: None,
        on_toggle_tag_shortcut=lambda _slot: None,
        on_toggle_focus_mode=lambda: None,
        on_swap_tag_numbering=lambda: None,
        on_shuffle_results=lambda: None,
        on_true_fullscreen=lambda: None,
    )
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Control,
        Qt.KeyboardModifier.NoModifier,
    )

    assert controller.handle_key_press(event, text_editing=False) is False


def test_tag_panel_reports_hovered_row_from_viewport_event(qtbot: QtBot) -> None:
    panel = TagPanel("Item tags")
    qtbot.addWidget(panel)
    panel.resize(260, 180)
    panel.set_tags([Tag(id=11, name="vacation")], frozenset())
    assert panel._delegate._show_shortcuts is False
    panel.show()
    qtbot.waitExposed(panel)
    row_rect = panel.list_view.visualRect(panel.model.index(0, 0))
    assert row_rect.isValid()
    rows: list[int | None] = []
    panel.hover_row_changed.connect(rows.append)
    position = QPointF(row_rect.center())
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        position,
        position,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )

    panel.eventFilter(panel.list_view.viewport(), event)

    assert rows == [0]


def test_tag_panel_keeps_header_spacing_and_stretches_the_tag_list(qtbot: QtBot) -> None:
    panel = TagPanel("Item tags")
    qtbot.addWidget(panel)

    assert panel.header.layout().contentsMargins() == QMargins(0, 0, 0, 0)
    assert panel.header.layout().spacing() == 0
    assert panel.layout().contentsMargins() == QMargins(0, 0, 0, 0)
    assert panel.layout().spacing() == 0
    assert panel.layout().stretch(1) == 1


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


def test_exact_single_wheel_delta_zooms_in(qtbot: QtBot) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(QImage(100, 100, QImage.Format.Format_RGB32))
    before = view.zoom
    event = wheel_event(1)

    view.wheelEvent(event)

    assert view.zoom > before


def test_movie_frames_update_the_pixmap_and_late_frames_without_a_movie_are_ignored(
    qtbot: QtBot,
) -> None:
    view = ImageView()
    qtbot.addWidget(view)
    view.set_image(QImage(10, 10, QImage.Format.Format_RGB32))

    # A queued frameChanged signal may arrive just after clear/stop removed
    # the movie; it must be ignored while the still-image pixmap remains.
    view._on_movie_frame()

    class _Movie:
        def __init__(self) -> None:
            self.pixmap = QPixmap(10, 10)
            self.pixmap.fill(QColor("#e02020"))

        def currentPixmap(self) -> QPixmap:
            return self.pixmap

    movie = _Movie()
    view._movie = movie
    view._on_movie_frame()

    assert view._pixmap_item is not None
    assert view._pixmap_item.pixmap().toImage().pixelColor(0, 0) == QColor("#e02020")


def test_default_image_loader_keeps_a_2048_pixel_image_at_full_size(
    qtbot: QtBot, monkeypatch
) -> None:
    raw = QImage(2048, 32, QImage.Format.Format_RGB32)
    monkeypatch.setattr(loader_module, "load_image", lambda _path: raw)
    loader = ImageLoader()
    request_id = loader.begin_request()

    result = loader.load(request_id, Path("large.png"))

    assert result is not None
    assert result.image is not None
    assert result.image.width() == 2048


def test_video_controls_are_visible_for_video_and_hidden_after_clear(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)
    assert viewer._controls.isHidden()
    assert (viewer._seek_slider.minimum(), viewer._seek_slider.maximum()) == (0, 0)

    viewer.show_media(FIXTURES_DIR / "supported_video.webm")
    assert viewer._controls.isHidden() is False

    viewer.clear()
    assert viewer._controls.isHidden() is True


def test_invalid_animation_is_declined_for_still_image_fallback(qtbot: QtBot, monkeypatch) -> None:
    class _Reader:
        def supportsAnimation(self) -> bool:
            return True

        def imageCount(self) -> int:
            return 2

    class _Movie:
        def isValid(self) -> bool:
            return False

    monkeypatch.setattr(viewer_module, "QImageReader", lambda _path: _Reader())
    monkeypatch.setattr(viewer_module, "QMovie", lambda _path: _Movie())
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    assert viewer._try_show_animation(Path("broken.gif")) is False


def test_video_position_updates_pause_while_the_slider_is_dragged(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)
    slider = viewer._seek_slider
    slider.setRange(0, 100)
    slider.setValue(20)

    viewer._on_position_changed(40)
    assert slider.value() == 40

    slider.setSliderDown(True)
    viewer._on_position_changed(60)
    assert slider.value() == 40


def test_video_duration_keeps_the_seek_slider_minimum_at_zero(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    viewer._on_duration_changed(120)

    assert (viewer._seek_slider.minimum(), viewer._seek_slider.maximum()) == (0, 120)


def test_playback_state_sets_the_matching_button_label(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    viewer._on_playback_state_changed(QMediaPlayer.PlaybackState.PlayingState)
    assert viewer.play_pause_button.text() == "Pause"

    viewer._on_playback_state_changed(QMediaPlayer.PlaybackState.PausedState)
    assert viewer.play_pause_button.text() == "Play"


def test_column_splitter_draws_a_one_pixel_line_centered_in_both_orientations(
    qtbot: QtBot,
) -> None:
    for orientation, expected_rect in (
        (Qt.Orientation.Horizontal, (4, 0, 1, 40)),
        (Qt.Orientation.Vertical, (0, 19, 10, 1)),
    ):
        splitter = ColumnSplitter(orientation)
        qtbot.addWidget(splitter)
        handle = splitter.createHandle()
        handle.resize(10, 40)

        rect = handle._line_rect()

        assert (rect.x(), rect.y(), rect.width(), rect.height()) == expected_rect


def test_result_model_exposes_media_id_role_and_rejects_out_of_range_indices(
    qtbot: QtBot,
) -> None:
    assert int(MediaIdRole) == int(Qt.ItemDataRole.UserRole) + 1
    model = ResultListModel()
    model.set_media([make_media(media_id=29)])

    assert model.data(model.index(0, 0), MediaIdRole) == 29
    assert model.data(model.index(5, 0)) is None


def test_transient_message_without_timeout_stays_visible(qtbot: QtBot) -> None:
    bar = TransientMessageBar()
    qtbot.addWidget(bar)

    bar.show_message("Collection is already open")
    qtbot.wait(20)

    assert bar.text() == "Collection is already open"


def test_instance_bridge_ignores_raise_messages_with_trailing_bytes() -> None:
    bridge = InstanceBridge()
    assert_raise_not_requested(bridge, b"raise-extra")


def test_instance_bridge_release_closes_its_listening_server(tmp_path: Path) -> None:
    bridge = InstanceBridge()
    bridge.take_ownership(tmp_path / "collection.prismic")
    server = bridge._server
    assert server is not None and server.isListening()

    try:
        bridge.release()

        assert bridge._server is None
        assert server.isListening() is False
    finally:
        if server.isListening():
            server.close()
