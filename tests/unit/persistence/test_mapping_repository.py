import sqlite3

import pytest

from prismic.domain.media import MediaState
from prismic.persistence.errors import DuplicateMappingError
from prismic.persistence.repositories.mapping_repository import MappingRepository
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.tag_repository import TagRepository


@pytest.fixture
def repositories(
    migrated_connection: sqlite3.Connection,
) -> tuple[MappingRepository, MediaRepository, TagRepository]:
    return (
        MappingRepository(migrated_connection),
        MediaRepository(migrated_connection),
        TagRepository(migrated_connection),
    )


def _make_media(media_repo: MediaRepository, relative_path: str) -> int:
    return media_repo.create(
        relative_path=relative_path,
        content_hash=relative_path,
        size=1,
        mtime=1.0,
        state=MediaState.ACTIVE,
    ).id


def _mapping_setup(
    repositories: tuple[MappingRepository, MediaRepository, TagRepository], *, added: bool = False
) -> tuple[MappingRepository, int, int]:
    mappings, media_repo, tag_repo = repositories
    media_id = _make_media(media_repo, "a.jpg")
    tag_id = tag_repo.create("vacation").id
    if added:
        mappings.add(media_id, tag_id)
    return mappings, media_id, tag_id


def test_add_and_tags_for_media(
    repositories: tuple[MappingRepository, MediaRepository, TagRepository],
) -> None:
    mappings, media_id, tag_id = _mapping_setup(repositories)

    mappings.add(media_id, tag_id)

    assert [t.name for t in mappings.tags_for_media(media_id)] == ["vacation"]


def test_add_the_same_mapping_twice_raises(
    repositories: tuple[MappingRepository, MediaRepository, TagRepository],
) -> None:
    mappings, media_id, tag_id = _mapping_setup(repositories, added=True)

    with pytest.raises(DuplicateMappingError):
        mappings.add(media_id, tag_id)


def test_add_with_a_nonexistent_media_id_is_rejected_by_the_foreign_key(
    repositories: tuple[MappingRepository, MediaRepository, TagRepository],
) -> None:
    mappings, _media_repo, tag_repo = repositories
    tag = tag_repo.create("vacation")

    with pytest.raises(sqlite3.IntegrityError):
        mappings.add(999, tag.id)


def test_add_with_a_nonexistent_tag_id_is_rejected_by_the_foreign_key(
    repositories: tuple[MappingRepository, MediaRepository, TagRepository],
) -> None:
    mappings, media_repo, _tag_repo = repositories
    media_id = _make_media(media_repo, "a.jpg")

    with pytest.raises(sqlite3.IntegrityError):
        mappings.add(media_id, 999)


def test_remove_deletes_the_mapping(
    repositories: tuple[MappingRepository, MediaRepository, TagRepository],
) -> None:
    mappings, media_id, tag_id = _mapping_setup(repositories, added=True)

    mappings.remove(media_id, tag_id)

    assert mappings.tags_for_media(media_id) == []


def test_remove_a_mapping_that_does_not_exist_is_a_no_op(
    repositories: tuple[MappingRepository, MediaRepository, TagRepository],
) -> None:
    mappings, media_repo, tag_repo = repositories
    media_id = _make_media(media_repo, "a.jpg")
    tag = tag_repo.create("vacation")

    mappings.remove(media_id, tag.id)  # never added; should not raise


def test_media_ids_for_tags_with_no_tags_returns_empty(
    repositories: tuple[MappingRepository, MediaRepository, TagRepository],
) -> None:
    mappings, _media_repo, _tag_repo = repositories

    assert mappings.media_ids_for_tags([]) == []


def test_media_ids_for_tags_is_an_intersection(
    repositories: tuple[MappingRepository, MediaRepository, TagRepository],
) -> None:
    mappings, media_repo, tag_repo = repositories
    beach = _make_media(media_repo, "beach.jpg")
    mountain = _make_media(media_repo, "mountain.jpg")
    vacation = tag_repo.create("vacation")
    summer = tag_repo.create("summer")

    mappings.add(beach, vacation.id)
    mappings.add(beach, summer.id)
    mappings.add(mountain, vacation.id)

    assert set(mappings.media_ids_for_tags([vacation.id])) == {beach, mountain}
    assert mappings.media_ids_for_tags([vacation.id, summer.id]) == [beach]


def test_media_ids_for_tags_with_no_common_media_is_empty(
    repositories: tuple[MappingRepository, MediaRepository, TagRepository],
) -> None:
    mappings, media_repo, tag_repo = repositories
    beach = _make_media(media_repo, "beach.jpg")
    mountain = _make_media(media_repo, "mountain.jpg")
    vacation = tag_repo.create("vacation")
    work = tag_repo.create("work")

    mappings.add(beach, vacation.id)
    mappings.add(mountain, work.id)

    assert mappings.media_ids_for_tags([vacation.id, work.id]) == []
