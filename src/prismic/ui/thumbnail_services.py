"""Shared access to thumbnail decoding for list and grid views."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from prismic.application.worker_pool import WorkerPool
from prismic.media.formats import SUPPORTED_VIDEO_EXTENSIONS
from prismic.ui.thumbnail_provider import ThumbnailProvider


class ThumbnailServices:
    def __init__(
        self,
        provider: ThumbnailProvider,
        worker_pool: Callable[[], WorkerPool | None],
    ) -> None:
        self.provider = provider
        self._worker_pool = worker_pool

    @staticmethod
    def is_video(path: str | Path) -> bool:
        return Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS

    def request(self, media_id: int, path: Path, dimension: int | None = None) -> None:
        if self.is_video(path):
            return
        pool = self._worker_pool()
        if pool is not None:
            self.provider.request(media_id, path, pool, dimension)
