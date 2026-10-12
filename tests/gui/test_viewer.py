from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCore import QObject
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer
from pytestqt.qtbot import QtBot

from prismic.media import loader as loader_module
from prismic.media.loader import ImageLoader
from prismic.ui import viewer as viewer_module
from prismic.ui.viewer import MediaViewer
from tests.gui._media_helpers import solid_image
from tests.gui._viewer_helpers import assert_viewer_empty, show_media

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "media"


def _show_gif(qtbot: QtBot, path: Path, frame_count: int) -> MediaViewer:
    _gif(path, frame_count)
    return show_media(qtbot, path)


def test_shows_image_for_a_supported_image_path(qtbot: QtBot) -> None:
    viewer = show_media(qtbot, FIXTURES_DIR / "supported_image.png")

    assert viewer.is_showing_image is True
    assert viewer.is_showing_video is False


def test_shows_video_for_a_webm_path(qtbot: QtBot) -> None:
    viewer = show_media(qtbot, FIXTURES_DIR / "supported_video.webm")

    assert viewer.is_showing_video is True
    assert viewer.is_showing_image is False


def test_corrupt_image_emits_load_error_and_shows_nothing(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    with qtbot.waitSignal(viewer.load_error, timeout=2000):
        viewer.show_media(FIXTURES_DIR / "corrupt_image.jpg")

    assert_viewer_empty(viewer)


def test_toggle_playback_starts_and_pauses_video(qtbot: QtBot) -> None:
    viewer = show_media(qtbot, FIXTURES_DIR / "supported_video.webm")
    qtbot.waitUntil(lambda: viewer.video_player.duration_ms > 0, timeout=5000)

    viewer.toggle_playback()
    qtbot.waitUntil(
        lambda: viewer.video_player.playback_state == QMediaPlayer.PlaybackState.PlayingState,
        timeout=5000,
    )

    viewer.toggle_playback()
    qtbot.waitUntil(
        lambda: viewer.video_player.playback_state != QMediaPlayer.PlaybackState.PlayingState,
        timeout=5000,
    )


def test_clear_resets_to_the_empty_state(qtbot: QtBot) -> None:
    viewer = show_media(qtbot, FIXTURES_DIR / "supported_image.png")

    viewer.clear()

    assert_viewer_empty(viewer)
    assert viewer.current_path is None


def _gif(path: Path, frame_count: int) -> None:
    """A hand-assembled 1x1 GIF of `frame_count` frames (Qt can read
    animated GIFs but not write them, and there's no imaging library in
    the dev deps). Built from hex so every byte is spelled out."""
    header = bytes.fromhex("47494638396101000100800000000000ffffff")
    loop = bytes.fromhex("21ff0b" + b"NETSCAPE2.0".hex() + "0301000000")
    frame = bytes.fromhex(
        "21f904"
        "00"
        "0500"
        "00"
        "00"  # graphic control: 50ms delay
        "2c"
        "0000"
        "0000"
        "0100"
        "0100"
        "00"  # image descriptor: 1x1
        "02"
        "02"
        "4401"
        "00"  # LZW data: one pixel
    )
    path.write_bytes(header + loop + frame * frame_count + b";")


def test_animated_gif_plays_in_the_image_view(qtbot: QtBot, tmp_path: Path) -> None:
    gif = tmp_path / "anim.gif"
    viewer = _show_gif(qtbot, gif, 3)

    assert viewer.is_showing_image is True
    assert viewer.image_view.is_animating is True
    viewer.clear()
    assert viewer.image_view.is_animating is False


def test_single_frame_gif_is_not_treated_as_an_animation(qtbot: QtBot, tmp_path: Path) -> None:
    gif = tmp_path / "still.gif"
    viewer = _show_gif(qtbot, gif, 1)

    assert viewer.image_view.is_animating is False


def test_video_loops_forever(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    assert viewer.video_player.qt_player.loops() == QMediaPlayer.Loops.Infinite


def test_suppressing_controls_collapses_them_and_restores(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)
    viewer.show()
    viewer.show_media(FIXTURES_DIR / "supported_video.webm")

    viewer.set_controls_suppressed(True)
    assert viewer._controls.maximumHeight() == 0
    viewer.set_controls_suppressed(False)
    assert viewer._controls.maximumHeight() > 0


def test_play_pause_is_a_global_mode_across_videos(qtbot: QtBot) -> None:
    video = FIXTURES_DIR / "supported_video.webm"
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    def is_playing() -> bool:
        return viewer.video_player.playback_state == QMediaPlayer.PlaybackState.PlayingState

    viewer.show_media(video)
    assert viewer.autoplay is False
    assert not is_playing()

    viewer.toggle_playback()
    viewer.show_media(FIXTURES_DIR / "audio_video.webm")
    qtbot.waitUntil(is_playing, timeout=5000)

    viewer.toggle_playback()
    assert viewer.autoplay is False
    viewer.show_media(video)
    qtbot.wait(300)
    assert not is_playing()


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


@pytest.mark.parametrize(
    ("playback_state", "expected_label"),
    [
        (QMediaPlayer.PlaybackState.PlayingState, "Pause"),
        (QMediaPlayer.PlaybackState.PausedState, "Play"),
    ],
    ids=["playing", "paused"],
)
def test_playback_state_sets_the_matching_button_label(
    qtbot: QtBot,
    playback_state: QMediaPlayer.PlaybackState,
    expected_label: str,
) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    viewer._on_playback_state_changed(playback_state)

    assert viewer.play_pause_button.text() == expected_label


def test_viewer_layouts_have_no_margins_or_spacing(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)
    outer_layout = viewer.layout()
    controls_layout = viewer._controls.layout()
    assert outer_layout is not None
    assert controls_layout is not None

    assert outer_layout.getContentsMargins() == (0, 0, 0, 0)
    assert outer_layout.spacing() == 0
    assert controls_layout.getContentsMargins() == (0, 0, 0, 0)


def _show_image(qtbot: QtBot, monkeypatch, image: QImage, path: Path) -> MediaViewer:
    monkeypatch.setattr(viewer_module, "load_image", lambda _path: image)
    return show_media(qtbot, path)


def test_showing_a_still_image_keeps_video_controls_hidden(qtbot: QtBot, monkeypatch) -> None:
    image = solid_image(3, 2)
    viewer = _show_image(qtbot, monkeypatch, image, Path("photo.png"))
    assert viewer.is_showing_image
    assert viewer._controls.isHidden()


class _Reader:
    def __init__(self, _path: str, frame_count: int) -> None:
        self._frame_count = frame_count

    def supportsAnimation(self) -> bool:
        return True

    def imageCount(self) -> int:
        return self._frame_count


def test_single_frame_gif_falls_back_to_a_still_image(qtbot: QtBot, monkeypatch) -> None:
    image = solid_image(2, 2)
    monkeypatch.setattr(
        viewer_module,
        "QImageReader",
        lambda path: _Reader(path, 1),
    )
    viewer = _show_image(qtbot, monkeypatch, image, Path("still.gif"))
    assert viewer.is_showing_image
    assert not viewer.image_view.is_animating


class _Signal:
    def connect(self, _callback: Callable[..., object]) -> None:
        pass


class _Movie:
    def __init__(self, _path: str) -> None:
        self.frameChanged = _Signal()
        self.jump_targets: list[int] = []

    def isValid(self) -> bool:
        return True

    def jumpToFrame(self, frame: int) -> None:
        self.jump_targets.append(frame)

    def currentImage(self) -> QImage:
        return QImage(2, 2, QImage.Format.Format_RGB32)

    def setParent(self, _parent: QObject) -> None:
        pass

    def start(self) -> None:
        pass


def test_animated_gif_starts_on_its_first_frame(qtbot: QtBot, monkeypatch) -> None:
    movies: list[_Movie] = []

    def make_movie(path: str) -> _Movie:
        movie = _Movie(path)
        movies.append(movie)
        return movie

    monkeypatch.setattr(
        viewer_module,
        "QImageReader",
        lambda path: _Reader(path, 2),
    )
    monkeypatch.setattr(viewer_module, "QMovie", make_movie)
    viewer = MediaViewer()
    qtbot.addWidget(viewer)
    assert viewer._try_show_animation(Path("animated.gif"))
    assert len(movies) == 1
    assert movies[0].jump_targets == [0]


def test_completed_image_watcher_is_removed_even_when_its_result_is_stale(
    qtbot: QtBot,
) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)
    watcher = object()
    viewer._watchers.append(watcher)  # type: ignore[arg-type]

    viewer._on_image_loaded(watcher, None)  # type: ignore[arg-type]

    assert viewer._watchers == []
