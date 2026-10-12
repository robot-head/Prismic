"""Runtime contracts exposed by postponed annotations and keyword-only APIs."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import get_type_hints

from PySide6.QtCore import QObject
from PySide6.QtGui import QImage

from prismic.domain.media import Media
from prismic.domain.tag import Tag
from prismic.indexing import reconciler
from prismic.indexing.reconciler import Reconciler, run_reconciliation
from prismic.media.cache import ImageCache
from prismic.media.image import ImageLoadError, load_image
from prismic.media.loader import ImageLoader, ImageLoadResult
from prismic.media.video import VideoPlayer
from prismic.persistence.preferences import PreferencesStore
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.tag_correlation_repository import TagCorrelationRepository
from prismic.persistence.repositories.tag_repository import TagRepository


def test_optional_and_union_annotations_resolve_to_the_documented_types() -> None:
    assert get_type_hints(reconciler._recorded_hash_if_unchanged)["recorded"] == Media | None
    assert get_type_hints(run_reconciliation)["on_progress"] == reconciler.ProgressCallback | None
    assert get_type_hints(PreferencesStore.__init__)["path"] == Path | None
    assert get_type_hints(TagRepository.get)["return"] == Tag | None
    assert get_type_hints(TagCorrelationRepository.last_computed_at)["return"] == float | None
    assert get_type_hints(ImageCache.get)["return"] == QImage | None
    assert get_type_hints(ImageLoader.__init__)["cache"] == ImageCache | None
    assert get_type_hints(ImageLoader.load)["return"] == ImageLoadResult | None
    assert get_type_hints(load_image)["return"] == QImage | ImageLoadError
    assert get_type_hints(VideoPlayer.__init__)["parent"] == QObject | None


def test_configuration_parameters_remain_keyword_only() -> None:
    signatures = (
        (MediaRepository.update, "fields", inspect.Parameter.VAR_KEYWORD),
        (Reconciler.reconcile, "unreadable_paths", inspect.Parameter.KEYWORD_ONLY),
        (run_reconciliation, "on_progress", inspect.Parameter.KEYWORD_ONLY),
        (TagCorrelationRepository.__init__, "clock", inspect.Parameter.KEYWORD_ONLY),
        (TagCorrelationRepository.recompute, "min_cooccurrence", inspect.Parameter.KEYWORD_ONLY),
        (TagCorrelationRepository.ensure_fresh, "min_cooccurrence", inspect.Parameter.KEYWORD_ONLY),
        (TagCorrelationRepository.ensure_fresh, "max_age_seconds", inspect.Parameter.KEYWORD_ONLY),
    )

    for function, parameter_name, expected_kind in signatures:
        parameters = inspect.signature(function).parameters
        assert parameters[parameter_name].kind is expected_kind
