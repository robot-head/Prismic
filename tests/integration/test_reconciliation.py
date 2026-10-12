import sqlite3
from pathlib import Path

import pytest

from prismic.domain.collection import Collection
from prismic.domain.media import Media, MediaState
from prismic.indexing.reconciler import HashedFile, Reconciler, run_reconciliation
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.scan_stats_repository import ScanStatsRepository


@pytest.fixture
def collection(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path, database_path=tmp_path / "vacation.prismic")


@pytest.fixture
def reconciler() -> Reconciler:
    return Reconciler()


@pytest.fixture
def media_repository(migrated_connection: sqlite3.Connection) -> MediaRepository:
    return MediaRepository(migrated_connection)


def _run(reconciler: Reconciler, collection: Collection, connection: sqlite3.Connection) -> None:
    generation = reconciler.begin_scan()
    result = run_reconciliation(reconciler, collection, generation, connection)
    assert result.applied


def _record_one_file(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    connection: sqlite3.Connection,
) -> Media:
    (collection.root / "a.jpg").write_bytes(b"content")
    _run(reconciler, collection, connection)
    return media_repository.list_all()[0]


def _scan_two_files(
    collection: Collection, reconciler: Reconciler, connection: sqlite3.Connection
) -> None:
    (collection.root / "a.jpg").write_bytes(b"content")
    (collection.root / "b.jpg").write_bytes(b"more content")
    _run(reconciler, collection, connection)


def test_new_file_gets_a_new_identity(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
) -> None:
    (collection.root / "a.jpg").write_bytes(b"content")

    _run(reconciler, collection, migrated_connection)

    media = media_repository.list_all()
    assert len(media) == 1
    assert media[0].relative_path == "a.jpg"
    assert media[0].state == MediaState.ACTIVE


def test_unchanged_file_is_a_no_op(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
) -> None:
    (collection.root / "a.jpg").write_bytes(b"content")
    _run(reconciler, collection, migrated_connection)
    first_pass = media_repository.list_all()

    _run(reconciler, collection, migrated_connection)

    second_pass = media_repository.list_all()
    assert second_pass == first_pass


def test_changed_content_creates_a_new_identity_and_retires_the_old_one(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
) -> None:
    target = collection.root / "a.jpg"
    target.write_bytes(b"original content")
    _run(reconciler, collection, migrated_connection)
    original = media_repository.list_all()[0]

    target.write_bytes(b"replaced content")
    _run(reconciler, collection, migrated_connection)

    media = media_repository.list_all()
    assert len(media) == 2
    retired = next(m for m in media if m.id == original.id)
    replacement = next(m for m in media if m.id != original.id)
    assert retired.state == MediaState.MISSING
    assert retired.content_hash == original.content_hash  # untouched history
    assert replacement.relative_path == "a.jpg"
    assert replacement.state == MediaState.ACTIVE
    assert replacement.content_hash != original.content_hash


def test_unique_move_relinks_the_existing_identity(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
) -> None:
    original_path = collection.root / "a.jpg"
    original_path.write_bytes(b"content")
    _run(reconciler, collection, migrated_connection)
    original = media_repository.list_all()[0]

    original_path.rename(collection.root / "moved.jpg")
    _run(reconciler, collection, migrated_connection)

    media = media_repository.list_all()
    assert len(media) == 1
    assert media[0].id == original.id
    assert media[0].relative_path == "moved.jpg"
    assert media[0].state == MediaState.ACTIVE


def test_ambiguous_move_leaves_the_old_identity_unresolved(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
) -> None:
    original_path = collection.root / "a.jpg"
    original_path.write_bytes(b"shared content")
    _run(reconciler, collection, migrated_connection)
    original = media_repository.list_all()[0]

    # The original disappears from its path, and two *different* new files
    # both happen to share its content hash — Prismic must not guess which
    # (if either) is "the move".
    original_path.unlink()
    (collection.root / "candidate_one.jpg").write_bytes(b"shared content")
    (collection.root / "candidate_two.jpg").write_bytes(b"shared content")
    _run(reconciler, collection, migrated_connection)

    media = media_repository.list_all()
    assert len(media) == 3
    original_after = next(m for m in media if m.id == original.id)
    assert original_after.state == MediaState.MISSING
    new_identities = [m for m in media if m.id != original.id]
    assert len(new_identities) == 2
    assert {m.relative_path for m in new_identities} == {"candidate_one.jpg", "candidate_two.jpg"}
    assert all(m.state == MediaState.ACTIVE for m in new_identities)


def test_missing_file_is_marked_missing_not_deleted(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
) -> None:
    original = _record_one_file(collection, reconciler, media_repository, migrated_connection)
    target = collection.root / "a.jpg"

    target.unlink()
    _run(reconciler, collection, migrated_connection)

    media = media_repository.list_all()
    assert len(media) == 1
    assert media[0].id == original.id
    assert media[0].state == MediaState.MISSING


def test_unsupported_file_is_never_recorded(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
) -> None:
    (collection.root / "notes.txt").write_bytes(b"not media")

    _run(reconciler, collection, migrated_connection)

    assert media_repository.list_all() == []


def test_unreadable_file_is_skipped_without_disturbing_its_recorded_state(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
) -> None:
    original = _record_one_file(collection, reconciler, media_repository, migrated_connection)

    generation = reconciler.begin_scan()
    result = reconciler.reconcile(
        migrated_connection, generation, [], unreadable_paths=frozenset({"a.jpg"})
    )

    assert result.applied
    media = media_repository.list_all()
    assert media == [original]  # left completely untouched, not marked missing


def test_a_stale_reconciliation_is_discarded(
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
) -> None:
    stale_generation = reconciler.begin_scan()
    current_generation = reconciler.begin_scan()  # a newer scan has since begun

    result = reconciler.reconcile(
        migrated_connection,
        stale_generation,
        [HashedFile(relative_path="a.jpg", content_hash="h", size=1, mtime=1.0)],
    )

    assert result.applied is False
    assert media_repository.list_all() == []

    # The current generation still applies normally.
    result = reconciler.reconcile(
        migrated_connection,
        current_generation,
        [HashedFile(relative_path="a.jpg", content_hash="h", size=1, mtime=1.0)],
    )
    assert result.applied is True
    assert len(media_repository.list_all()) == 1


def test_scan_reports_progress_against_the_previous_scans_count(
    collection: Collection,
    reconciler: Reconciler,
    migrated_connection: sqlite3.Connection,
) -> None:
    _scan_two_files(collection, reconciler, migrated_connection)  # no prior count to report yet

    (collection.root / "c.jpg").write_bytes(b"even more content")
    calls: list[tuple[int, int]] = []
    generation = reconciler.begin_scan()
    run_reconciliation(
        reconciler,
        collection,
        generation,
        migrated_connection,
        on_progress=lambda processed, total: calls.append((processed, total)),
    )

    # Three candidate files this pass, each reported as it's processed,
    # against last scan's total (2) as the denominator throughout.
    assert len(calls) == 3
    assert {processed for processed, _ in calls} == {1, 2, 3}
    assert all(expected_total == 2 for _, expected_total in calls)


def test_scan_persists_its_own_file_count_for_the_next_scan_to_use(
    collection: Collection,
    reconciler: Reconciler,
    migrated_connection: sqlite3.Connection,
) -> None:
    _scan_two_files(collection, reconciler, migrated_connection)

    assert ScanStatsRepository(migrated_connection).get_last_file_count() == 2


def test_hashing_runs_multiple_files_concurrently(
    collection: Collection,
    reconciler: Reconciler,
    migrated_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of parallelizing hashing: on a large root, files are
    hashed *at the same time*, not one after another. Each stand-in `hash_file`
    call blocks until every other one of the N files has also entered the
    function -- a barrier that only clears if all N are in flight together,
    which is only possible if they're running on separate threads
    concurrently rather than sequentially on one."""
    import threading

    import prismic.indexing.reconciler as reconciler_module

    # Kept comfortably below ThreadPoolExecutor's own minimum default pool
    # size (`min(32, (os.cpu_count() or 1) + 4)`, at least 5 even on a
    # single-core CI runner) so this can't spuriously fail for lack of
    # worker threads rather than for a real regression to sequential hashing.
    n_files = 4
    for i in range(n_files):
        (collection.root / f"{i}.jpg").write_bytes(f"content {i}".encode())
    barrier = threading.Barrier(n_files, timeout=5)

    def _blocking_hash_file(path: object) -> str:
        barrier.wait()  # hangs forever (until the 5s timeout) unless all N arrive together
        return str(path)

    monkeypatch.setattr(reconciler_module, "hash_file", _blocking_hash_file)

    _run(reconciler, collection, migrated_connection)  # must not time out


def test_hashing_starts_before_the_walk_finishes(
    collection: Collection,
    reconciler: Reconciler,
    migrated_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A progress indicator that sits frozen until the whole tree is
    walked, then races through hashing, isn't a progress indicator for the
    walk itself -- on a slow walk (a large root, a network share), hashing
    must already be under way *while still walking*, not only start once
    `scan()` is exhausted. Proven directly: a stand-in `scan()` yields one
    file, then blocks until that file's hash has demonstrably started on a
    worker thread before yielding the rest -- which only clears if
    submission and walking are interleaved, not sequential phases."""
    import threading

    import prismic.indexing.reconciler as reconciler_module

    (collection.root / "a.jpg").write_bytes(b"a")
    (collection.root / "b.jpg").write_bytes(b"b")

    hash_started = threading.Event()
    real_hash_file = reconciler_module.hash_file
    real_scan = reconciler_module.scan

    def _hash_file_signaling_start(path: object) -> str:
        hash_started.set()
        return real_hash_file(path)  # type: ignore[arg-type]

    def _scan_blocking_after_first(collection_: Collection):  # type: ignore[no-untyped-def]
        iterator = iter(real_scan(collection_))
        yield next(iterator)
        assert hash_started.wait(timeout=5), "hashing never started before the walk continued"
        yield from iterator

    monkeypatch.setattr(reconciler_module, "hash_file", _hash_file_signaling_start)
    monkeypatch.setattr(reconciler_module, "scan", _scan_blocking_after_first)

    _run(reconciler, collection, migrated_connection)  # must not hang/time out


def test_reconciliation_can_run_on_a_separate_connection_to_the_same_file(
    tmp_path: Path,
) -> None:
    """The whole point of taking a connection per call: a background worker
    opens its own connection to the same `.prismic` file rather than reusing
    the session's main-thread connection."""
    from prismic.persistence import database, migrations

    database_path = tmp_path / "vacation.prismic"
    main_connection = database.connect(database_path)
    migrations.migrate(main_connection, database_path)

    collection = Collection(root=tmp_path, database_path=database_path)
    (tmp_path / "a.jpg").write_bytes(b"content")

    worker_connection = database.connect(database_path)
    try:
        reconciler = Reconciler()
        generation = reconciler.begin_scan()
        result = run_reconciliation(reconciler, collection, generation, worker_connection)
        assert result.applied
    finally:
        worker_connection.close()

    media = MediaRepository(main_connection).list_all()
    assert len(media) == 1
    assert media[0].relative_path == "a.jpg"
    main_connection.close()


# --- size/mtime shortcut: unchanged files aren't re-read -------------------

_OLD_MTIME = 1_600_000_000.25  # settled (not recent) and has a sub-second part


def _write_settled(path: Path, content: bytes, mtime: float = _OLD_MTIME) -> None:
    import os

    path.write_bytes(content)
    os.utime(path, ns=(int(mtime * 1e9), int(mtime * 1e9)))


def _rewrite_and_reconcile(
    target: Path,
    content: bytes,
    reconciler: Reconciler,
    collection: Collection,
    connection: sqlite3.Connection,
    mtime: float = _OLD_MTIME,
) -> None:
    _write_settled(target, content, mtime)
    _run(reconciler, collection, connection)


def _hash_calls_for_rewrite(
    collection: Collection,
    reconciler: Reconciler,
    connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    mtime: float = _OLD_MTIME,
) -> list[object]:
    target = collection.root / "a.jpg"
    _write_settled(target, b"content")
    _run(reconciler, collection, connection)
    calls = _count_hash_calls(monkeypatch)
    _rewrite_and_reconcile(target, content, reconciler, collection, connection, mtime)
    return calls


def _count_hash_calls(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    import prismic.indexing.reconciler as reconciler_module

    calls: list[object] = []
    real_hash_file = reconciler_module.hash_file

    def _counting(path: Path) -> str:
        calls.append(path)
        return real_hash_file(path)

    monkeypatch.setattr(reconciler_module, "hash_file", _counting)
    return calls


def test_unchanged_settled_file_is_not_rehashed(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_settled(collection.root / "a.jpg", b"content")
    _run(reconciler, collection, migrated_connection)
    first = media_repository.list_all()
    calls = _count_hash_calls(monkeypatch)

    _run(reconciler, collection, migrated_connection)

    assert calls == []
    assert media_repository.list_all() == first


def test_changed_size_is_rehashed_and_detected(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _hash_calls_for_rewrite(
        collection, reconciler, migrated_connection, monkeypatch, b"longer content"
    )  # same mtime, different size

    assert len(calls) == 1
    assert [m.state for m in media_repository.list_all()] == [MediaState.MISSING, MediaState.ACTIVE]


def test_changed_mtime_is_rehashed(
    collection: Collection,
    reconciler: Reconciler,
    migrated_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _hash_calls_for_rewrite(
        collection,
        reconciler,
        migrated_connection,
        monkeypatch,
        b"CONTENT",
        mtime=_OLD_MTIME + 5,
    )  # same size, newer mtime

    assert len(calls) == 1


def test_recently_modified_file_is_always_rehashed(
    collection: Collection,
    reconciler: Reconciler,
    migrated_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (collection.root / "a.jpg").write_bytes(b"content")  # mtime is "now"
    _run(reconciler, collection, migrated_connection)
    calls = _count_hash_calls(monkeypatch)

    _run(reconciler, collection, migrated_connection)

    assert len(calls) == 1


def test_whole_second_mtime_is_always_rehashed(
    collection: Collection,
    reconciler: Reconciler,
    migrated_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAT-style timestamps: equal whole-second mtimes prove too little."""
    _write_settled(collection.root / "a.jpg", b"content", mtime=1_600_000_000.0)
    _run(reconciler, collection, migrated_connection)
    calls = _count_hash_calls(monkeypatch)

    _run(reconciler, collection, migrated_connection)

    assert len(calls) == 1


def test_move_is_still_detected_when_other_files_are_skipped(
    collection: Collection,
    reconciler: Reconciler,
    media_repository: MediaRepository,
    migrated_connection: sqlite3.Connection,
) -> None:
    _write_settled(collection.root / "stay.jpg", b"stays")
    _write_settled(collection.root / "move.jpg", b"moves")
    _run(reconciler, collection, migrated_connection)
    original_ids = {m.relative_path: m.id for m in media_repository.list_all()}

    (collection.root / "move.jpg").rename(collection.root / "moved.jpg")
    _run(reconciler, collection, migrated_connection)

    by_path = {m.relative_path: m for m in media_repository.list_all()}
    assert by_path["moved.jpg"].id == original_ids["move.jpg"]
    assert by_path["stay.jpg"].id == original_ids["stay.jpg"]
