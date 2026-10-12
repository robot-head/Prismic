"""Regression tests for default tag-correlation and schema settings."""

from __future__ import annotations

import sqlite3

import pytest

from prismic.persistence import database, migrations
from tests.unit import _tag_correlation_support as support


def _seed_correlated_pair(connection: sqlite3.Connection, count: int) -> dict[str, int]:
    media = support.MediaRepository(connection)
    tags = support.TagRepository(connection)
    tag_ids = {name: tags.create(name).id for name in ("first", "second")}
    mappings = support.MappingRepository(connection)
    for index in range(count):
        item = media.create(f"{index}.jpg", f"hash-{index}", 1, 0.0, support.MediaState.ACTIVE)
        mappings.add(item.id, tag_ids["first"])
        mappings.add(item.id, tag_ids["second"])
    return tag_ids


def test_default_cooccurrence_floor_drops_pairs_seen_on_four_items(
    migrated_connection: sqlite3.Connection,
) -> None:
    tag_ids = _seed_correlated_pair(migrated_connection, count=4)
    repository = support.TagCorrelationRepository(migrated_connection)

    repository.recompute()

    assert repository.best_correlations_from([tag_ids["first"]]) == {}


def test_default_throttle_recomputes_at_the_sixty_second_boundary(
    migrated_connection: sqlite3.Connection,
) -> None:
    ticks = iter([100.0, 160.0, 160.0]).__next__
    repository = support.TagCorrelationRepository(migrated_connection, clock=ticks)
    repository.recompute()
    tag_ids = _seed_correlated_pair(migrated_connection, count=5)

    repository.ensure_fresh()

    assert repository.best_correlations_from([tag_ids["first"]]) == {tag_ids["second"]: 1.0}


def test_current_schema_version_constant_matches_the_migrations() -> None:
    assert database.CURRENT_SCHEMA_VERSION == len(migrations.MIGRATIONS)


def test_recompute_rolls_back_if_the_timestamp_clock_fails(
    migrated_connection: sqlite3.Connection,
) -> None:
    tag_ids = _seed_correlated_pair(migrated_connection, count=4)
    repository = support.TagCorrelationRepository(migrated_connection, clock=lambda: 100.0)
    repository.recompute()
    new_media = support.MediaRepository(migrated_connection).create(
        "4.jpg", "hash-4", 1, 0.0, support.MediaState.ACTIVE
    )
    mappings = support.MappingRepository(migrated_connection)
    mappings.add(new_media.id, tag_ids["first"])
    mappings.add(new_media.id, tag_ids["second"])

    def fail_clock() -> float:
        raise RuntimeError("clock unavailable")

    failing_repository = support.TagCorrelationRepository(migrated_connection, clock=fail_clock)
    with pytest.raises(RuntimeError, match="clock unavailable"):
        failing_repository.recompute()

    assert migrated_connection.in_transaction is False
    assert repository.best_correlations_from([tag_ids["first"]]) == {}
    assert repository.last_computed_at() == 100.0
