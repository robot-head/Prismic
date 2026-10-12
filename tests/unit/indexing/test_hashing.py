from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from prismic.indexing import hashing
from prismic.indexing.hashing import hash_file


def test_identical_content_produces_the_same_hash(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    first.write_bytes(b"identical bytes")
    second.write_bytes(b"identical bytes")

    assert hash_file(first) == hash_file(second)


def test_different_content_produces_a_different_hash(tmp_path: Path) -> None:
    first = tmp_path / "a.jpg"
    second = tmp_path / "b.jpg"
    first.write_bytes(b"some content")
    second.write_bytes(b"different content")

    assert hash_file(first) != hash_file(second)


def test_hashes_content_larger_than_one_chunk(tmp_path: Path) -> None:
    large_file = tmp_path / "large.jpg"
    large_file.write_bytes(b"x" * (2 * (1 << 20) + 17))

    # Should not raise, and should be stable across repeated hashing.
    assert hash_file(large_file) == hash_file(large_file)


def test_an_unreadable_path_raises_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        hash_file(tmp_path)  # a directory can't be opened for reading as a file


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
