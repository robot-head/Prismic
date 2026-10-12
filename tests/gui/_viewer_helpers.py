"""Shared constructors for tests that display media in the viewer."""

from pathlib import Path

from pytestqt.qtbot import QtBot

from prismic.ui.viewer import MediaViewer


def assert_viewer_empty(viewer: MediaViewer) -> None:
    assert not viewer.is_showing_image
    assert not viewer.is_showing_video


def show_media(qtbot: QtBot, path: Path) -> MediaViewer:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)
    viewer.show_media(path)
    return viewer
