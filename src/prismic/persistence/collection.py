"""Collection lifecycle: resolving, opening, and creating a `.prismic` file.

Per requirements-amendments.md, a collection's persistent data is a single
SQLite file named `<name>.prismic` living directly in the collection root —
not a hidden directory. Opening accepts either the root directory (its
`*.prismic` file is located) or a direct `.prismic` file path (the OS
file-association launch case), both converging here.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from prismic.context import ClosableContext
from prismic.domain.collection import Collection
from prismic.persistence import database, migrations
from prismic.persistence.errors import MultipleCollectionFilesError
from prismic.persistence.lockfile import CollectionLock

_SUFFIX = ".prismic"


def find_collection_file(directory: Path) -> Path | None:
    """The single `*.prismic` file directly in `directory`, or None.

    More than one is an error surfaced to the user, not silently resolved.
    """
    matches = sorted(directory.glob(f"*{_SUFFIX}"))
    if len(matches) > 1:
        raise MultipleCollectionFilesError(directory, matches)
    return matches[0] if matches else None


def resolve_database_path(path: Path) -> Path:
    """The `.prismic` file for `path`, whether a directory or a direct file.

    For a directory with no existing collection file yet, derives one named
    after the directory itself.
    """
    if path.is_file():
        return path
    existing = find_collection_file(path)
    if existing is not None:
        return existing
    return path / f"{path.name}{_SUFFIX}"


class OpenCollection(ClosableContext):
    """A live, locked connection to an opened collection.

    Callers must `close()` it (or use it as a context manager) to release
    both the database connection and the collection lock.
    """

    def __init__(
        self, collection: Collection, connection: sqlite3.Connection, lock: CollectionLock
    ) -> None:
        self.collection = collection
        self.connection = connection
        self._lock = lock

    def close(self) -> None:
        self.connection.close()
        self._lock.release()


def open_collection(path: str | os.PathLike[str]) -> OpenCollection:
    """Open (or create) the collection at `path`.

    `path` may be a collection root directory or a direct `.prismic` file
    path — and a plain string or any path-like object, not just a `Path`,
    since this is the entry point argv-driven launches (and callers in
    other processes/languages) hand a path to. On any failure — lock
    contention, an unreadable/incompatible database, or a failed migration
    — no partial session is left behind: the lock and connection (whichever
    were acquired) are released and the error propagates.
    """
    path = Path(path)
    root = path.parent if path.is_file() else path
    database_path = resolve_database_path(path)

    if not database_path.exists():
        database_path.touch()

    lock = CollectionLock(database_path)
    lock.acquire()

    connection: sqlite3.Connection | None = None
    try:
        connection = database.connect(database_path)
        migrations.migrate(connection, database_path)
    except Exception:
        if connection is not None:
            connection.close()
        lock.release()
        raise

    return OpenCollection(
        collection=Collection(root=root, database_path=database_path),
        connection=connection,
        lock=lock,
    )
