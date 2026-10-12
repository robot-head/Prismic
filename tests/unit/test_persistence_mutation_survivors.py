"""Behavioral contracts for persistence and indexing survivor mutations."""

from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from prismic.domain.media import Media, MediaState
from prismic.indexing.reconciler import (
    HashedFile,
    Reconciler,
    _recorded_hash_if_unchanged,
)
from prismic.indexing.scanner import ScannedFile
from prismic.persistence import database, migrations
from prismic.persistence.repositories import mapping_repository, media_repository, tag_repository
from tests.unit._lockfile_helpers import load_windows_lockfile
from tests.unit._migration_helpers import assert_migration_failure_preserves_version


def test_hash_cache_rejects_a_file_modified_within_the_two_second_safety_window() -> None:
    scanned = ScannedFile(
        relative_path="photo.jpg",
        absolute_path=Path("photo.jpg"),
        size=12,
        mtime=98.5,
    )
    recorded = Media(
        id=1,
        relative_path="photo.jpg",
        content_hash="known-hash",
        size=12,
        mtime=98.5,
        state=MediaState.ACTIVE,
    )

    assert _recorded_hash_if_unchanged(scanned, recorded, now=100.0) is None


def test_hashed_file_is_frozen_and_uses_slots() -> None:
    hashed = HashedFile(relative_path="photo.jpg", content_hash="known-hash", size=12, mtime=98.5)

    with pytest.raises(FrozenInstanceError):
        hashed.relative_path = "renamed.jpg"  # type: ignore[misc]
    assert not hasattr(hashed, "__dict__")


def test_scan_generations_start_at_one_and_advance_once() -> None:
    reconciler = Reconciler()

    assert reconciler.begin_scan() == 1
    assert reconciler.begin_scan() == 2


def test_equal_generation_values_apply_even_when_the_int_objects_differ(
    migrated_connection: sqlite3.Connection,
) -> None:
    reconciler = Reconciler()
    for _ in range(300):
        generation = reconciler.begin_scan()
    equal_generation = int(str(generation))
    assert equal_generation == generation
    assert equal_generation is not generation

    result = reconciler.reconcile(migrated_connection, equal_generation, [])

    assert result.applied is True


def test_future_generation_is_discarded(migrated_connection: sqlite3.Connection) -> None:
    reconciler = Reconciler()
    generation = reconciler.begin_scan()

    result = reconciler.reconcile(migrated_connection, generation + 1, [])

    assert result.applied is False


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


def test_migration_failure_after_version_two_preserves_that_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "collection.prismic"
    connection = database.connect(database_path)
    try:
        existing_migrations = migrations.MIGRATIONS

        def fail_after_version_two(conn: sqlite3.Connection) -> None:
            raise RuntimeError("stop before the next migration")

        monkeypatch.setattr(
            migrations,
            "MIGRATIONS",
            [existing_migrations[0], existing_migrations[1], fail_after_version_two],
        )

        assert_migration_failure_preserves_version(connection, database_path, expected_version=2)
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'scan_stats'"
            ).fetchone()
            is not None
        )
    finally:
        connection.close()


def test_mega_popular_tag_threshold_includes_a_tag_on_the_only_media(
    migrated_connection: sqlite3.Connection,
) -> None:
    media = media_repository.MediaRepository(migrated_connection).create(
        "photo.jpg", "hash", 1, 1.5, MediaState.ACTIVE
    )
    tags = tag_repository.TagRepository(migrated_connection)
    tag = tags.create("vacation")
    mapping_repository.MappingRepository(migrated_connection).add(media.id, tag.id)

    assert tags.mega_popular_tag_ids(1.0, total_media_count=1) == frozenset({tag.id})


def test_negative_total_media_count_never_produces_popular_tags(
    migrated_connection: sqlite3.Connection,
) -> None:
    tags = tag_repository.TagRepository(migrated_connection)
    tag = tags.create("vacation")

    assert tags.mega_popular_tag_ids(-1.0, total_media_count=-1) == frozenset()
    assert tags.get(tag.id) == tag


def test_windows_lock_detection_uses_platform_value_equality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distinct_platform = bytearray(b"win32").decode("ascii")
    canonical_platform = "".join(("win", "32"))
    assert distinct_platform == "win32"
    assert distinct_platform is not canonical_platform
    fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=lambda *_args: None)
    module = load_windows_lockfile(monkeypatch, distinct_platform, fake_msvcrt)

    assert module._LOCK_OFFSET == 1 << 40
