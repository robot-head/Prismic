from pathlib import Path

from prismic.domain.collection import Collection


def _collection_with_database(tmp_path: Path) -> Collection:
    database_path = tmp_path / "vacation.prismic"
    database_path.touch()
    return Collection(root=tmp_path, database_path=database_path)


def test_is_collection_file_matches_its_own_database_path(tmp_path: Path) -> None:
    collection = _collection_with_database(tmp_path)

    assert collection.is_collection_file(collection.database_path) is True


def test_is_collection_file_rejects_other_paths(tmp_path: Path) -> None:
    collection = _collection_with_database(tmp_path)

    assert collection.is_collection_file(tmp_path / "photo.jpg") is False
