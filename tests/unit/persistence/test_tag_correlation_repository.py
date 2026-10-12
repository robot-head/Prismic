import sqlite3

import pytest

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


def _repository_with_correlated_pair(
    connection: sqlite3.Connection, *, media_count: int = 5
) -> tuple[dict[str, int], support.TagCorrelationRepository]:
    ids = _seed_correlated_pair(connection, media_count=media_count)
    return ids, support.TagCorrelationRepository(connection)


def _assign_tag_to_first_media(
    mappings: support.MappingRepository, tag_id: int, media_count: int
) -> None:
    for media_id in range(1, media_count + 1):
        mappings.add(media_id, tag_id)


def _recompute_at_test_floor(repository: support.TagCorrelationRepository) -> None:
    repository.recompute(min_cooccurrence=5)


def _repository_with_prevalent_tags(
    connection: sqlite3.Connection, prevalence_by_tag: dict[str, int]
) -> tuple[dict[str, int], support.TagCorrelationRepository]:
    ids = _seed(
        connection,
        media_count=max(prevalence_by_tag.values()),
        tag_names=list(prevalence_by_tag),
    )
    mappings = support.MappingRepository(connection)
    for name, media_count in prevalence_by_tag.items():
        _assign_tag_to_first_media(mappings, ids[name], media_count)
    repository = support.TagCorrelationRepository(connection)
    _recompute_at_test_floor(repository)
    return ids, repository


def test_recompute_leaves_no_correlations_when_nothing_is_tagged(
    migrated_connection: sqlite3.Connection,
) -> None:
    repository = support.TagCorrelationRepository(migrated_connection)

    repository.recompute()

    assert repository.best_correlations_from([1]) == {}


@pytest.mark.parametrize(
    ("media_count", "expected_included"),
    [(5, True), (4, False)],
    ids=["at-floor", "below-floor"],
)
def test_recompute_applies_the_cooccurrence_floor(
    migrated_connection: sqlite3.Connection,
    media_count: int,
    expected_included: bool,
) -> None:
    ids, repository = _repository_with_correlated_pair(migrated_connection, media_count=media_count)

    _recompute_at_test_floor(repository)

    expected = {ids["kitten"]: 1.0} if expected_included else {}
    assert repository.best_correlations_from([ids["cat"]]) == expected


def test_correlation_ratio_is_directional(migrated_connection: sqlite3.Connection) -> None:
    """5 files have "cat"; only 5 of those also have "pet" -- but "pet" is
    on many more files overall, so cat->pet is 100% while pet->cat is far
    lower. Both directions are tracked, independently."""
    ids, repository = _repository_with_prevalent_tags(migrated_connection, {"cat": 5, "pet": 15})

    cat_to_pet = repository.best_correlations_from([ids["cat"]])
    pet_to_cat = repository.best_correlations_from([ids["pet"]])
    assert cat_to_pet[ids["pet"]] == 1.0
    assert pet_to_cat[ids["cat"]] == 5 / 15


def test_best_correlations_from_multiple_tags_takes_the_strongest_match(
    migrated_connection: sqlite3.Connection,
) -> None:
    # "a" correlates weakly with "shared" (5 of 10), "b" correlates
    # strongly (5 of 5) -- the union should report the stronger ratio.
    ids, repository = _repository_with_prevalent_tags(
        migrated_connection, {"a": 10, "b": 5, "shared": 5}
    )

    result = repository.best_correlations_from([ids["a"], ids["b"]])
    assert result[ids["shared"]] == 1.0  # from b, not a's weaker 0.5


def test_ensure_fresh_recomputes_when_never_computed(
    migrated_connection: sqlite3.Connection,
) -> None:
    ids, repository = _repository_with_correlated_pair(migrated_connection)

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
