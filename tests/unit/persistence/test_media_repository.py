from __future__ import annotations

import sqlite3

import pytest

from prismic.domain.media import Media, MediaState
from prismic.indexing.reconciler import HashedFile, Reconciler
from prismic.persistence.errors import UnknownMediaError
from prismic.persistence.repositories import media_repository
from prismic.persistence.repositories.media_repository import MediaRepository


@pytest.fixture
def repository(migrated_connection: sqlite3.Connection) -> MediaRepository:
    return MediaRepository(migrated_connection)


def _create_cat_media(repository: MediaRepository) -> Media:
    return repository.create(
        relative_path="photos/cat.jpg",
        content_hash="hash-1",
        size=1024,
        mtime=1_700_000_000.0,
        state=MediaState.ACTIVE,
    )


def test_create_and_get_round_trip(repository: MediaRepository) -> None:
    created = _create_cat_media(repository)

    fetched = repository.get(created.id)

    assert fetched == created


def test_get_returns_none_for_unknown_id(repository: MediaRepository) -> None:
    assert repository.get(999) is None


def test_get_by_relative_path(repository: MediaRepository) -> None:
    created = _create_cat_media(repository)

    assert repository.get_by_relative_path("photos/cat.jpg") == created
    assert repository.get_by_relative_path("photos/missing.jpg") is None


def test_find_by_content_hash_returns_all_matches(repository: MediaRepository) -> None:
    first = repository.create(
        relative_path="a.jpg", content_hash="shared", size=1, mtime=1.0, state=MediaState.ACTIVE
    )
    second = repository.create(
        relative_path="b.jpg", content_hash="shared", size=2, mtime=2.0, state=MediaState.MISSING
    )
    repository.create(
        relative_path="c.jpg", content_hash="other", size=3, mtime=3.0, state=MediaState.ACTIVE
    )

    matches = repository.find_by_content_hash("shared")

    assert {media.id for media in matches} == {first.id, second.id}


def test_update_changes_the_stored_fields(repository: MediaRepository) -> None:
    created = repository.create(
        relative_path="a.jpg", content_hash="old", size=1, mtime=1.0, state=MediaState.ACTIVE
    )

    updated = repository.update(
        created.id,
        relative_path="moved/a.jpg",
        content_hash="old",
        size=1,
        mtime=2.0,
        state=MediaState.MISSING,
    )

    assert updated.relative_path == "moved/a.jpg"
    assert updated.state is MediaState.MISSING
    assert repository.get(created.id) == updated


def test_update_unknown_id_raises(repository: MediaRepository) -> None:
    with pytest.raises(UnknownMediaError):
        repository.update(
            999, relative_path="a.jpg", content_hash="h", size=1, mtime=1.0, state=MediaState.ACTIVE
        )


def test_list_all_is_ordered_by_relative_path(repository: MediaRepository) -> None:
    repository.create(
        relative_path="z.jpg", content_hash="h1", size=1, mtime=1.0, state=MediaState.ACTIVE
    )
    repository.create(
        relative_path="a.jpg", content_hash="h2", size=1, mtime=1.0, state=MediaState.ACTIVE
    )

    assert [media.relative_path for media in repository.list_all()] == ["a.jpg", "z.jpg"]


def test_count_is_zero_for_an_empty_collection(repository: MediaRepository) -> None:
    assert repository.count() == 0


def test_count_reflects_every_row_regardless_of_state(repository: MediaRepository) -> None:
    repository.create(
        relative_path="a.jpg", content_hash="h1", size=1, mtime=1.0, state=MediaState.ACTIVE
    )
    repository.create(
        relative_path="b.jpg", content_hash="h2", size=1, mtime=1.0, state=MediaState.MISSING
    )

    assert repository.count() == 2


@pytest.mark.parametrize(
    ("original_path", "scanned_path"),
    [("photo.jpg", "photo.jpg"), ("old/photo.jpg", "new/photo.jpg")],
    ids=["restored-at-same-path", "moved-after-missing"],
)
def test_previously_missing_media_is_reactivated_without_changing_identity(
    migrated_connection: sqlite3.Connection,
    original_path: str,
    scanned_path: str,
) -> None:
    repository = media_repository.MediaRepository(migrated_connection)
    original = repository.create(
        relative_path=original_path,
        content_hash="same-content",
        size=12,
        mtime=98.5,
        state=MediaState.MISSING,
    )
    reconciler = Reconciler()

    result = reconciler.reconcile(
        migrated_connection,
        reconciler.begin_scan(),
        [
            HashedFile(
                relative_path=scanned_path,
                content_hash="same-content",
                size=12,
                mtime=98.5,
            )
        ],
    )

    restored = repository.get(original.id)
    assert result.applied is True
    assert result.moved_count == 1
    assert restored is not None
    assert restored.id == original.id
    assert restored.relative_path == scanned_path
    assert restored.state is MediaState.ACTIVE
