"""Focused regression tests for behavior exposed by mutation testing."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
import stat
import sys
from concurrent.futures import Future
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
from prismic.persistence import lockfile, migrations, preferences
from prismic.persistence.database import connect
from prismic.persistence.errors import SchemaMigrationError
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.tag_repository import TagRepository


def _hashed_file(relative_path: str, content_hash: str) -> HashedFile:
    return HashedFile(relative_path, content_hash, size=1, mtime=10.5)


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


def test_cached_hash_is_rejected_for_non_active_records() -> None:
    scanned = ScannedFile("photo.jpg", Path("photo.jpg"), size=1024, mtime=10.5)
    recorded = Media(1, "photo.jpg", "old", 1024, 10.5, MediaState.MISSING)

    assert _recorded_hash_if_unchanged(scanned, recorded, now=100.0) is None


def test_cached_hash_size_comparison_uses_value_equality() -> None:
    recorded_size = int("1024")
    scanned_size = int("10" + "24")
    scanned = ScannedFile("photo.jpg", Path("photo.jpg"), scanned_size, 10.5)
    recorded = Media(1, "photo.jpg", "same", recorded_size, 10.5, MediaState.ACTIVE)

    assert recorded_size == scanned_size
    assert recorded_size is not scanned_size
    assert _recorded_hash_if_unchanged(scanned, recorded, now=100.0) == "same"


def test_cached_hash_rejects_a_smaller_replacement_file() -> None:
    scanned = ScannedFile("photo.jpg", Path("photo.jpg"), size=512, mtime=10.5)
    recorded = Media(1, "photo.jpg", "old", 1024, 10.5, MediaState.ACTIVE)

    assert _recorded_hash_if_unchanged(scanned, recorded, now=100.0) is None


def test_cached_hash_rejects_an_older_replacement_mtime() -> None:
    scanned = ScannedFile("photo.jpg", Path("photo.jpg"), size=1024, mtime=10.5)
    recorded = Media(1, "photo.jpg", "old", 1024, 10.75, MediaState.ACTIVE)

    assert _recorded_hash_if_unchanged(scanned, recorded, now=100.0) is None


def test_recent_mtime_cutoff_is_strict() -> None:
    scanned = ScannedFile("photo.jpg", Path("photo.jpg"), size=1024, mtime=98.125)
    recorded = Media(1, "photo.jpg", "same", 1024, 98.125, MediaState.ACTIVE)

    assert _recorded_hash_if_unchanged(scanned, recorded, now=100.125) == "same"


def test_reconciliation_result_count_defaults_are_zero() -> None:
    result = ReconciliationResult(applied=False)

    assert (
        result.new_count,
        result.unchanged_count,
        result.changed_count,
        result.moved_count,
        result.missing_count,
    ) == (0, 0, 0, 0, 0)


def test_reconciliation_reports_each_outcome_count(
    migrated_connection: sqlite3.Connection,
) -> None:
    repository = MediaRepository(migrated_connection)
    unchanged = repository.create("unchanged.jpg", "same", 1, 1.5, MediaState.ACTIVE)
    changed = repository.create("changed.jpg", "old", 1, 2.5, MediaState.ACTIVE)
    moved = repository.create("old-location.jpg", "move", 1, 3.5, MediaState.ACTIVE)
    missing = repository.create("absent.jpg", "absent", 1, 4.5, MediaState.ACTIVE)
    reconciler = Reconciler()
    generation = reconciler.begin_scan()

    result = reconciler.reconcile(
        migrated_connection,
        generation,
        [
            _hashed_file("unchanged.jpg", "same"),
            _hashed_file("changed.jpg", "replacement"),
            _hashed_file("new.jpg", "new"),
            _hashed_file("new-location.jpg", "move"),
        ],
    )

    assert result.applied
    assert (
        result.new_count,
        result.unchanged_count,
        result.changed_count,
        result.moved_count,
        result.missing_count,
    ) == (1, 1, 1, 1, 1)
    after = repository.list_all()
    assert repository.get(unchanged.id) == unchanged
    assert repository.get(changed.id).state is MediaState.MISSING  # type: ignore[union-attr]
    assert repository.get(missing.id).state is MediaState.MISSING  # type: ignore[union-attr]
    assert repository.get(moved.id).relative_path == "new-location.jpg"  # type: ignore[union-attr]
    assert len(after) == 6


def test_unreadable_path_does_not_stop_later_missing_paths_from_being_marked(
    migrated_connection: sqlite3.Connection,
) -> None:
    repository = MediaRepository(migrated_connection)
    unreadable = repository.create("a-unreadable.jpg", "a", 1, 1.5, MediaState.ACTIVE)
    absent = repository.create("b-absent.jpg", "b", 1, 2.5, MediaState.ACTIVE)
    reconciler = Reconciler()
    generation = reconciler.begin_scan()

    result = reconciler.reconcile(
        migrated_connection,
        generation,
        [],
        unreadable_paths=frozenset({"a-unreadable.jpg"}),
    )

    assert result.missing_count == 1
    assert repository.get(unreadable.id) == unreadable
    assert repository.get(absent.id).state is MediaState.MISSING  # type: ignore[union-attr]


def test_ambiguous_reverse_move_does_not_relink_one_of_two_candidates(
    migrated_connection: sqlite3.Connection,
) -> None:
    repository = MediaRepository(migrated_connection)
    first = repository.create("first.jpg", "shared", 1, 1.5, MediaState.ACTIVE)
    second = repository.create("second.jpg", "shared", 1, 2.5, MediaState.ACTIVE)
    reconciler = Reconciler()

    result = reconciler.reconcile(
        migrated_connection,
        reconciler.begin_scan(),
        [_hashed_file("new.jpg", "shared")],
    )

    assert result.moved_count == 0
    assert result.new_count == 1
    assert repository.get(first.id).state is MediaState.MISSING  # type: ignore[union-attr]
    assert repository.get(second.id).state is MediaState.MISSING  # type: ignore[union-attr]
    assert repository.get_by_relative_path("new.jpg").id not in {first.id, second.id}  # type: ignore[union-attr]


def test_relinked_record_does_not_hide_later_missing_records(
    migrated_connection: sqlite3.Connection,
) -> None:
    repository = MediaRepository(migrated_connection)
    moved = repository.create("a-old.jpg", "move", 1, 1.5, MediaState.ACTIVE)
    absent = repository.create("z-absent.jpg", "absent", 1, 2.5, MediaState.ACTIVE)
    reconciler = Reconciler()

    result = reconciler.reconcile(
        migrated_connection,
        reconciler.begin_scan(),
        [_hashed_file("b-new.jpg", "move")],
    )

    assert result.moved_count == 1
    assert result.missing_count == 1
    assert repository.get(moved.id).relative_path == "b-new.jpg"  # type: ignore[union-attr]
    assert repository.get(absent.id).state is MediaState.MISSING  # type: ignore[union-attr]


def test_failed_reconciliation_rolls_back_earlier_updates(
    migrated_connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = MediaRepository(migrated_connection)
    original = repository.create("same.jpg", "old", 1, 1.5, MediaState.ACTIVE)
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
    tmp_path: Path,
    migrated_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection = Collection(tmp_path, tmp_path / "collection.prismic")
    scanned_file = ScannedFile("photo.jpg", tmp_path / "photo.jpg", size=1, mtime=1.5)
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

    monkeypatch.setattr(reconciler_module, "ThreadPoolExecutor", _ImmediateExecutor)
    monkeypatch.setattr(reconciler_module, "scan", scan_before_second_yield)
    reconciler = Reconciler()

    result = run_reconciliation(
        reconciler,
        collection,
        reconciler.begin_scan(),
        migrated_connection,
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

    found = list(scanner.scan(Collection(tmp_path, tmp_path / "collection.prismic")))

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
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    spec = importlib.util.spec_from_file_location(
        "_test_prismic_windows_lockfile", lockfile.__file__
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

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
