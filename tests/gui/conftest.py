import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from prismic.ui.main_window import MainWindow

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "media"


@pytest.fixture
def collection_dir(tmp_path: Path) -> Path:
    """A real collection directory with two supported images in it."""
    root = tmp_path / "vacation"
    root.mkdir()
    shutil.copyfile(FIXTURES_DIR / "supported_image.png", root / "a.png")
    shutil.copyfile(FIXTURES_DIR / "supported_image.png", root / "b.png")
    return root


@pytest.fixture
def window(qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> MainWindow:
    settings_path = tmp_path / "settings.ini"
    monkeypatch.setattr(
        "prismic.ui.main_window.QSettings",
        lambda: QSettings(str(settings_path), QSettings.Format.IniFormat),
    )
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    return win
