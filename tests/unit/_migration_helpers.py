"""Shared rollback assertions for migration contract tests."""

import pathlib
import sqlite3

import pytest

from prismic.persistence import database, migrations
from prismic.persistence.errors import SchemaMigrationError


def assert_migration_failure_preserves_version(
    connection: sqlite3.Connection,
    database_path: pathlib.Path,
    *,
    expected_version: int,
) -> None:
    with pytest.raises(SchemaMigrationError):
        migrations.migrate(connection, database_path)

    assert database.schema_version(connection) == expected_version
