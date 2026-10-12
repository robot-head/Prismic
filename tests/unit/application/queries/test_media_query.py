import pytest

from prismic.application.queries.media_query import eligible_media
from prismic.domain.media import MediaState
from prismic.persistence.repositories.mapping_repository import MappingRepository
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.tag_repository import TagRepository


def _add_media(
    media: MediaRepository, relative_path: str, state: MediaState = MediaState.ACTIVE
) -> int:
    return media.create(
        relative_path=relative_path, content_hash=relative_path, size=1, mtime=1.0, state=state
    ).id


def test_zero_tags_returns_all_active_media_in_path_order(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    _add_media(media, "z.jpg")
    _add_media(media, "a.jpg")
    _add_media(media, "missing.jpg", state=MediaState.MISSING)

    result = eligible_media(media, mappings, [])

    assert [m.relative_path for m in result] == ["a.jpg", "z.jpg"]


@pytest.mark.parametrize(
    ("second_tag", "expected_paths"),
    [(None, ["beach.jpg"]), ("summer", ["beach.jpg"]), ("work", [])],
    ids=["one-tag", "multiple-tag-intersection", "empty-intersection"],
)
def test_tag_filters_return_only_media_matching_every_selected_tag(
    media: MediaRepository,
    mappings: MappingRepository,
    tags: TagRepository,
    second_tag: str | None,
    expected_paths: list[str],
) -> None:
    beach = _add_media(media, "beach.jpg")
    vacation = tags.create("vacation")
    mappings.add(beach, vacation.id)
    query_ids = [vacation.id]

    if second_tag is None:
        _add_media(media, "unrelated.jpg")
    else:
        mountain = _add_media(media, "mountain.jpg")
        other = tags.create(second_tag)
        query_ids.append(other.id)
        if second_tag == "summer":
            mappings.add(beach, other.id)
            mappings.add(mountain, vacation.id)
        else:
            mappings.add(mountain, other.id)

    result = eligible_media(media, mappings, query_ids)

    assert [item.relative_path for item in result] == expected_paths


def test_missing_media_is_never_eligible_even_when_tagged(
    media: MediaRepository, mappings: MappingRepository, tags: TagRepository
) -> None:
    gone = _add_media(media, "gone.jpg", state=MediaState.MISSING)
    vacation = tags.create("vacation")
    mappings.add(gone, vacation.id)

    assert eligible_media(media, mappings, [vacation.id]) == []
    assert eligible_media(media, mappings, []) == []


def test_ordering_is_deterministic_by_normalized_relative_path(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    _add_media(media, "b/2.jpg")
    _add_media(media, "a/1.jpg")
    _add_media(media, "b/1.jpg")

    result = eligible_media(media, mappings, [])

    assert [m.relative_path for m in result] == ["a/1.jpg", "b/1.jpg", "b/2.jpg"]


@pytest.mark.slow
def test_scales_acceptably_on_a_large_result_set(
    media: MediaRepository, mappings: MappingRepository
) -> None:
    """A rough smoke-test benchmark, not a rigorous perf target — flags a
    gross regression (e.g. an accidental N+1 query) long before it'd need a
    real number backed by production-scale data."""
    import time

    for index in range(5000):
        _add_media(media, f"photo_{index:05d}.jpg")

    start = time.perf_counter()
    result = eligible_media(media, mappings, [])
    elapsed = time.perf_counter() - start

    assert len(result) == 5000
    assert result[0].relative_path == "photo_00000.jpg"
    assert result[-1].relative_path == "photo_04999.jpg"
    assert elapsed < 2.0
