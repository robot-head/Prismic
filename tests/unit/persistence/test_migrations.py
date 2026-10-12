from __future__ import annotations

import collections.abc
import pathlib
import sqlite3
from pathlib import Path

import pytest

import prismic.persistence.database as database
import prismic.persistence.migrations as migrations
from prismic.persistence.database import connect
from prismic.persistence.errors import SchemaMigrationError, SchemaTooNewError
from tests.unit._migration_helpers import assert_migration_failure_preserves_version


def _new_database(tmp_path: pathlib.Path) -> tuple[pathlib.Path, sqlite3.Connection]:
    database_path = tmp_path / "vacation.prismic"
    return database_path, database.connect(database_path)


@pytest.fixture
def new_database(
    tmp_path: pathlib.Path,
) -> collections.abc.Iterator[tuple[pathlib.Path, sqlite3.Connection]]:
    database_path, connection = _new_database(tmp_path)
    try:
        yield database_path, connection
    finally:
        connection.close()


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def test_migrate_creates_schema_from_empty(
    new_database: tuple[pathlib.Path, sqlite3.Connection],
) -> None:
    database_path, connection = new_database
    migrations.migrate(connection, database_path)

    tables = _table_names(connection)
    expected = {"media", "tags", "media_tags", "tag_correlations", "tag_correlation_stats"}
    assert expected <= tables
    assert database.schema_version(connection) == len(migrations.MIGRATIONS)
    migrations.migrate(connection, database_path)

    assert database.schema_version(connection) == len(migrations.MIGRATIONS)


def test_migrate_rejects_a_schema_newer_than_this_build_supports(
    new_database: tuple[pathlib.Path, sqlite3.Connection],
) -> None:
    database_path, connection = new_database
    connection.execute(f"PRAGMA user_version = {len(migrations.MIGRATIONS) + 1}")

    with pytest.raises(SchemaTooNewError):
        migrations.migrate(connection, database_path)


def test_a_failed_migration_step_rolls_back_and_leaves_prior_schema_intact(
    new_database: tuple[pathlib.Path, sqlite3.Connection], monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path, connection = new_database
    migrations.migrate(connection, database_path)
    version_before_failure = database.schema_version(connection)

    def _broken_migration(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE half_created (id INTEGER PRIMARY KEY)")
        raise RuntimeError("simulated failure mid-migration")

    monkeypatch.setattr(migrations, "MIGRATIONS", [*migrations.MIGRATIONS, _broken_migration])

    assert_migration_failure_preserves_version(
        connection, database_path, expected_version=version_before_failure
    )
    tables = _table_names(connection)
    assert "half_created" not in tables
    # The schema from before the failed step is still fully usable.
    connection.execute("INSERT INTO tags (name) VALUES ('still works')")


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

        monkeypatch.setattr(
            migrations,
            "MIGRATIONS",
            [
                *migrations.MIGRATIONS,
                broken_migration,
            ],
        )
        with pytest.raises(SchemaMigrationError) as error:
            migrations.migrate(connection, database_path)
        assert f"Migration to schema version {failed_version} failed" in str(error.value)
    finally:
        connection.close()


def test_migration_failure_after_version_two_preserves_that_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "collection.prismic"
    connection = database.connect(database_path)
    try:
        existing_migrations = migrations.MIGRATIONS

        def fail_after_version_two(conn: sqlite3.Connection) -> None:
            raise RuntimeError("stop before the next migration")

        monkeypatch.setattr(
            migrations,
            "MIGRATIONS",
            [existing_migrations[0], existing_migrations[1], fail_after_version_two],
        )
        assert_migration_failure_preserves_version(connection, database_path, expected_version=2)
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'scan_stats'"
            ).fetchone()
            is not None
        )
    finally:
        connection.close()
