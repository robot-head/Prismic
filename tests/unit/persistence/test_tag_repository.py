import sqlite3

import pytest

from prismic.domain.tag import InvalidTagNameError
from prismic.persistence.errors import DuplicateTagNameError, UnknownTagError
from prismic.persistence.repositories.tag_repository import TagRepository


@pytest.fixture
def repository(migrated_connection: sqlite3.Connection) -> TagRepository:
    return TagRepository(migrated_connection)


def test_create_returns_a_tag_with_a_trimmed_name(repository: TagRepository) -> None:
    tag = repository.create("  vacation  ")

    assert tag.name == "vacation"
    assert tag.id is not None


def test_create_rejects_an_invalid_name(repository: TagRepository) -> None:
    with pytest.raises(InvalidTagNameError):
        repository.create("   ")


def test_create_rejects_an_exact_duplicate_name(repository: TagRepository) -> None:
    repository.create("vacation")

    with pytest.raises(DuplicateTagNameError):
        repository.create("vacation")


def test_names_are_case_sensitive(repository: TagRepository) -> None:
    repository.create("vacation")

    lowercase_variant = repository.create("Vacation")

    assert lowercase_variant.name == "Vacation"


def test_rename_updates_the_stored_name(repository: TagRepository) -> None:
    tag = repository.create("vacation")

    renamed = repository.rename(tag.id, "travel")

    assert renamed.name == "travel"
    assert repository.get(tag.id).name == "travel"  # type: ignore[union-attr]


def test_rename_to_an_existing_name_raises(repository: TagRepository) -> None:
    repository.create("vacation")
    other = repository.create("travel")

    with pytest.raises(DuplicateTagNameError):
        repository.rename(other.id, "vacation")


def test_rename_unknown_tag_raises(repository: TagRepository) -> None:
    with pytest.raises(UnknownTagError):
        repository.rename(999, "anything")


def test_delete_removes_the_tag(repository: TagRepository) -> None:
    tag = repository.create("vacation")

    repository.delete(tag.id)

    assert repository.get(tag.id) is None


def test_delete_unknown_tag_raises(repository: TagRepository) -> None:
    with pytest.raises(UnknownTagError):
        repository.delete(999)


def test_get_returns_none_for_unknown_id(repository: TagRepository) -> None:
    assert repository.get(999) is None


def test_list_all_breaks_ties_by_name(repository: TagRepository) -> None:
    # None of these are used by any media, so they're all tied on use
    # count -- the name is what orders them in that case.
    repository.create("zebra")
    repository.create("apple")
    repository.create("mango")

    assert [tag.name for tag in repository.list_all()] == ["apple", "mango", "zebra"]


def test_list_all_is_ordered_by_descending_use_count(
    repository: TagRepository, migrated_connection: sqlite3.Connection
) -> None:
    rare = repository.create("rare")
    popular = repository.create("popular")
    repository.create("unused")

    for path in ("a.jpg", "b.jpg", "c.jpg"):
        migrated_connection.execute(
            "INSERT INTO media (content_hash, relative_path, size, mtime, state) "
            "VALUES ('h', ?, 0, 0, 'present')",
            (path,),
        )
    media_ids = [row[0] for row in migrated_connection.execute("SELECT id FROM media").fetchall()]
    migrated_connection.executemany(
        "INSERT INTO media_tags (media_id, tag_id) VALUES (?, ?)",
        [(media_ids[0], rare.id), *((mid, popular.id) for mid in media_ids)],
    )

    assert [tag.name for tag in repository.list_all()] == ["popular", "rare", "unused"]


def test_mega_popular_tag_ids_uses_the_same_use_count_basis_as_list_all(
    repository: TagRepository, migrated_connection: sqlite3.Connection
) -> None:
    mega = repository.create("mega")
    rare = repository.create("rare")
    boundary = repository.create("boundary")

    for path in ("a.jpg", "b.jpg", "c.jpg", "d.jpg"):
        migrated_connection.execute(
            "INSERT INTO media (content_hash, relative_path, size, mtime, state) "
            "VALUES ('h', ?, 0, 0, 'active')",
            (path,),
        )
    media_ids = [row[0] for row in migrated_connection.execute("SELECT id FROM media").fetchall()]
    # mega: 3 of 4 files (75%), rare: 1 of 4 (25%).
    migrated_connection.executemany(
        "INSERT INTO media_tags (media_id, tag_id) VALUES (?, ?)",
        [
            (media_ids[0], rare.id),
            *((mid, mega.id) for mid in media_ids[:3]),
            *((mid, boundary.id) for mid in media_ids[:2]),
        ],
    )

    assert repository.mega_popular_tag_ids(0.5, total_media_count=4) == frozenset(
        {mega.id, boundary.id}
    )
    assert repository.mega_popular_tag_ids(0.1, total_media_count=4) == frozenset(
        {mega.id, rare.id, boundary.id}
    )


def test_mega_popular_tag_ids_is_empty_with_no_media(repository: TagRepository) -> None:
    repository.create("mega")

    assert repository.mega_popular_tag_ids(0.1, total_media_count=0) == frozenset()
