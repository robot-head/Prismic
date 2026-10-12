"""SQLite connection setup for a `.prismic` collection database."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from prismic.persistence.errors import IncompatibleDatabaseError

CURRENT_SCHEMA_VERSION = 3


def connect(database_path: Path) -> sqlite3.Connection:
    """Open a connection to a `.prismic` database file, creating it if absent.

    Transactions are managed explicitly (BEGIN/COMMIT/ROLLBACK) by callers —
    `isolation_level=None` puts the underlying sqlite3 connection in
    autocommit mode so Python doesn't second-guess transaction boundaries.
    The rollback journal (not WAL) is used so that, with no connection open,
    the collection is genuinely just this one file on disk.
    """
    connection = sqlite3.connect(database_path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        # A non-database file (or a corrupt one) doesn't fail at
        # sqlite3.connect() time — that's lazy and only touches the
        # filesystem, not the file's contents. The first real access is
        # where an unreadable/incompatible file actually surfaces, so wrap
        # setup itself and turn it into a domain error rather than letting
        # migration code mistake a `DatabaseError` for an empty schema and
        # silently overwrite it.
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA user_version")
    except sqlite3.DatabaseError as exc:
        connection.close()
        raise IncompatibleDatabaseError(database_path, str(exc)) from exc
    return connection


def schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0])


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Run a unit of work atomically on an autocommit connection."""
    connection.execute("BEGIN")
    try:
        yield
    except Exception:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")
