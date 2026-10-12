from pathlib import Path

import pytest

from prismic.persistence.errors import CollectionLockedError
from prismic.persistence.lockfile import CollectionLock


@pytest.fixture
def collection_file(tmp_path: Path) -> Path:
    target = tmp_path / "vacation.prismic"
    target.touch()
    return target


def test_acquire_and_release_round_trip(collection_file: Path) -> None:
    lock = CollectionLock(collection_file)

    lock.acquire()
    lock.release()  # should not raise


def test_a_second_lock_on_the_same_file_is_rejected(collection_file: Path) -> None:
    first = CollectionLock(collection_file)
    first.acquire()
    try:
        second = CollectionLock(collection_file)
        with pytest.raises(CollectionLockedError):
            second.acquire()
    finally:
        first.release()


@pytest.mark.parametrize(
    "context_managed",
    [False, True],
    ids=["explicit-release", "context-manager"],
)
def test_release_allows_another_lock_to_be_acquired(
    collection_file: Path, context_managed: bool
) -> None:
    first = CollectionLock(collection_file)
    if context_managed:
        with first:
            pass
    else:
        first.acquire()
        first.release()

    second = CollectionLock(collection_file)
    second.acquire()
    second.release()
