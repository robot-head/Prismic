"""Focused regression tests for behavior exposed by mutation testing."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sqlite3
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from prismic.domain.media import MediaState
from prismic.indexing import hashing, scanner
from prismic.indexing.reconciler import HashedFile, Reconciler
from prismic.persistence import lockfile, migrations, preferences
from prismic.persistence.database import connect
from prismic.persistence.errors import SchemaMigrationError
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.tag_repository import TagRepository


def _hashed_file(relative_path: str, content_hash: str) -> HashedFile:
    return HashedFile(relative_path, content_hash, size=1, mtime=10.5)


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
    entry = SimpleNamespace(
        stat=lambda *, follow_symlinks: SimpleNamespace(st_file_attributes=attributes),
        is_symlink=lambda: False,
    )

    assert scanner._is_reparse_point(entry) is expected


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
    monkeypatch.setattr(preferences, "sys", SimpleNamespace(platform=platform))
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


def test_mega_popular_tags_are_empty_when_media_count_is_negative(
    migrated_connection: sqlite3.Connection,
) -> None:
    tags = TagRepository(migrated_connection)
    created = tags.create("travel")

    assert tags.mega_popular_tag_ids(0.1, total_media_count=-1) == frozenset()
    assert tags.get(created.id) == created
