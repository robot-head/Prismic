"""Reusable image fixtures for viewer tests."""

from PySide6.QtGui import QImage


def solid_image(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    return image
