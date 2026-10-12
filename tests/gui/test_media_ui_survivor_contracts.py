"""Focused behavior checks for surviving thumbnail and viewer mutations."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QImage, QPainterPath, QPixmap
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytestqt.qtbot import QtBot

import prismic.ui.viewer as viewer_module
from prismic.ui.result_model import MediaIdRole
from prismic.ui.selection_grid_view import _best_grid
from prismic.ui.thumbnail_delegate import ThumbnailDelegate
from prismic.ui.thumbnail_services import ThumbnailServices
from prismic.ui.viewer import MediaViewer
from tests.gui._media_helpers import solid_image
from tests.gui._paint_helpers import PaintStub
from tests.gui._viewer_helpers import show_media


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


def test_grid_keeps_a_candidate_with_one_pixel_cells() -> None:
    columns, cell_width, cell_height = _best_grid(2, 32, 1)

    assert columns == 2
    assert cell_width == 1
    assert cell_height == 1


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


def _show_image(qtbot: QtBot, monkeypatch, image: QImage, path: Path) -> MediaViewer:
    monkeypatch.setattr(viewer_module, "load_image", lambda _path: image)
    return show_media(qtbot, path)


def test_single_frame_gif_falls_back_to_a_still_image(qtbot: QtBot, monkeypatch) -> None:
    image = solid_image(2, 2)
    monkeypatch.setattr(viewer_module, "QImageReader", lambda path: _Reader(path, 1))
    viewer = _show_image(qtbot, monkeypatch, image, Path("still.gif"))

    assert viewer.is_showing_image
    assert not viewer.image_view.is_animating


def test_animated_gif_starts_on_its_first_frame(qtbot: QtBot, monkeypatch) -> None:
    movies: list[_Movie] = []

    def make_movie(path: str) -> _Movie:
        movie = _Movie(path)
        movies.append(movie)
        return movie

    monkeypatch.setattr(viewer_module, "QImageReader", lambda path: _Reader(path, 2))
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


class _InlinePool:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def submit(self, function: Callable[..., object], *args: object) -> object:
        self.paths.append(args[-1])  # type: ignore[arg-type]
        return function(*args)


def test_preload_warms_images_and_skips_videos(qtbot: QtBot, monkeypatch) -> None:
    image = solid_image(3, 2)
    monkeypatch.setattr("prismic.media.loader.load_image", lambda _path: image)
    pool = _InlinePool()
    viewer = MediaViewer(worker_pool=lambda: pool)  # type: ignore[arg-type]
    qtbot.addWidget(viewer)
    photo = Path("photo.png")
    video = Path("clip.webm")

    viewer.preload(photo)
    viewer.preload(video)

    assert pool.paths == [photo]
    assert viewer._image_loader._cache.get(str(photo)) is not None  # noqa: SLF001


def test_preload_without_a_worker_pool_is_a_no_op(qtbot: QtBot) -> None:
    viewer = MediaViewer()
    qtbot.addWidget(viewer)

    viewer.preload(Path("photo.png"))
