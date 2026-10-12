from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from prismic.application.commands.tag_commands import TagCreateCommand
from prismic.application.session import PrismicSession


def _collection_root(tmp_path: Path, *, first_file: bytes | None = None) -> Path:
    collection_root = tmp_path / "vacation"
    collection_root.mkdir()
    if first_file is not None:
        (collection_root / "a.jpg").write_bytes(first_file)
    return collection_root


def _open_session(collection_root: Path) -> PrismicSession:
    return PrismicSession.open(collection_root)


def _await_initial_scan(session: PrismicSession) -> None:
    session.initial_reconciliation.result(timeout=5)


@contextmanager
def _ready_session(collection_root: Path) -> Iterator[PrismicSession]:
    with _open_session(collection_root) as session:
        _await_initial_scan(session)
        yield session


def test_open_assembles_a_fully_working_session(tmp_path: Path) -> None:
    collection_root = _collection_root(tmp_path, first_file=b"content")

    with _open_session(collection_root) as session:
        assert session.collection.root == collection_root
        assert session.collection.database_path.exists()

        # The initial background scan eventually discovers the file.
        _await_initial_scan(session)
        session.refresh_state()

        assert len(session.media.list_all()) == 1
        assert session.state.result_set == [session.media.list_all()[0].id]


def test_commands_go_through_the_dispatcher_and_are_undoable(tmp_path: Path) -> None:
    with _ready_session(_collection_root(tmp_path)) as session:
        session.execute(TagCreateCommand(name="vacation"))
        assert [t.name for t in session.tags.list_all()] == ["vacation"]

        session.undo()
        assert session.tags.list_all() == []


def test_rescan_returns_a_future_and_keeps_the_database_consistent(tmp_path: Path) -> None:
    collection_root = _collection_root(tmp_path)
    with _ready_session(collection_root) as session:
        (collection_root / "new.jpg").write_bytes(b"new content")
        result = session.rescan().result(timeout=5)
        session.refresh_state()

        assert result.applied
        assert [m.relative_path for m in session.media.list_all()] == ["new.jpg"]


def test_is_first_scan_is_true_until_the_initial_scan_completes_then_false(
    tmp_path: Path,
) -> None:
    collection_root = _collection_root(tmp_path, first_file=b"content")

    with _open_session(collection_root) as session:
        # True from construction -- read synchronously before the
        # background scan could possibly have written a count back.
        assert session.is_first_scan is True

        _await_initial_scan(session)

        (collection_root / "b.jpg").write_bytes(b"more content")
        session.rescan().result(timeout=5)

        assert session.is_first_scan is False


def test_close_leaves_no_lingering_lock_for_a_subsequent_open(tmp_path: Path) -> None:
    collection_root = tmp_path / "vacation"
    collection_root.mkdir()

    session = PrismicSession.open(collection_root)
    session.initial_reconciliation.result(timeout=5)
    session.close()

    # A fresh session can open the same collection now that the first is closed.
    with PrismicSession.open(collection_root) as reopened:
        reopened.initial_reconciliation.result(timeout=5)
        assert reopened.collection.root == collection_root
