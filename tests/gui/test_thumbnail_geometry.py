from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPixmap
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QWidget
from pytestqt.qtbot import QtBot

from prismic.ui.result_model import MediaIdRole
from prismic.ui.thumbnail_delegate import ThumbnailDelegate
from prismic.ui.thumbnail_services import ThumbnailServices
from tests.gui._paint_helpers import PaintStub


class _Index:
    def data(self, role: int) -> object:
        if role == int(MediaIdRole):
            return 17
        if role == int(Qt.ItemDataRole.DisplayRole):
            return "photo.jpg"
        return None


class _RecordingPainter(PaintStub):
    def __init__(self) -> None:
        self.text_alignments: list[Qt.AlignmentFlag] = []
        self.pixmap_positions: list[QPoint] = []

    def drawText(self, _rect: QRectF, alignment: Qt.AlignmentFlag, _text: str) -> None:
        self.text_alignments.append(alignment)

    def setClipPath(self, _path: QPainterPath) -> None:
        pass

    def drawPixmap(self, x: int, y: int, _pixmap: QPixmap) -> None:
        self.pixmap_positions.append(QPoint(x, y))


class _Provider:
    def __init__(self, pixmap: QPixmap | None = None) -> None:
        self.pixmap = pixmap

    def get(self, _media_id: int) -> QPixmap | None:
        return self.pixmap

    def has_failed(self, _media_id: int) -> bool:
        return False


def _delegate(pixmap: QPixmap | None = None) -> ThumbnailDelegate:
    services = ThumbnailServices(_Provider(pixmap), lambda: None)  # type: ignore[arg-type]
    return ThumbnailDelegate(services, lambda _media_id: Path("photo.jpg"))


def _paint_option() -> QStyleOptionViewItem:
    option = QStyleOptionViewItem()
    option.rect = QRect(10, 20, 300, 64)
    option.state = QStyle.StateFlag.State_None
    return option


def test_delegate_text_is_left_aligned_and_vertically_centered(qtbot: QtBot) -> None:
    painter = _RecordingPainter()

    _delegate().paint(painter, _paint_option(), _Index())  # type: ignore[arg-type]

    assert painter.text_alignments == [Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft]


def test_delegate_centers_odd_horizontal_and_vertical_crops(qtbot: QtBot) -> None:
    horizontal_painter = _RecordingPainter()
    horizontal = _delegate(QPixmap(53, 48))
    horizontal.show_thumbnails = True
    horizontal.paint(horizontal_painter, _paint_option(), _Index())  # type: ignore[arg-type]

    vertical_painter = _RecordingPainter()
    vertical = _delegate(QPixmap(48, 53))
    vertical.show_thumbnails = True
    vertical.paint(vertical_painter, _paint_option(), _Index())  # type: ignore[arg-type]

    assert horizontal_painter.pixmap_positions == [QPoint(15, 28)]
    assert vertical_painter.pixmap_positions == [QPoint(18, 25)]


class _ModelIndex:
    def __init__(self, media_id: object, name: object) -> None:
        self._values = {int(MediaIdRole): media_id, int(Qt.ItemDataRole.DisplayRole): name}

    def data(self, role: int) -> object:
        return self._values.get(role)


class _Painter(PaintStub):
    def __init__(self) -> None:
        self.text_rects: list[QRectF] = []
        self.clips: list[QPainterPath] = []
        self.fills: list[tuple[QRectF, object]] = []

    def drawText(self, rect: QRectF, _alignment: Qt.AlignmentFlag, _text: str) -> None:
        self.text_rects.append(rect)

    def setClipPath(self, path: QPainterPath) -> None:
        self.clips.append(path)

    def fillRect(self, rect: QRectF, color: object) -> None:
        self.fills.append((rect, color))


class _FailedProvider:
    def get(self, _media_id: int) -> None:
        return None

    def has_failed(self, _media_id: int) -> bool:
        return True


def _failed_provider_delegate(qtbot: QtBot) -> ThumbnailDelegate:
    parent = QWidget()
    qtbot.addWidget(parent)
    return ThumbnailDelegate(
        ThumbnailServices(_FailedProvider(), lambda: None),
        lambda _media_id: Path("photo.jpg"),
        parent,
    )


def test_thumbnail_and_filename_keep_their_exact_row_offsets(qtbot: QtBot, monkeypatch) -> None:
    delegate = _failed_provider_delegate(qtbot)
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
    delegate.paint(painter, option, _ModelIndex(17, "photo.jpg"))
    assert thumbnails == [QRectF(18, 28.5, 48, 48)]
    assert painter.text_rects == [QRectF(78, 20, 223, 65)]


def test_thumbnail_clips_to_the_expected_rounded_rectangle(qtbot: QtBot) -> None:
    delegate = _failed_provider_delegate(qtbot)
    painter = _Painter()
    rect = QRectF(18, 28, 48, 48)
    delegate._paint_thumbnail(painter, rect, 17, "photo.jpg")
    expected = QPainterPath()
    expected.addRoundedRect(rect, 6, 6)
    assert painter.clips == [expected]


def test_invalid_media_ids_are_ignored_even_when_the_name_is_valid(qtbot: QtBot) -> None:
    delegate = _failed_provider_delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(10, 20, 300, 64)
    painter = _Painter()
    delegate.paint(
        painter,
        option,
        _ModelIndex("invalid", "photo.jpg"),
    )
    assert painter.text_rects == []


def test_an_idle_row_does_not_get_the_hover_wash(qtbot: QtBot) -> None:
    delegate = _failed_provider_delegate(qtbot)
    option = QStyleOptionViewItem()
    option.rect = QRect(10, 20, 300, 64)
    option.state = QStyle.StateFlag.State_None
    painter = _Painter()
    delegate.paint(painter, option, _ModelIndex(17, "photo.jpg"))
    assert painter.fills == []
