from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from prismic.persistence.errors import CollectionLockedError
from prismic.persistence.lockfile import CollectionLock
from tests.unit._lockfile_helpers import load_windows_lockfile


@pytest.fixture
def collection_file(tmp_path: Path) -> Path:
    target = tmp_path / "vacation.prismic"
    target.touch()
    return target


def test_acquire_and_release_round_trip(collection_file: Path) -> None:
    lock = CollectionLock(collection_file)

    lock.acquire()
    lock.release()  # should not raise


def test_a_second_lock_on_the_same_file_is_rejected(collection_file: Path) -> None:
    first = CollectionLock(collection_file)
    first.acquire()
    try:
        second = CollectionLock(collection_file)
        with pytest.raises(CollectionLockedError):
            second.acquire()
    finally:
        first.release()


@pytest.mark.parametrize(
    "context_managed",
    [False, True],
    ids=["explicit-release", "context-manager"],
)
def test_release_allows_another_lock_to_be_acquired(
    collection_file: Path, context_managed: bool
) -> None:
    first = CollectionLock(collection_file)
    if context_managed:
        with first:
            pass
    else:
        first.acquire()
        first.release()

    second = CollectionLock(collection_file)
    second.acquire()
    second.release()


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
