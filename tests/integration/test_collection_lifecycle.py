from pathlib import Path

import pytest

from prismic.persistence import database
from prismic.persistence.collection import (
    OpenCollection,
    find_collection_file,
    open_collection,
    resolve_database_path,
)
from prismic.persistence.errors import (
    CollectionLockedError,
    IncompatibleDatabaseError,
    MultipleCollectionFilesError,
)


@pytest.fixture
def empty_collection_root(tmp_path: Path) -> Path:
    root = tmp_path / "vacation"
    root.mkdir()
    return root


def test_opening_accepts_a_plain_string_path_not_just_a_path_object(tmp_path: Path) -> None:
    collection_root = tmp_path / "vacation"
    collection_root.mkdir()

    with open_collection(str(collection_root)) as opened:
        assert opened.collection.root == collection_root


def test_opening_an_empty_directory_creates_a_collection_named_after_it(tmp_path: Path) -> None:
    collection_root = tmp_path / "vacation photos"
    collection_root.mkdir()

    with open_collection(collection_root) as opened:
        assert opened.collection.root == collection_root
        assert opened.collection.database_path == collection_root / "vacation photos.prismic"
        assert opened.collection.database_path.exists()
        assert database.schema_version(opened.connection) > 0


def test_opening_a_directory_with_an_existing_collection_file_reuses_it(tmp_path: Path) -> None:
    collection_root = tmp_path / "vacation"
    collection_root.mkdir()
    with open_collection(collection_root) as first:
        first_path = first.collection.database_path

    with open_collection(collection_root) as second:
        assert second.collection.database_path == first_path


def test_opening_a_direct_file_path_uses_its_parent_as_the_root(tmp_path: Path) -> None:
    collection_root = tmp_path / "vacation"
    collection_root.mkdir()
    with open_collection(collection_root) as first:
        database_path = first.collection.database_path

    with open_collection(database_path) as reopened:
        assert reopened.collection.root == collection_root
        assert reopened.collection.database_path == database_path


def test_more_than_one_prismic_file_in_a_directory_is_an_error(tmp_path: Path) -> None:
    collection_root = tmp_path / "vacation"
    collection_root.mkdir()
    (collection_root / "one.prismic").touch()
    (collection_root / "two.prismic").touch()

    with pytest.raises(MultipleCollectionFilesError):
        find_collection_file(collection_root)

    with pytest.raises(MultipleCollectionFilesError):
        resolve_database_path(collection_root)

    with pytest.raises(MultipleCollectionFilesError):
        open_collection(collection_root)


def test_a_second_open_while_the_first_is_still_open_is_locked_out(
    empty_collection_root: Path,
) -> None:
    collection_root = empty_collection_root
    first = open_collection(collection_root)
    try:
        with pytest.raises(CollectionLockedError):
            open_collection(collection_root)
    finally:
        first.close()


def test_closing_releases_the_lock_for_a_subsequent_open(empty_collection_root: Path) -> None:
    collection_root = empty_collection_root
    first = open_collection(collection_root)
    first.close()

    with open_collection(collection_root) as second:
        assert second.collection.root == collection_root


def test_opening_an_incompatible_file_raises_and_leaves_no_lock_held(tmp_path: Path) -> None:
    collection_root = tmp_path / "vacation"
    collection_root.mkdir()
    garbage = collection_root / "vacation.prismic"
    garbage.write_bytes(b"not a sqlite database" * 5)

    with pytest.raises(IncompatibleDatabaseError):
        open_collection(collection_root)

    # The failed open must not have left the file locked or an open connection
    # dangling — a well-formed retry (after fixing the file) should succeed.
    garbage.unlink()
    with open_collection(collection_root) as opened:
        assert isinstance(opened, OpenCollection)
