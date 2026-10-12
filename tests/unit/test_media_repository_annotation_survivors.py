"""Ensure optional media repository return types remain introspectable."""

from __future__ import annotations

from typing import get_type_hints

from prismic.domain.media import Media
from prismic.persistence.repositories.media_repository import MediaRepository


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
