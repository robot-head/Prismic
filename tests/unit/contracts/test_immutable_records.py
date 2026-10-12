from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import prismic.application.tag_ranking_settings as ranking_settings
import prismic.domain.collection as collection_domain
import prismic.domain.media as media_domain
import prismic.domain.tag as tag_domain
import prismic.indexing.reconciler as reconciler
import prismic.indexing.scanner as scanner
import prismic.media.loader as loader
from prismic.application.input.resolver import InputEvent
from prismic.application.input.shortcuts import SHORTCUTS
from prismic.indexing.reconciler import HashedFile
from tests.unit._record_contracts import assert_frozen_and_slotted


def test_public_input_and_settings_records_are_frozen_and_slotted() -> None:
    records: tuple[tuple[object, str], ...] = (
        (InputEvent(key="a"), "key"),
        (SHORTCUTS[0], "label"),
        (ranking_settings.TagRankingSettings(), "correlation_threshold"),
    )

    for record, field in records:
        assert_frozen_and_slotted(record, field=field)


@pytest.mark.parametrize(
    ("record", "field"),
    [
        (
            collection_domain.Collection(
                root=Path("root"), database_path=Path("root/collection.prismic")
            ),
            "root",
        ),
        (
            media_domain.Media(
                id=1,
                relative_path="photo.jpg",
                content_hash="hash",
                size=1,
                mtime=1.5,
                state=media_domain.MediaState.ACTIVE,
            ),
            "relative_path",
        ),
        (tag_domain.Tag(id=1, name="travel"), "name"),
        (
            scanner.ScannedFile(
                relative_path="photo.jpg",
                absolute_path=Path("photo.jpg"),
                size=1,
                mtime=1.5,
            ),
            "relative_path",
        ),
        (
            reconciler.HashedFile(
                relative_path="photo.jpg", content_hash="hash", size=1, mtime=1.5
            ),
            "relative_path",
        ),
        (reconciler.ReconciliationResult(applied=True), "applied"),
        (
            loader.ImageLoadResult(
                request_id=1,
                path=Path("photo.jpg"),
                image=None,
                error=None,
            ),
            "request_id",
        ),
    ],
)
def test_value_records_are_frozen_and_slotted(record: object, field: str) -> None:
    assert_frozen_and_slotted(record, field=field)


def test_hashed_file_is_frozen_and_uses_slots() -> None:
    hashed = HashedFile(relative_path="photo.jpg", content_hash="known-hash", size=12, mtime=98.5)

    with pytest.raises(FrozenInstanceError):
        hashed.relative_path = "renamed.jpg"  # type: ignore[misc]
    assert not hasattr(hashed, "__dict__")
