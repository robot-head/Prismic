"""Checks for stale thumbnail completion and the smallest supported size."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path

from PySide6.QtGui import QImage
from pytestqt.qtbot import QtBot

from prismic.ui.thumbnail_provider import ThumbnailProvider


def test_a_decode_for_an_old_generation_cannot_repopulate_the_cache(qtbot: QtBot) -> None:
    provider = ThumbnailProvider()
    stale_generation = provider._generation  # noqa: SLF001
    provider.reset()
    ready: list[int] = []
    provider.thumbnail_ready.connect(ready.append)
    image = QImage(4, 3, QImage.Format.Format_RGB32)
    image.fill(0x336699)

    provider._on_done(  # noqa: SLF001
        media_id=17,
        generation=stale_generation,
        dimension=32,
        image=image,
    )

    assert provider.get(17) is None
    assert ready == []


def test_a_request_for_one_pixel_still_starts_a_decode(qtbot: QtBot) -> None:
    submitted: list[tuple[object, ...]] = []

    class Pool:
        def submit(self, *args: object) -> Future[object]:
            submitted.append(args)
            return Future()

    provider = ThumbnailProvider()
    provider.request(4, Path("photo.png"), Pool(), dimension=1)  # type: ignore[arg-type]

    assert len(submitted) == 1
    assert submitted[0][-1] == 1
