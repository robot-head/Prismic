"""Contract tests for thumbnail row geometry and invalid model data."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QWidget
from pytestqt.qtbot import QtBot

from prismic.ui.result_model import MediaIdRole
from prismic.ui.thumbnail_delegate import ThumbnailDelegate


class _Index:
    def __init__(self, media_id: object, name: object) -> None:
        self._values = {int(MediaIdRole): media_id, int(Qt.ItemDataRole.DisplayRole): name}

    def data(self, role: int) -> object:
        return self._values.get(role)


class _Metrics:
    def elidedText(self, text: str, _mode: Qt.TextElideMode, _width: int) -> str:
        return text


class _Painter:
    def __init__(self) -> None:
        self.text_rects: list[QRectF] = []
        self.clips: list[QPainterPath] = []
        self.fills: list[tuple[QRectF, object]] = []

    def save(self) -> None:
        pass

    def restore(self) -> None:
        pass

    def setRenderHint(self, _hint: QPainter.RenderHint) -> None:
        pass

    def setPen(self, _pen: object) -> None:
        pass

    def fontMetrics(self) -> _Metrics:
        return _Metrics()

    def drawText(self, rect: QRectF, _alignment: Qt.AlignmentFlag, _text: str) -> None:
        self.text_rects.append(rect)

    def setClipPath(self, path: QPainterPath) -> None:
        self.clips.append(path)

    def fillRect(self, rect: QRectF, color: object) -> None:
        self.fills.append((rect, color))


class _Provider:
    def get(self, _media_id: int) -> None:
        return None

    def has_failed(self, _media_id: int) -> bool:
        return True


def _delegate(qtbot: QtBot) -> ThumbnailDelegate:
    parent = QWidget()
    qtbot.addWidget(parent)
    return ThumbnailDelegate(_Provider(), lambda _media_id: Path("photo.jpg"), lambda: None, parent)  # type: ignore[arg-type]


def test_thumbnail_and_filename_keep_their_exact_row_offsets(qtbot: QtBot, monkeypatch) -> None:
    delegate = _delegate(qtbot)
    delegate.show_thumbnails = True
    thumbnails: list[QRectF] = []
    monkeypatch.setattr(
        delegate,
        "_paint_thumbnail",
        lambda _painter, rect, _media_id, _name: thumbnails.append(rect),
    )
    option = QStyleOptionViewItem()
    option.rect = QRect(10, 20, 300, 65)
    painter = _Painter()

    delegate.paint(painter, option, _Index(17, "photo.jpg"))  # type: ignore[arg-type]

    assert thumbnails == [QRectF(18, 28.5, 48, 48)]
    assert painter.text_rects == [QRectF(78, 20, 223, 65)]


def test_thumbnail_clips_to_the_expected_rounded_rectangle(qtbot: QtBot) -> None:
    delegate = _delegate(qtbot)
    painter = _Painter()
    rect = QRectF(18, 28, 48, 48)

    delegate._paint_thumbnail(painter, rect, 17, "photo.jpg")  # type: ignore[arg-type]

    expected = QPainterPath()
    expected.addRoundedRect(rect, 6, 6)
    assert painter.clips == [expected]


def test_invalid_media_ids_are_ignored_even_when_the_name_is_valid(qtbot: QtBot) -> None:
    delegate = _delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(10, 20, 300, 64)
    painter = _Painter()

    delegate.paint(painter, option, _Index("invalid", "photo.jpg"))  # type: ignore[arg-type]

    assert painter.text_rects == []


def test_an_idle_row_does_not_get_the_hover_wash(qtbot: QtBot) -> None:
    delegate = _delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(10, 20, 300, 64)
    option.state = QStyle.StateFlag.State_None
    painter = _Painter()

    delegate.paint(painter, option, _Index(17, "photo.jpg"))  # type: ignore[arg-type]

    assert painter.fills == []
