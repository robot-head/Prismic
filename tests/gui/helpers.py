from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from prismic.application.session import PrismicSession
from prismic.domain.tag import Tag
from prismic.ui.main_window import MainWindow
from prismic.ui.scan_progress_bar import ScanProgressBar
from prismic.ui.tag_model import CheckedRole


def open_and_wait(
    qtbot: QtBot, window: MainWindow, collection_dir: Path, expected_count: int = 2
) -> PrismicSession:
    window.open_collection(collection_dir)
    qtbot.waitUntil(lambda: window.result_model.rowCount() == expected_count, timeout=5000)
    session = window.session
    assert session is not None
    return session


def create_tag(window: MainWindow, name: str = "vacation") -> Tag:
    window._on_tag_create(name)
    session = window.session
    assert session is not None
    return next(tag for tag in session.tags.list_all() if tag.name == name)


def open_and_create_tag(
    qtbot: QtBot,
    window: MainWindow,
    collection_dir: Path,
    name: str = "vacation",
) -> Tag:
    open_and_wait(qtbot, window, collection_dir)
    return create_tag(window, name)


def shown_parent(
    qtbot: QtBot,
    width: int,
    height: int,
    *,
    position: QPoint | None = None,
) -> QWidget:
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(width, height)
    if position is not None:
        parent.move(position)
    parent.show()
    qtbot.waitExposed(parent)
    return parent


def open_three_item_collection(
    qtbot: QtBot, window: MainWindow, collection_dir: Path
) -> PrismicSession:
    (collection_dir / "c.png").write_bytes((collection_dir / "a.png").read_bytes())
    open_and_wait(qtbot, window, collection_dir, expected_count=3)
    session = window.session
    assert session is not None
    return session


def refresh_and_hover_item_tag(window: MainWindow, row: int) -> None:
    window._refresh_all()
    window._on_item_tag_hover(row)


def checked_tag_names(window: MainWindow) -> set[str]:
    model = window.item_tag_panel.model
    return {
        model.tag_at(row).name
        for row in range(model.rowCount())
        if model.data(model.index(row, 0), CheckedRole)
    }


def make_scan_progress_bar(qtbot: QtBot) -> ScanProgressBar:
    bar = ScanProgressBar()
    qtbot.addWidget(bar)
    return bar
