import sqlite3

import pytest

from prismic.persistence.errors import DuplicateMappingError
from prismic.persistence.repositories import mapping_repository, media_repository, tag_repository
from tests.unit._media_support import add_active_media

_Repositories = tuple[
    mapping_repository.MappingRepository,
    media_repository.MediaRepository,
    tag_repository.TagRepository,
]


@pytest.fixture
def repositories(
    migrated_connection: sqlite3.Connection,
) -> _Repositories:
    return (
        mapping_repository.MappingRepository(migrated_connection),
        media_repository.MediaRepository(migrated_connection),
        tag_repository.TagRepository(migrated_connection),
    )


def _mapping_setup(
    repositories: _Repositories,
    *,
    added: bool = False,
) -> tuple[mapping_repository.MappingRepository, int, int]:
    mappings, media_repo, tag_repo = repositories
    media_id = add_active_media(media_repo, "a.jpg")
    tag_id = tag_repo.create("vacation").id
    if added:
        mappings.add(media_id, tag_id)
    return mappings, media_id, tag_id


def test_add_and_tags_for_media(
    repositories: _Repositories,
) -> None:
    mappings, media_id, tag_id = _mapping_setup(repositories)

    mappings.add(media_id, tag_id)

    assert [t.name for t in mappings.tags_for_media(media_id)] == ["vacation"]


@pytest.mark.parametrize(
    "operation",
    ["add_again", "remove"],
    ids=["duplicate-add", "remove-existing"],
)
def test_existing_mapping_operations(
    repositories: _Repositories, operation: str
) -> None:
    mappings, media_id, tag_id = _mapping_setup(repositories, added=True)

    if operation == "add_again":
        with pytest.raises(DuplicateMappingError):
            mappings.add(media_id, tag_id)
    else:
        mappings.remove(media_id, tag_id)
        assert mappings.tags_for_media(media_id) == []


def test_add_with_a_nonexistent_media_id_is_rejected_by_the_foreign_key(
    repositories: _Repositories,
) -> None:
    mappings, _media_repo, tag_repo = repositories
    tag = tag_repo.create("vacation")

    with pytest.raises(sqlite3.IntegrityError):
        mappings.add(999, tag.id)


def test_add_with_a_nonexistent_tag_id_is_rejected_by_the_foreign_key(
    repositories: _Repositories,
) -> None:
    mappings, media_repo, _tag_repo = repositories
    media_id = add_active_media(media_repo, "a.jpg")

    with pytest.raises(sqlite3.IntegrityError):
        mappings.add(media_id, 999)


def test_remove_a_mapping_that_does_not_exist_is_a_no_op(
    repositories: _Repositories,
) -> None:
    mappings, media_repo, tag_repo = repositories
    media_id = add_active_media(media_repo, "a.jpg")
    tag = tag_repo.create("vacation")

    mappings.remove(media_id, tag.id)  # never added; should not raise


def test_media_ids_for_tags_with_no_tags_returns_empty(
    repositories: _Repositories,
) -> None:
    mappings, _media_repo, _tag_repo = repositories

    assert mappings.media_ids_for_tags([]) == []


@pytest.mark.parametrize("has_common_media", [True, False], ids=["intersection", "no-common-media"])
def test_media_ids_for_tags_return_only_media_common_to_all_tags(
    repositories: _Repositories,
    has_common_media: bool,
) -> None:
    mappings, media_repo, tag_repo = repositories
    beach = add_active_media(media_repo, "beach.jpg")
    mountain = add_active_media(media_repo, "mountain.jpg")
    vacation = tag_repo.create("vacation")
    other = tag_repo.create("summer" if has_common_media else "work")

    mappings.add(beach, vacation.id)
    if has_common_media:
        mappings.add(beach, other.id)
        mappings.add(mountain, vacation.id)
        assert set(mappings.media_ids_for_tags([vacation.id])) == {beach, mountain}
    else:
        mappings.add(mountain, other.id)

    expected = [beach] if has_common_media else []
    assert mappings.media_ids_for_tags([vacation.id, other.id]) == expected
