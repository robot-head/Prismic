"""Cross-platform advisory locking so only one Prismic instance writes to a
given `.prismic` file at a time.

The lock is held via an OS-level advisory lock on the database file itself,
tied to an open file descriptor's lifetime — not a separate sidecar lock
file. That means it can never go stale: if the process dies, the OS releases
the lock when the descriptor closes, with nothing left on disk to clean up.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from prismic.context import ClosableContext
from prismic.persistence.errors import CollectionLockedError

if sys.platform == "win32":
    import msvcrt

    # Windows byte-range locks are mandatory, not advisory: locking byte 0
    # would block SQLite's own separate handle from reading the file header
    # ("disk I/O error"), even within the same process. Lock a byte range far
    # past any real file content instead — deliberately NOT SQLite's own
    # PENDING_BYTE (1<<30) or its neighboring reserved/shared-lock bytes,
    # which would collide with SQLite's internal locking ("database is
    # locked") — so our lock coordinates instances without ever overlapping
    # a byte SQLite itself reads or locks.
    _LOCK_OFFSET = 1 << 40

    def _lock(fd: int) -> None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class CollectionLock(ClosableContext):
    """An exclusive, non-blocking advisory lock on a collection's database file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        fd = os.open(self._path, os.O_RDWR)
        try:
            _lock(fd)
        except OSError as exc:
            os.close(fd)
            raise CollectionLockedError(self._path) from exc
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        _unlock(self._fd)
        os.close(self._fd)
        self._fd = None

    def close(self) -> None:
        self.release()

    def __enter__(self) -> CollectionLock:
        self.acquire()
        return self
