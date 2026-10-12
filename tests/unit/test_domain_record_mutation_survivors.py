from pathlib import Path

import pytest

import prismic.domain.collection as collection_domain
import prismic.domain.media as media_domain
import prismic.domain.tag as tag_domain
import prismic.indexing.reconciler as reconciler
import prismic.indexing.scanner as scanner
import prismic.media.loader as loader
from tests.unit._record_contracts import assert_frozen_and_slotted


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
