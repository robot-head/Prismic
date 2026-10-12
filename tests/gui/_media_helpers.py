"""Reusable media and image fixtures for GUI tests."""

from PySide6.QtGui import QImage

from prismic.domain.media import Media, MediaState


def make_media(*, media_id: int = 1, relative_path: str = "photo.jpg") -> Media:
    return Media(
        id=media_id,
        relative_path=relative_path,
        content_hash="hash",
        size=1,
        mtime=1.0,
        state=MediaState.ACTIVE,
    )


def solid_image(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    return image
