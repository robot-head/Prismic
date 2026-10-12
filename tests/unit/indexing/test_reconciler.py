from __future__ import annotations

import sqlite3
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path

import pytest

from prismic.domain.collection import Collection
from prismic.domain.media import Media, MediaState
from prismic.indexing import reconciler as reconciler_module
from prismic.indexing.reconciler import (
    HashedFile,
    Reconciler,
    ReconciliationResult,
    _recorded_hash_if_unchanged,
    run_reconciliation,
)
from prismic.indexing.scanner import ScannedFile
from prismic.persistence.repositories.media_repository import MediaRepository
from tests._reconciliation_test_context import ReconciliationTestContext


def _cache_records(
    *,
    cache_size: int,
    persisted_size: int,
    cache_mtime: float,
    persisted_mtime: float,
    content_hash: str,
    state: MediaState = MediaState.ACTIVE,
) -> tuple[ScannedFile, Media]:
    scanned = ScannedFile(
        relative_path="photo.jpg",
        absolute_path=Path("photo.jpg"),
        size=cache_size,
        mtime=cache_mtime,
    )
    recorded = Media(
        id=1,
        relative_path="photo.jpg",
        content_hash=content_hash,
        size=persisted_size,
        mtime=persisted_mtime,
        state=state,
    )
    return scanned, recorded


@pytest.mark.parametrize(
    ("state", "scanned_size", "recorded_size", "scanned_mtime", "recorded_mtime"),
    [
        (MediaState.MISSING, 1024, 1024, 10.5, 10.5),
        (MediaState.ACTIVE, 512, 1024, 10.5, 10.5),
        (MediaState.ACTIVE, 1024, 1024, 10.5, 10.75),
    ],
    ids=["non-active-record", "smaller-file", "older-record-mtime"],
)
def test_cached_hash_is_rejected_for_inactive_or_changed_records(
    state: MediaState,
    scanned_size: int,
    recorded_size: int,
    scanned_mtime: float,
    recorded_mtime: float,
) -> None:
    scanned, recorded = _cache_records(
        cache_size=scanned_size,
        persisted_size=recorded_size,
        cache_mtime=scanned_mtime,
        persisted_mtime=recorded_mtime,
        content_hash="old",
        state=state,
    )

    assert _recorded_hash_if_unchanged(scanned, recorded, now=100.0) is None


def test_cached_hash_size_comparison_uses_value_equality() -> None:
    recorded_size = int("1024")
    scanned_size = int("10" + "24")
    scanned, recorded = _cache_records(
        cache_size=scanned_size,
        persisted_size=recorded_size,
        cache_mtime=10.5,
        persisted_mtime=10.5,
        content_hash="same",
    )

    assert recorded_size == scanned_size
    assert recorded_size is not scanned_size
    assert _recorded_hash_if_unchanged(scanned, recorded, now=100.0) == "same"


def test_recent_mtime_cutoff_is_strict() -> None:
    scanned, recorded = _cache_records(
        cache_size=1024,
        persisted_size=1024,
        cache_mtime=98.125,
        persisted_mtime=98.125,
        content_hash="same",
    )

    assert _recorded_hash_if_unchanged(scanned, recorded, now=100.125) == "same"


def _outcome_counts(result: ReconciliationResult) -> tuple[int, int, int, int, int]:
    return (
        result.new_count,
        result.unchanged_count,
        result.changed_count,
        result.moved_count,
        result.missing_count,
    )


def test_reconciliation_result_count_defaults_are_zero() -> None:
    result = ReconciliationResult(applied=False)

    assert _outcome_counts(result) == (0, 0, 0, 0, 0)


def _hashed_file(relative_path: str, content_hash: str) -> HashedFile:
    return HashedFile(relative_path=relative_path, content_hash=content_hash, size=1, mtime=10.5)


def _reconcile_with_files(
    connection: sqlite3.Connection,
    reconciler: Reconciler,
    files: list[HashedFile],
    *,
    unreadable_paths: frozenset[str] = frozenset(),
) -> ReconciliationResult:
    return reconciler.reconcile(
        connection,
        reconciler.begin_scan(),
        files,
        unreadable_paths=unreadable_paths,
    )


def _active_record(
    repository: MediaRepository,
    relative_path: str,
    content_hash: str,
    *,
    mtime: float = 1.5,
) -> Media:
    return repository.create(
        relative_path=relative_path,
        content_hash=content_hash,
        size=1,
        mtime=mtime,
        state=MediaState.ACTIVE,
    )


def _repository_and_reconciler(
    connection: sqlite3.Connection,
) -> tuple[MediaRepository, Reconciler]:
    return MediaRepository(connection), Reconciler()


def test_reconciliation_reports_each_outcome_count(
    migrated_connection: sqlite3.Connection,
) -> None:
    repository, reconciler = _repository_and_reconciler(migrated_connection)
    unchanged = _active_record(repository, "unchanged.jpg", "same")
    changed = _active_record(repository, "changed.jpg", "old", mtime=2.5)
    moved = _active_record(repository, "old-location.jpg", "move", mtime=3.5)
    missing = _active_record(repository, "absent.jpg", "absent", mtime=4.5)

    result = _reconcile_with_files(
        migrated_connection,
        reconciler,
        [
            _hashed_file("unchanged.jpg", "same"),
            _hashed_file("changed.jpg", "replacement"),
            _hashed_file("new.jpg", "new"),
            _hashed_file("new-location.jpg", "move"),
        ],
    )

    assert result.applied
    assert _outcome_counts(result) == (1, 1, 1, 1, 1)
    after = repository.list_all()
    assert repository.get(unchanged.id) == unchanged
    assert repository.get(changed.id).state is MediaState.MISSING  # type: ignore[union-attr]
    assert repository.get(missing.id).state is MediaState.MISSING  # type: ignore[union-attr]
    assert repository.get(moved.id).relative_path == "new-location.jpg"  # type: ignore[union-attr]
    assert len(after) == 6


def test_unreadable_path_does_not_stop_later_missing_paths_from_being_marked(
    migrated_connection: sqlite3.Connection,
) -> None:
    repository, reconciler = _repository_and_reconciler(migrated_connection)
    unreadable = _active_record(repository, "a-unreadable.jpg", "a")
    absent = _active_record(repository, "b-absent.jpg", "b", mtime=2.5)

    result = _reconcile_with_files(
        migrated_connection,
        reconciler,
        [],
        unreadable_paths=frozenset({"a-unreadable.jpg"}),
    )

    assert result.missing_count == 1
    assert repository.get(unreadable.id) == unreadable
    assert repository.get(absent.id).state is MediaState.MISSING  # type: ignore[union-attr]


@dataclass(frozen=True, slots=True)
class _MediaSeed:
    relative_path: str
    content_hash: str
    mtime: float


def _create_active_seed(repository: MediaRepository, seed: _MediaSeed) -> Media:
    return repository.create(
        relative_path=seed.relative_path,
        content_hash=seed.content_hash,
        size=1,
        mtime=seed.mtime,
        state=MediaState.ACTIVE,
    )


def _two_media_records(
    connection: sqlite3.Connection,
    *,
    first: _MediaSeed,
    second: _MediaSeed,
) -> tuple[MediaRepository, Media, Media, Reconciler]:
    repository = MediaRepository(connection)
    first_record = _create_active_seed(repository, first)
    second_record = _create_active_seed(repository, second)
    return repository, first_record, second_record, Reconciler()


def test_ambiguous_reverse_move_does_not_relink_one_of_two_candidates(
    migrated_connection: sqlite3.Connection,
) -> None:
    repository, first, second, reconciler = _two_media_records(
        migrated_connection,
        first=_MediaSeed(relative_path="first.jpg", content_hash="shared", mtime=1.5),
        second=_MediaSeed(relative_path="second.jpg", content_hash="shared", mtime=2.5),
    )

    result = _reconcile_with_files(
        migrated_connection, reconciler, [_hashed_file("new.jpg", "shared")]
    )

    assert result.moved_count == 0
    assert result.new_count == 1
    assert repository.get(first.id).state is MediaState.MISSING  # type: ignore[union-attr]
    assert repository.get(second.id).state is MediaState.MISSING  # type: ignore[union-attr]
    assert repository.get_by_relative_path("new.jpg").id not in {first.id, second.id}  # type: ignore[union-attr]


def test_relinked_record_does_not_hide_later_missing_records(
    migrated_connection: sqlite3.Connection,
) -> None:
    repository, moved, absent, reconciler = _two_media_records(
        migrated_connection,
        first=_MediaSeed(relative_path="a-old.jpg", content_hash="move", mtime=1.5),
        second=_MediaSeed(relative_path="z-absent.jpg", content_hash="absent", mtime=2.5),
    )

    result = _reconcile_with_files(
        migrated_connection, reconciler, [_hashed_file("b-new.jpg", "move")]
    )

    assert result.moved_count == 1
    assert result.missing_count == 1
    assert repository.get(moved.id).relative_path == "b-new.jpg"  # type: ignore[union-attr]
    assert repository.get(absent.id).state is MediaState.MISSING  # type: ignore[union-attr]


def test_failed_reconciliation_rolls_back_earlier_updates(
    migrated_connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = MediaRepository(migrated_connection)
    original = repository.create(
        relative_path="same.jpg",
        content_hash="old",
        size=1,
        mtime=1.5,
        state=MediaState.ACTIVE,
    )
    reconciler = Reconciler()

    def fail_create(*_args: object, **_kwargs: object) -> Media:
        raise RuntimeError("simulated create failure")

    monkeypatch.setattr(reconciler_module.MediaRepository, "create", fail_create)
    with pytest.raises(RuntimeError, match="simulated create failure"):
        reconciler.reconcile(
            migrated_connection,
            reconciler.begin_scan(),
            [_hashed_file("same.jpg", "replacement")],
        )

    assert migrated_connection.in_transaction is False
    assert repository.get(original.id) == original


def test_completed_hash_is_reported_before_the_scan_walk_finishes(
    reconciliation_test_context: ReconciliationTestContext,
) -> None:
    context = reconciliation_test_context
    scanned_file = ScannedFile(
        relative_path="photo.jpg",
        absolute_path=context.root / "photo.jpg",
        size=1,
        mtime=1.5,
    )
    progress: list[tuple[int, int]] = []

    class _ImmediateExecutor:
        def __init__(self, *, thread_name_prefix: str) -> None:
            self.thread_name_prefix = thread_name_prefix

        def __enter__(self) -> _ImmediateExecutor:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def submit(self, _function: object, _path: Path) -> Future[str]:
            future: Future[str] = Future()
            future.set_result("hash")
            return future

    def scan_before_second_yield(_collection: Collection):
        yield scanned_file
        assert progress == [(1, 0)]

    context.monkeypatch.setattr(reconciler_module, "ThreadPoolExecutor", _ImmediateExecutor)
    context.monkeypatch.setattr(reconciler_module, "scan", scan_before_second_yield)
    reconciler = Reconciler()

    result = run_reconciliation(
        reconciler,
        context.collection,
        reconciler.begin_scan(),
        context.connection,
        on_progress=lambda processed, total: progress.append((processed, total)),
    )

    assert result.new_count == 1


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
