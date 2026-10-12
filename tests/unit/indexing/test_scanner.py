from __future__ import annotations

import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from prismic.domain.collection import Collection
from prismic.indexing import scanner
from prismic.indexing.scanner import scan


def _collection(root: Path) -> Collection:
    return Collection(root=root, database_path=root / "test.prismic")


def test_finds_supported_files_recursively(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"1")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.png").write_bytes(b"2")

    found = {f.relative_path for f in scan(_collection(tmp_path))}

    assert found == {"a.jpg", "nested/b.png"}


def test_excludes_unsupported_extensions(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"1")
    (tmp_path / "notes.txt").write_bytes(b"not media")

    found = {f.relative_path for f in scan(_collection(tmp_path))}

    assert found == {"a.jpg"}


def test_excludes_the_collections_own_database_file(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"1")
    collection = _collection(tmp_path)
    collection.database_path.touch()

    found = {f.relative_path for f in scan(collection)}

    assert found == {"a.jpg"}


def test_reports_size_and_mtime(tmp_path: Path) -> None:
    target = tmp_path / "a.jpg"
    target.write_bytes(b"some bytes")

    (found,) = list(scan(_collection(tmp_path)))

    assert found.size == target.stat().st_size
    assert found.mtime == target.stat().st_mtime


def test_continues_past_an_unreadable_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    (good / "a.jpg").write_bytes(b"1")
    (bad / "b.jpg").write_bytes(b"2")

    real_scandir = os.scandir

    def _flaky_scandir(path: str | os.PathLike[str]) -> Iterator[os.DirEntry[str]]:
        if Path(path) == bad:
            raise PermissionError("simulated permission failure")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", _flaky_scandir)

    found = {f.relative_path for f in scan(_collection(tmp_path))}

    assert found == {"good/a.jpg"}


def test_does_not_follow_a_symlinked_directory(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "inside.jpg").write_bytes(b"1")
    (tmp_path / "outside.jpg").write_bytes(b"2")

    link = tmp_path / "link"
    _make_directory_link_or_skip(link, real_dir)

    found = {f.relative_path for f in scan(_collection(tmp_path))}

    assert found == {"outside.jpg", "real/inside.jpg"}
    assert not any(path.startswith("link/") for path in found)


def _make_directory_link_or_skip(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        # Junctions don't require elevated privileges on Windows, unlike
        # symlinks, and are the reparse-point case the overview specifically
        # calls out ("does not follow Windows junctions/reparse points").
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"could not create a junction in this environment: {result.stderr!r}")
    else:
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"could not create a symlink in this environment: {exc}")


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
