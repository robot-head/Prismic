from __future__ import annotations

import inspect
import os
from pathlib import Path
from types import TracebackType
from typing import get_type_hints

from PySide6.QtCore import QObject
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget

from prismic.application.input.shortcuts import ShortcutBindings
from prismic.application.tag_ranking_settings import TagRankingSettingsStore
from prismic.domain.media import Media
from prismic.domain.tag import Tag
from prismic.indexing import reconciler
from prismic.indexing.reconciler import Reconciler, run_reconciliation
from prismic.media.cache import ImageCache
from prismic.media.image import ImageLoadError, load_image
from prismic.media.loader import ImageLoader, ImageLoadResult
from prismic.media.video import VideoPlayer
from prismic.persistence.collection import OpenCollection, find_collection_file, open_collection
from prismic.persistence.preferences import PreferencesStore
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.tag_correlation_repository import TagCorrelationRepository
from prismic.persistence.repositories.tag_repository import TagRepository
from prismic.ui.main_window import MainWindow
from prismic.ui.result_list_view import ResultListView


def test_collection_file_lookup_annotations_resolve() -> None:
    assert get_type_hints(find_collection_file) == {
        "directory": Path,
        "return": Path | None,
    }


def test_collection_context_manager_annotations_resolve() -> None:
    assert get_type_hints(OpenCollection.__exit__) == {
        "exc_type": type[BaseException] | None,
        "exc_value": BaseException | None,
        "traceback": TracebackType | None,
        "return": type(None),
    }


def test_open_collection_path_annotations_resolve() -> None:
    assert get_type_hints(open_collection) == {
        "path": str | os.PathLike[str],
        "return": OpenCollection,
    }


def test_get_annotations_resolve_to_optional_media() -> None:
    assert get_type_hints(MediaRepository.get) == {
        "media_id": int,
        "return": Media | None,
    }


def test_get_by_relative_path_annotations_resolve_to_optional_media() -> None:
    assert get_type_hints(MediaRepository.get_by_relative_path) == {
        "relative_path": str,
        "return": Media | None,
    }


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


def test_main_window_union_annotations_resolve_to_their_declared_types() -> None:
    constructor_hints = get_type_hints(MainWindow.__init__)

    assert constructor_hints["initial_path"] == Path | None
    assert constructor_hints["bindings"] == ShortcutBindings | None
    assert constructor_hints["tag_ranking_settings"] == TagRankingSettingsStore | None
    assert get_type_hints(MainWindow._create_tag_and_find)["return"] == Tag | None
    assert get_type_hints(MainWindow._on_item_tag_hover)["row"] == int | None
    assert get_type_hints(MainWindow._resolve_media_path)["return"] == Path | None


def test_constructor_parent_annotation_resolves_to_optional_widget() -> None:
    assert get_type_hints(ResultListView.__init__)["parent"] == QWidget | None
