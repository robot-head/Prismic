from pathlib import Path

from pytestqt.qtbot import QtBot

from prismic.ui.main_window import MainWindow
from prismic.ui.tag_model import CheckedRole


def open_and_wait(
    qtbot: QtBot, window: MainWindow, collection_dir: Path, expected_count: int = 2
) -> None:
    window.open_collection(collection_dir)
    qtbot.waitUntil(lambda: window.result_model.rowCount() == expected_count, timeout=5000)


def checked_tag_names(window: MainWindow) -> set[str]:
    model = window.item_tag_panel.model
    return {
        model.tag_at(row).name
        for row in range(model.rowCount())
        if model.data(model.index(row, 0), CheckedRole)
    }
