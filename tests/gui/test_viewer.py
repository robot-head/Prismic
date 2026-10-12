from pathlib import Path

from PySide6.QtMultimedia import QMediaPlayer
from pytestqt.qtbot import QtBot

from prismic.ui.viewer import MediaViewer

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "media"


def test_shows_image_for_a_supported_image_path(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    viewer.show_media(FIXTURES_DIR / "supported_image.png")

    assert viewer.is_showing_image is True
    assert viewer.is_showing_video is False


def test_shows_video_for_a_webm_path(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    viewer.show_media(FIXTURES_DIR / "supported_video.webm")

    assert viewer.is_showing_video is True
    assert viewer.is_showing_image is False


def test_corrupt_image_emits_load_error_and_shows_nothing(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    with qtbot.waitSignal(viewer.load_error, timeout=2000):
        viewer.show_media(FIXTURES_DIR / "corrupt_image.jpg")

    assert viewer.is_showing_image is False
    assert viewer.is_showing_video is False


def test_toggle_playback_starts_and_pauses_video(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)
    viewer.show_media(FIXTURES_DIR / "supported_video.webm")
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
    viewer = MediaViewer()
    qtbot.addWidget(viewer)
    viewer.show_media(FIXTURES_DIR / "supported_image.png")

    viewer.clear()

    assert viewer.is_showing_image is False
    assert viewer.is_showing_video is False
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
    _gif(gif, 3)
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    viewer.show_media(gif)

    assert viewer.is_showing_image is True
    assert viewer.image_view.is_animating is True
    viewer.clear()
    assert viewer.image_view.is_animating is False


def test_single_frame_gif_is_not_treated_as_an_animation(qtbot: QtBot, tmp_path: Path) -> None:
    gif = tmp_path / "still.gif"
    _gif(gif, 1)
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    viewer.show_media(gif)

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
