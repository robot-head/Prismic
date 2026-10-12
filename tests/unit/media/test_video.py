from pathlib import Path

import pytest
from PySide6.QtMultimedia import QMediaPlayer
from pytestqt.qtbot import QtBot

from prismic.media.video import VideoPlayer


def _load_video_when_ready(qtbot: QtBot, path: Path) -> VideoPlayer:
    player = VideoPlayer()
    player.load(path)

    def _is_ready() -> bool:
        loaded = player.media_status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        )
        return loaded and player.duration_ms > 0

    qtbot.waitUntil(
        _is_ready,
        timeout=5000,
    )
    return player


@pytest.fixture
def loaded_video(qtbot: QtBot, fixtures_dir: Path) -> VideoPlayer:
    return _load_video_when_ready(qtbot, fixtures_dir / "supported_video.webm")


def test_load_supported_video_reports_no_error_and_a_positive_duration(
    loaded_video: VideoPlayer,
) -> None:
    player = loaded_video

    assert player.duration_ms > 0


def test_load_audio_bearing_video_reports_an_audio_track(qtbot: QtBot, fixtures_dir: Path) -> None:
    player = VideoPlayer()
    failures: list[str] = []
    player.load_failed.connect(failures.append)

    player.load(fixtures_dir / "audio_video.webm")
    player.play()

    qtbot.waitUntil(
        lambda: player.media_status == QMediaPlayer.MediaStatus.EndOfMedia, timeout=5000
    )

    assert failures == []
    assert len(player.qt_player.audioTracks()) >= 1
    assert len(player.qt_player.videoTracks()) >= 1


def test_load_corrupt_video_emits_load_failed(qtbot: QtBot, fixtures_dir: Path) -> None:
    player = VideoPlayer()

    with qtbot.waitSignal(player.load_failed, timeout=5000):
        player.load(fixtures_dir / "corrupt_video.webm")
        player.play()


def test_seek_and_pause_do_not_raise(loaded_video: VideoPlayer) -> None:
    player = loaded_video
    player.play()
    player.seek(500)
    player.pause()
    player.stop()


def test_playback_position_is_exposed_as_a_property(qtbot: QtBot) -> None:
    player = VideoPlayer()

    assert player.position_ms == player.qt_player.position()
