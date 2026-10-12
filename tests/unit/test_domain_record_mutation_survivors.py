from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from prismic.domain.collection import Collection
from prismic.domain.media import Media, MediaState
from prismic.domain.tag import Tag
from prismic.indexing.reconciler import HashedFile, ReconciliationResult
from prismic.indexing.scanner import ScannedFile
from prismic.media.loader import ImageLoadResult


@pytest.mark.parametrize(
    ("record", "field"),
    [
        (Collection(Path("root"), Path("root/collection.prismic")), "root"),
        (Media(1, "photo.jpg", "hash", 1, 1.5, MediaState.ACTIVE), "relative_path"),
        (Tag(1, "travel"), "name"),
        (ScannedFile("photo.jpg", Path("photo.jpg"), 1, 1.5), "relative_path"),
        (HashedFile("photo.jpg", "hash", 1, 1.5), "relative_path"),
        (ReconciliationResult(applied=True), "applied"),
        (ImageLoadResult(1, Path("photo.jpg"), None, None), "request_id"),
    ],
)
def test_value_records_are_frozen_and_slotted(record: object, field: str) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(record, field, "changed")

    assert not hasattr(record, "__dict__")
