import sqlite3

from tests.unit import _tag_correlation_support as support


def _seed(
    connection: sqlite3.Connection, *, media_count: int, tag_names: list[str]
) -> dict[str, int]:
    media_repo = support.MediaRepository(connection)
    tag_repo = support.TagRepository(connection)
    for i in range(media_count):
        media_repo.create(f"{i}.jpg", f"hash{i}", 1, 0.0, support.MediaState.ACTIVE)
    return {name: tag_repo.create(name).id for name in tag_names}


def _seed_correlated_pair(
    connection: sqlite3.Connection, *, media_count: int = 5
) -> dict[str, int]:
    ids = _seed(connection, media_count=media_count, tag_names=["cat", "kitten"])
    mappings = support.MappingRepository(connection)
    for media_id in range(1, media_count + 1):
        mappings.add(media_id, ids["cat"])
        mappings.add(media_id, ids["kitten"])
    return ids


def test_recompute_leaves_no_correlations_when_nothing_is_tagged(
    migrated_connection: sqlite3.Connection,
) -> None:
    repository = support.TagCorrelationRepository(migrated_connection)

    repository.recompute()

    assert repository.best_correlations_from([1]) == {}


def test_recompute_tracks_a_pair_meeting_the_cooccurrence_floor(
    migrated_connection: sqlite3.Connection,
) -> None:
    ids = _seed_correlated_pair(migrated_connection)
    repository = support.TagCorrelationRepository(migrated_connection)

    repository.recompute(min_cooccurrence=5)

    correlations = repository.best_correlations_from([ids["cat"]])
    assert correlations == {ids["kitten"]: 1.0}


def test_recompute_drops_a_pair_below_the_cooccurrence_floor(
    migrated_connection: sqlite3.Connection,
) -> None:
    ids = _seed_correlated_pair(migrated_connection, media_count=4)
    repository = support.TagCorrelationRepository(migrated_connection)

    repository.recompute(min_cooccurrence=5)

    assert repository.best_correlations_from([ids["cat"]]) == {}


def test_correlation_ratio_is_directional(migrated_connection: sqlite3.Connection) -> None:
    """5 files have "cat"; only 5 of those also have "pet" -- but "pet" is
    on many more files overall, so cat->pet is 100% while pet->cat is far
    lower. Both directions are tracked, independently."""
    ids = _seed(migrated_connection, media_count=15, tag_names=["cat", "pet"])
    mappings = support.MappingRepository(migrated_connection)
    for media_id in range(1, 16):
        mappings.add(media_id, ids["pet"])
    for media_id in range(1, 6):
        mappings.add(media_id, ids["cat"])
    repository = support.TagCorrelationRepository(migrated_connection)

    repository.recompute(min_cooccurrence=5)

    cat_to_pet = repository.best_correlations_from([ids["cat"]])
    pet_to_cat = repository.best_correlations_from([ids["pet"]])
    assert cat_to_pet[ids["pet"]] == 1.0
    assert pet_to_cat[ids["cat"]] == 5 / 15


def test_best_correlations_from_multiple_tags_takes_the_strongest_match(
    migrated_connection: sqlite3.Connection,
) -> None:
    ids = _seed(migrated_connection, media_count=10, tag_names=["a", "b", "shared"])
    mappings = support.MappingRepository(migrated_connection)
    # "a" correlates weakly with "shared" (5 of 10), "b" correlates
    # strongly (5 of 5) -- the union should report the stronger ratio.
    for media_id in range(1, 11):
        mappings.add(media_id, ids["a"])
    for media_id in range(1, 6):
        mappings.add(media_id, ids["b"])
    for media_id in range(1, 6):
        mappings.add(media_id, ids["shared"])
    repository = support.TagCorrelationRepository(migrated_connection)

    repository.recompute(min_cooccurrence=5)

    result = repository.best_correlations_from([ids["a"], ids["b"]])
    assert result[ids["shared"]] == 1.0  # from b, not a's weaker 0.5


def test_ensure_fresh_recomputes_when_never_computed(
    migrated_connection: sqlite3.Connection,
) -> None:
    ids = _seed_correlated_pair(migrated_connection)
    repository = support.TagCorrelationRepository(migrated_connection)

    repository.ensure_fresh(min_cooccurrence=5)

    assert repository.best_correlations_from([ids["cat"]]) == {ids["kitten"]: 1.0}
    assert repository.last_computed_at() is not None


def test_ensure_fresh_skips_recompute_within_the_throttle_window(
    migrated_connection: sqlite3.Connection,
) -> None:
    clock = iter([100.0, 110.0]).__next__  # 10s apart, well under the throttle
    repository = support.TagCorrelationRepository(migrated_connection, clock=clock)
    repository.recompute()  # consumes clock() == 100.0, sets computed_at

    ids = _seed_correlated_pair(migrated_connection)

    repository.ensure_fresh(min_cooccurrence=5, max_age_seconds=60.0)  # consumes 110.0, still < 60s

    # The seeded mapping happened *after* the one recompute -- if
    # ensure_fresh had recomputed again, it would show up.
    assert repository.best_correlations_from([ids["cat"]]) == {}


def test_ensure_fresh_recomputes_once_the_throttle_window_passes(
    migrated_connection: sqlite3.Connection,
) -> None:
    # construction's recompute() consumes one tick, ensure_fresh's own
    # staleness check consumes a second (100s later, past a 60s throttle),
    # and the recompute() that triggers consumes a third.
    clock = iter([100.0, 200.0, 200.0]).__next__
    repository = support.TagCorrelationRepository(migrated_connection, clock=clock)
    repository.recompute()

    ids = _seed(migrated_connection, media_count=5, tag_names=["cat", "kitten"])
    mappings = support.MappingRepository(migrated_connection)
    for media_id in range(1, 6):
        mappings.add(media_id, ids["cat"])
        mappings.add(media_id, ids["kitten"])

    repository.ensure_fresh(min_cooccurrence=5, max_age_seconds=60.0)

    assert repository.best_correlations_from([ids["cat"]]) == {ids["kitten"]: 1.0}
