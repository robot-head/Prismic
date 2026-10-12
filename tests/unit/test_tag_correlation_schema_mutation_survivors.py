"""Regression tests for default tag-correlation and schema settings."""

from __future__ import annotations

import sqlite3

from prismic.domain.media import MediaState
from prismic.persistence import database
from prismic.persistence.repositories.mapping_repository import MappingRepository
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.tag_correlation_repository import TagCorrelationRepository
from prismic.persistence.repositories.tag_repository import TagRepository


def _seed_correlated_pair(connection: sqlite3.Connection, count: int) -> dict[str, int]:
    media = MediaRepository(connection)
    tags = TagRepository(connection)
    tag_ids = {name: tags.create(name).id for name in ("first", "second")}
    mappings = MappingRepository(connection)
    for index in range(count):
        item = media.create(f"{index}.jpg", f"hash-{index}", 1, 0.0, MediaState.ACTIVE)
        mappings.add(item.id, tag_ids["first"])
        mappings.add(item.id, tag_ids["second"])
    return tag_ids


def test_default_cooccurrence_floor_drops_pairs_seen_on_four_items(
    migrated_connection: sqlite3.Connection,
) -> None:
    tag_ids = _seed_correlated_pair(migrated_connection, count=4)
    repository = TagCorrelationRepository(migrated_connection)

    repository.recompute()

    assert repository.best_correlations_from([tag_ids["first"]]) == {}


def test_default_throttle_recomputes_at_the_sixty_second_boundary(
    migrated_connection: sqlite3.Connection,
) -> None:
    ticks = iter([100.0, 160.0, 160.0]).__next__
    repository = TagCorrelationRepository(migrated_connection, clock=ticks)
    repository.recompute()
    tag_ids = _seed_correlated_pair(migrated_connection, count=5)

    repository.ensure_fresh()

    assert repository.best_correlations_from([tag_ids["first"]]) == {tag_ids["second"]: 1.0}


def test_current_schema_version_constant_is_two() -> None:
    assert database.CURRENT_SCHEMA_VERSION == 2
