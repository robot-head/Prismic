"""Focused regression tests for behavior exposed by mutation testing."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from prismic.domain.collection import Collection
from prismic.domain.media import Media, MediaState
from prismic.indexing import hashing, scanner
from prismic.indexing import reconciler as reconciler_module
from prismic.indexing.reconciler import (
    HashedFile,
    Reconciler,
    ReconciliationResult,
    _recorded_hash_if_unchanged,
    run_reconciliation,
)
from prismic.indexing.scanner import ScannedFile
from prismic.persistence import migrations, preferences
from prismic.persistence.database import connect
from prismic.persistence.errors import SchemaMigrationError
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.tag_repository import TagRepository
from tests._reconciliation_test_context import ReconciliationTestContext
from tests.unit._lockfile_helpers import load_windows_lockfile


@dataclass(frozen=True, slots=True)
class _MediaSeed:
    relative_path: str
    content_hash: str
    mtime: float


def _hashed_file(relative_path: str, content_hash: str) -> HashedFile:
    return HashedFile(relative_path=relative_path, content_hash=content_hash, size=1, mtime=10.5)


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


def _create_active_seed(repository: MediaRepository, seed: _MediaSeed) -> Media:
    return repository.create(
        relative_path=seed.relative_path,
        content_hash=seed.content_hash,
        size=1,
        mtime=seed.mtime,
        state=MediaState.ACTIVE,
    )


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


def _outcome_counts(result: ReconciliationResult) -> tuple[int, int, int, int, int]:
    return (
        result.new_count,
        result.unchanged_count,
        result.changed_count,
        result.moved_count,
        result.missing_count,
    )


class _DirectoryEntry:
    def __init__(self, path: Path, *, fail_is_dir: bool = False, fail_stat: bool = False) -> None:
        self.path = str(path)
        self._fail_is_dir = fail_is_dir
        self._fail_stat = fail_stat

    def is_symlink(self) -> bool:
        return False

    def is_dir(self, *, follow_symlinks: bool) -> bool:
        if self._fail_is_dir:
            raise OSError("directory entry disappeared")
        return False

    def is_file(self, *, follow_symlinks: bool) -> bool:
        return True

    def stat(self, *, follow_symlinks: bool) -> SimpleNamespace:
        if self._fail_stat:
            raise OSError("file entry disappeared")
        return SimpleNamespace(st_size=1, st_mtime=1.5)


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


def test_reconciliation_result_count_defaults_are_zero() -> None:
    result = ReconciliationResult(applied=False)

    assert _outcome_counts(result) == (0, 0, 0, 0, 0)


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


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        (stat.FILE_ATTRIBUTE_REPARSE_POINT, True),
        (0x20, False),  # ordinary attribute bits must not look like a reparse point
    ],
)
def test_windows_reparse_point_detection_checks_the_attribute_bit(
    monkeypatch: pytest.MonkeyPatch, attributes: int, expected: bool
) -> None:
    # A distinct but equal string ensures the platform check uses value
    # equality, as sys.platform is a string value rather than a sentinel.
    platform = bytearray(b"win32").decode("ascii")
    monkeypatch.setattr(scanner, "sys", SimpleNamespace(platform=platform))
    follow_symlink_values: list[bool] = []

    def stat(*, follow_symlinks: bool) -> SimpleNamespace:
        follow_symlink_values.append(follow_symlinks)
        return SimpleNamespace(st_file_attributes=attributes)

    entry = SimpleNamespace(
        stat=stat,
        is_symlink=lambda: False,
    )

    assert scanner._is_reparse_point(entry) is expected
    assert follow_symlink_values == [False]


def test_non_windows_platforms_use_symlink_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = bytearray(b"z-other").decode("ascii")
    monkeypatch.setattr(scanner, "sys", SimpleNamespace(platform=platform))
    entry = SimpleNamespace(
        stat=lambda **_kwargs: SimpleNamespace(st_file_attributes=0),
        is_symlink=lambda: True,
    )

    assert scanner._is_reparse_point(entry) is True


def test_windows_reparse_stat_error_fails_open_as_non_reparse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scanner, "sys", SimpleNamespace(platform="win32"))

    def fail_stat(*, follow_symlinks: bool) -> SimpleNamespace:
        raise OSError("cannot read attributes")

    entry = SimpleNamespace(stat=fail_stat, is_symlink=lambda: False)

    assert scanner._is_reparse_point(entry) is False


@pytest.mark.parametrize("fail_is_dir", [True, False])
def test_scan_continues_past_an_unreadable_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_is_dir: bool
) -> None:
    broken = _DirectoryEntry(
        tmp_path / "broken.jpg", fail_is_dir=fail_is_dir, fail_stat=not fail_is_dir
    )
    later = _DirectoryEntry(tmp_path / "later.jpg")
    monkeypatch.setattr(scanner, "os", SimpleNamespace(scandir=lambda _path: [broken, later]))

    found = list(
        scanner.scan(Collection(root=tmp_path, database_path=tmp_path / "collection.prismic"))
    )

    assert [item.relative_path for item in found] == ["later.jpg"]


def test_hashing_reads_files_in_megabyte_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"x" * ((1 << 20) + 17)
    target = tmp_path / "large.bin"
    target.write_bytes(payload)
    real_open = Path.open
    requested_sizes: list[int] = []

    class RecordingHandle:
        def __init__(self, handle: object) -> None:
            self._handle = handle

        def __enter__(self) -> RecordingHandle:
            self._handle.__enter__()  # type: ignore[attr-defined]
            return self

        def __exit__(self, *args: object) -> object:
            return self._handle.__exit__(*args)  # type: ignore[attr-defined]

        def read(self, size: int) -> bytes:
            requested_sizes.append(size)
            return self._handle.read(size)  # type: ignore[attr-defined,no-any-return]

    def recording_open(path: Path, *args: object, **kwargs: object) -> RecordingHandle:
        return RecordingHandle(real_open(path, *args, **kwargs))

    monkeypatch.setattr(Path, "open", recording_open)

    assert hashing.hash_file(target) == hashlib.blake2b(payload).hexdigest()
    assert requested_sizes == [1 << 20, 1 << 20, 1 << 20]


def test_windows_collection_lock_uses_a_byte_outside_sqlite_lock_ranges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, int, int]] = []
    fake_msvcrt = SimpleNamespace(
        LK_NBLCK=1,
        LK_UNLCK=2,
        locking=lambda fd, mode, count: calls.append((fd, mode, count)),
    )
    module = load_windows_lockfile(monkeypatch, "win32", fake_msvcrt)

    target = tmp_path / "database.prismic"
    target.touch()
    fd = os.open(target, os.O_RDWR)
    try:
        module._lock(fd)
        module._unlock(fd)
    finally:
        os.close(fd)

    assert module._LOCK_OFFSET == 1 << 40
    assert calls == [(fd, fake_msvcrt.LK_NBLCK, 1), (fd, fake_msvcrt.LK_UNLCK, 1)]


@pytest.mark.parametrize(
    ("platform", "environment", "expected_parts"),
    [
        ("win32", {"APPDATA": "/profile/roaming"}, ("/profile/roaming", "Prismic")),
        ("win32", {}, ("home", "AppData", "Roaming", "Prismic")),
        (
            "darwin",
            {},
            ("home", "Library", "Application Support", "Prismic"),
        ),
        ("linux", {"XDG_CONFIG_HOME": "/config"}, ("/config", "prismic")),
        ("linux", {}, ("home", ".config", "prismic")),
        ("z-other", {"XDG_CONFIG_HOME": "/fallback"}, ("/fallback", "prismic")),
    ],
)
def test_preferences_directory_uses_platform_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    environment: dict[str, str],
    expected_parts: tuple[str, ...],
) -> None:
    home = tmp_path / "home"
    distinct_platform = bytearray(platform.encode()).decode("ascii")
    monkeypatch.setattr(preferences, "sys", SimpleNamespace(platform=distinct_platform))
    monkeypatch.setattr(preferences.Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    actual = preferences.preferences_directory()
    expected = (
        home.joinpath(*expected_parts[1:])
        if expected_parts[0] == "home"
        else Path(expected_parts[0]).joinpath(*expected_parts[1:])
    )

    assert actual == expected


def test_migration_failure_names_the_version_that_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "collection.prismic"
    connection = connect(database_path)
    try:
        migrations.migrate(connection, database_path)
        failed_version = len(migrations.MIGRATIONS) + 1

        def broken_migration(conn: sqlite3.Connection) -> None:
            raise RuntimeError("forced migration failure")

        monkeypatch.setattr(migrations, "MIGRATIONS", [*migrations.MIGRATIONS, broken_migration])

        with pytest.raises(SchemaMigrationError) as error:
            migrations.migrate(connection, database_path)

        assert f"Migration to schema version {failed_version} failed" in str(error.value)
    finally:
        connection.close()


def test_preferences_save_sorted_json_with_two_space_indentation(tmp_path: Path) -> None:
    store = preferences.PreferencesStore(tmp_path / "preferences.json")

    store.save({"z": 1, "a": 2})

    assert store.path.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "z": 1\n}'


def test_mega_popular_tags_are_empty_when_media_count_is_negative(
    migrated_connection: sqlite3.Connection,
) -> None:
    tags = TagRepository(migrated_connection)
    created = tags.create("travel")

    assert tags.mega_popular_tag_ids(0.1, total_media_count=-1) == frozenset()
    assert tags.get(created.id) == created
