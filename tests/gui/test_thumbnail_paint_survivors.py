"""Behavioral coverage for thumbnail painting and video badges."""

from pathlib import Path

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
from pytestqt.qtbot import QtBot

from prismic.ui import theme
from prismic.ui._thumbnail_badge import paint_play_badge
from prismic.ui.result_model import MediaIdRole
from prismic.ui.thumbnail_delegate import ThumbnailDelegate


class _Provider:
    def __init__(self, pixmaps: dict[int, QPixmap] | None = None) -> None:
        self.pixmaps = pixmaps or {}
        self.failed: set[int] = set()
        self.requests: list[tuple[int, Path, object]] = []

    def get(self, media_id: int) -> QPixmap | None:
        return self.pixmaps.get(media_id)

    def has_failed(self, media_id: int) -> bool:
        return media_id in self.failed

    def request(self, media_id: int, path: Path, pool: object) -> None:
        self.requests.append((media_id, path, pool))


def _delegate(
    provider: _Provider,
    *,
    resolve_path=lambda media_id: Path(f"/collection/{media_id}.jpg"),
    worker_pool=lambda: object(),
) -> ThumbnailDelegate:
    return ThumbnailDelegate(provider, resolve_path, worker_pool)


def _option(
    rect: QRect | None = None,
    state: QStyle.StateFlag = QStyle.StateFlag.State_None,
) -> QStyleOptionViewItem:
    option = QStyleOptionViewItem()
    option.rect = QRect(10, 20, 300, 64) if rect is None else rect
    option.state = state
    return option


def _model_and_index(name: str = "photo.jpg") -> tuple[QStandardItemModel, QModelIndex]:
    model = QStandardItemModel()
    item = QStandardItem(name)
    item.setData(17, MediaIdRole)
    model.appendRow(item)
    return model, model.index(0, 0)


def _render(delegate: ThumbnailDelegate, *, name: str = "photo.jpg", state=None) -> QImage:
    image = QImage(340, 110, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    _model, index = _model_and_index(name)
    delegate.paint(painter, _option(state=state or QStyle.StateFlag.State_None), index)
    painter.end()
    return image


def _striped_pixmap(*, horizontal: bool) -> QPixmap:
    pixmap = QPixmap(48, 96) if horizontal else QPixmap(96, 48)
    pixmap.fill(QColor("#e02020"))
    painter = QPainter(pixmap)
    painter.fillRect(
        QRect(0, 48, 48, 48) if horizontal else QRect(48, 0, 48, 48),
        QColor("#2040e0"),
    )
    painter.end()
    return pixmap


def test_play_badge_draws_a_centered_circle_and_right_facing_triangle(qtbot: QtBot) -> None:
    image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    background = QColor("#ff00ff")
    image.fill(background)
    painter = QPainter(image)
    paint_play_badge(painter, QRectF(10, 20, 80, 60), size_fraction=0.25)
    painter.end()

    # The circle radius is 15 (one quarter of the 60px short side), centered
    # at (50, 50); the play glyph is white and points to the right.
    assert image.pixelColor(50, 50) == QColor(theme.TEXT_PRIMARY)
    assert image.pixelColor(54, 50) == QColor(theme.TEXT_PRIMARY)
    assert image.pixelColor(43, 50) != QColor(theme.TEXT_PRIMARY)
    assert image.pixelColor(50, 40).red() < background.red()
    assert image.pixelColor(50, 32) == background


def test_delegate_size_hint_tracks_thumbnail_mode() -> None:
    delegate = _delegate(_Provider())
    option = _option(QRect(0, 0, 240, 100))
    _model, index = _model_and_index()

    assert delegate.sizeHint(option, index) == QSize(240, 32)
    delegate.show_thumbnails = True
    assert delegate.sizeHint(option, index) == QSize(240, 64)


def test_selected_row_wash_is_stronger_than_hover_wash(qtbot: QtBot) -> None:
    delegate = _delegate(_Provider())
    hovered = _render(delegate, state=QStyle.StateFlag.State_MouseOver)
    selected = _render(
        delegate,
        state=QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver,
    )

    hover_pixel = hovered.pixelColor(300, 21)
    selected_pixel = selected.pixelColor(300, 21)
    assert selected_pixel.red() > hover_pixel.red() > 0
    assert selected_pixel.green() > hover_pixel.green()
    assert selected_pixel.blue() > hover_pixel.blue()


def test_hover_only_state_does_not_get_treated_as_selected(qtbot: QtBot) -> None:
    delegate = _delegate(_Provider())
    hovered = _render(delegate, state=QStyle.StateFlag.State_MouseOver)
    selected = _render(delegate, state=QStyle.StateFlag.State_Selected)

    assert hovered.pixelColor(300, 21).red() < selected.pixelColor(300, 21).red()


def test_missing_image_placeholder_requests_its_thumbnail(qtbot: QtBot) -> None:
    provider = _Provider()
    pool = object()
    path = Path("/collection/photo.jpg")
    delegate = _delegate(provider, resolve_path=lambda _media_id: path, worker_pool=lambda: pool)
    delegate.show_thumbnails = True

    image = _render(delegate)

    assert image.pixelColor(42, 52) == QColor(theme.THUMB_PLACEHOLDER)
    assert provider.requests == [(17, path, pool)]


def test_video_placeholder_gets_a_badge_without_starting_a_thumbnail_request(
    qtbot: QtBot,
) -> None:
    provider = _Provider()
    delegate = _delegate(provider)
    delegate.show_thumbnails = True

    image = _render(delegate, name="clip.webm")

    assert image.pixelColor(42, 52) == QColor(theme.TEXT_PRIMARY)
    assert image.pixelColor(42, 42).red() < QColor(theme.THUMB_PLACEHOLDER).red()
    assert provider.requests == []


def test_cached_video_thumbnail_also_gets_the_play_badge(qtbot: QtBot) -> None:
    pixmap = QPixmap(48, 48)
    pixmap.fill(QColor("#2040e0"))
    provider = _Provider({17: pixmap})
    delegate = _delegate(provider)
    delegate.show_thumbnails = True

    image = _render(delegate, name="clip.webm")

    assert image.pixelColor(42, 52) == QColor(theme.TEXT_PRIMARY)
    assert image.pixelColor(42, 42).blue() < QColor("#2040e0").blue()
    assert provider.requests == []


def test_cached_wide_thumbnail_is_cropped_equally_from_both_sides(qtbot: QtBot) -> None:
    provider = _Provider({17: _striped_pixmap(horizontal=False)})
    delegate = _delegate(provider)
    delegate.show_thumbnails = True

    image = _render(delegate)

    assert image.pixelColor(30, 52) == QColor("#e02020")
    assert image.pixelColor(54, 52) == QColor("#2040e0")


def test_cached_tall_thumbnail_is_cropped_equally_from_top_and_bottom(qtbot: QtBot) -> None:
    provider = _Provider({17: _striped_pixmap(horizontal=True)})
    delegate = _delegate(provider)
    delegate.show_thumbnails = True

    image = _render(delegate)

    assert image.pixelColor(42, 40) == QColor("#e02020")
    assert image.pixelColor(42, 64) == QColor("#2040e0")


def test_filename_starts_after_thumbnail_and_uses_the_remaining_row_width(qtbot: QtBot) -> None:
    pixmap = QPixmap(48, 48)
    pixmap.fill(QColor("#2040e0"))
    delegate = _delegate(_Provider({17: pixmap}))
    delegate.show_thumbnails = True

    image = _render(delegate, name="M" * 80 + ".jpg")
    ink = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).red() > 180
        and image.pixelColor(x, y).green() > 180
        and image.pixelColor(x, y).blue() > 180
    ]

    assert ink
    assert min(x for x, _ in ink) >= 78
    assert max(x for x, _ in ink) < 302


def test_filename_starts_at_the_row_margin_when_thumbnails_are_hidden(qtbot: QtBot) -> None:
    image = _render(_delegate(_Provider()), name="M" * 30)
    ink = [
        x
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).red() > 180
        and image.pixelColor(x, y).green() > 180
        and image.pixelColor(x, y).blue() > 180
    ]

    assert ink
    assert min(ink) >= 18
