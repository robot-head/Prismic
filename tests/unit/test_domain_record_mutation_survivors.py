from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import prismic.domain.collection as collection_domain
import prismic.domain.media as media_domain
import prismic.domain.tag as tag_domain
import prismic.indexing.reconciler as reconciler
import prismic.indexing.scanner as scanner
import prismic.media.loader as loader


@pytest.mark.parametrize(
    ("record", "field"),
    [
        (collection_domain.Collection(Path("root"), Path("root/collection.prismic")), "root"),
        (
            media_domain.Media(1, "photo.jpg", "hash", 1, 1.5, media_domain.MediaState.ACTIVE),
            "relative_path",
        ),
        (tag_domain.Tag(1, "travel"), "name"),
        (scanner.ScannedFile("photo.jpg", Path("photo.jpg"), 1, 1.5), "relative_path"),
        (reconciler.HashedFile("photo.jpg", "hash", 1, 1.5), "relative_path"),
        (reconciler.ReconciliationResult(applied=True), "applied"),
        (loader.ImageLoadResult(1, Path("photo.jpg"), None, None), "request_id"),
    ],
)
def test_value_records_are_frozen_and_slotted(record: object, field: str) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(record, field, "changed")

    assert not hasattr(record, "__dict__")
