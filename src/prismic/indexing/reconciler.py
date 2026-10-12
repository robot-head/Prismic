"""Reconciliation: correlates a filesystem scan against recorded media identity.

Implements overview section 3's move/change semantics: new files, unchanged
files, changed content, unique vs. ambiguous moves, and missing-not-deleted
files. Also implements section 7's staleness rule: a reconciliation call for
a generation that's no longer current is a no-op, since a newer scan has
since begun.

Move detection is symmetric: a relink only happens when exactly one
"candidate" (an already-missing record, or a previously-active record whose
path wasn't seen this scan) and exactly one unmatched scanned file share a
content hash. Multiple on *either* side is treated as ambiguous — the
overview's wording ("a missing record's hash matches exactly one new file")
reads naturally as per-candidate, but the reverse case (two candidates
matching one file) is just as unsafe to guess at, so it's held to the same
1:1 standard.
"""

from __future__ import annotations

import queue
import sqlite3
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial

from prismic.domain.collection import Collection
from prismic.domain.media import Media, MediaState
from prismic.indexing.hashing import hash_file
from prismic.indexing.scanner import ScannedFile, scan
from prismic.persistence import database
from prismic.persistence.repositories.media_repository import MediaFields, MediaRepository
from prismic.persistence.repositories.scan_stats_repository import ScanStatsRepository

# Called as (files_processed_so_far, expected_total) while a scan is under
# way. `expected_total` is last scan's file count, not this one's -- see
# `run_reconciliation` -- so it's an estimate a caller may want to treat as
# a lower bound (progress can legitimately pass 100% if the collection grew).
ProgressCallback = Callable[[int, int], None]

__all__ = [
    "HashedFile",
    "ProgressCallback",
    "Reconciler",
    "ReconciliationResult",
    "hash_file",
    "run_reconciliation",
    "scan",
]
# `hash_file` and `scan` are re-exported (not just imported for internal
# use) so tests can monkeypatch `prismic.indexing.reconciler.hash_file`/
# `.scan` specifically -- to simulate a file disappearing between the scan
# and the hash, and to prove hashing starts before the walk finishes,
# respectively.


# A file modified this recently is always re-hashed rather than trusted on
# its size/mtime: a filesystem's timestamp granularity (2s on FAT) means a
# second edit can land on an unchanged mtime, and "recently modified" is the
# only window in which that can happen.
_RECENT_MTIME_WINDOW_SECONDS = 2.0


def _recorded_hash_if_unchanged(
    scanned_file: ScannedFile, recorded: Media | None, now: float
) -> str | None:
    """The stored content hash for `scanned_file`, if its size/mtime prove it unchanged.

    Returns None whenever there's any doubt, meaning "read and hash it" -- the
    safe direction. A match is trusted only when size and mtime both equal what
    was recorded, the mtime isn't recent (see `_RECENT_MTIME_WINDOW_SECONDS`),
    and the mtime has a sub-second part: a whole-second mtime is what FAT and
    second-truncating tools produce, where equal mtimes prove little.
    """
    if recorded is None or recorded.state != MediaState.ACTIVE:
        return None
    if recorded.size != scanned_file.size or recorded.mtime != scanned_file.mtime:
        return None
    if scanned_file.mtime.is_integer():
        return None
    if scanned_file.mtime > now - _RECENT_MTIME_WINDOW_SECONDS:
        return None
    return recorded.content_hash


@dataclass(frozen=True, slots=True)
class HashedFile:
    """A scanned file with its content hash computed."""

    relative_path: str
    content_hash: str
    size: int
    mtime: float


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Summary of what a reconciliation pass did.

    `applied` is False when the call was discarded as stale — a newer scan
    had already begun, so this generation's results no longer apply.
    """

    applied: bool
    new_count: int = 0
    unchanged_count: int = 0
    changed_count: int = 0
    moved_count: int = 0
    missing_count: int = 0


def _active_media_fields(file: HashedFile) -> MediaFields:
    return {
        "relative_path": file.relative_path,
        "content_hash": file.content_hash,
        "size": file.size,
        "mtime": file.mtime,
        "state": MediaState.ACTIVE,
    }


def _create_active_media(repository: MediaRepository, file: HashedFile) -> None:
    repository.create(**_active_media_fields(file))


class Reconciler:
    """Tracks scan generations and applies reconciliation results.

    Every scan gets a generation id from `begin_scan()`. `reconcile()` only
    applies its results if that generation is still the current one — if a
    newer scan has since begun, the call is a stale no-op rather than
    mutating state out of order.

    Deliberately holds no connection of its own: per overview section 7,
    "SQLite connections are explicitly owned by their respective execution
    contexts rather than shared indiscriminately across threads." A
    reconciliation run on a background worker thread must use its own
    connection to the same `.prismic` file, not the session's main-thread
    connection — so `reconcile()` takes the connection to use per call.
    `begin_scan()`/`reconcile()` are safe to call from any thread; the
    generation counter and the reconcile-and-commit sequence are both
    guarded by an internal lock so overlapping calls can't interleave.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0

    def begin_scan(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation

    def reconcile(
        self,
        connection: sqlite3.Connection,
        generation: int,
        hashed_files: Iterable[HashedFile],
        *,
        unreadable_paths: frozenset[str] = frozenset(),
    ) -> ReconciliationResult:
        """Apply one scan's results, unless a newer scan has superseded it.

        `unreadable_paths` are candidate files the scanner found but that
        failed to hash (a permission/I/O error) — their existing recorded
        state, if any, is left completely untouched this pass rather than
        being marked missing just because it couldn't be re-verified.
        """
        with self._lock:
            return self._reconcile_locked(connection, generation, hashed_files, unreadable_paths)

    def _reconcile_locked(
        self,
        connection: sqlite3.Connection,
        generation: int,
        scan_results: Iterable[HashedFile],
        unreadable_paths: frozenset[str],
    ) -> ReconciliationResult:
        if generation != self._generation:
            return ReconciliationResult(applied=False)

        media_repository = MediaRepository(connection)
        hashed_files = list(scan_results)
        existing = media_repository.list_all()
        existing_by_path = {m.relative_path: m for m in existing if m.state == MediaState.ACTIVE}

        with database.transaction(connection):
            new_count = 0
            unchanged_count = 0
            changed_count = 0
            unmatched: list[HashedFile] = []

            for file in hashed_files:
                existing_media = existing_by_path.pop(file.relative_path, None)
                if existing_media is None:
                    unmatched.append(file)
                elif existing_media.content_hash == file.content_hash:
                    unchanged_count += 1
                else:
                    self._mark_missing(media_repository, existing_media)
                    _create_active_media(media_repository, file)
                    changed_count += 1

            # Candidates for move-matching: already-missing records, plus
            # previously-active records not observed at their path this scan
            # (excluding ones that were simply unreadable this pass).
            candidates_by_hash: dict[str, list[Media]] = defaultdict(list)
            for media in existing:
                if media.state == MediaState.MISSING:
                    candidates_by_hash[media.content_hash].append(media)
            for media in existing_by_path.values():
                if media.relative_path in unreadable_paths:
                    continue
                candidates_by_hash[media.content_hash].append(media)

            files_by_hash: dict[str, list[HashedFile]] = defaultdict(list)
            for file in unmatched:
                files_by_hash[file.content_hash].append(file)

            relinked_media_ids: set[int] = set()
            moved_count = 0

            for content_hash in set(candidates_by_hash) | set(files_by_hash):
                candidates = candidates_by_hash.get(content_hash, [])
                files = files_by_hash.get(content_hash, [])
                if len(candidates) == 1 and len(files) == 1:
                    media = candidates[0]
                    file = files[0]
                    media_repository.update(media.id, **_active_media_fields(file))
                    relinked_media_ids.add(media.id)
                    moved_count += 1
                else:
                    for file in files:
                        _create_active_media(media_repository, file)
                        new_count += 1

            missing_count = 0
            for media in existing_by_path.values():
                if media.id in relinked_media_ids:
                    continue
                if media.relative_path in unreadable_paths:
                    continue
                self._mark_missing(media_repository, media)
                missing_count += 1
        return ReconciliationResult(
            applied=True,
            new_count=new_count,
            unchanged_count=unchanged_count,
            changed_count=changed_count,
            moved_count=moved_count,
            missing_count=missing_count,
        )

    @staticmethod
    def _mark_missing(media_repository: MediaRepository, media: Media) -> None:
        if media.state == MediaState.MISSING:
            return
        media_repository.update(
            media.id,
            relative_path=media.relative_path,
            content_hash=media.content_hash,
            size=media.size,
            mtime=media.mtime,
            state=MediaState.MISSING,
        )


def run_reconciliation(
    reconciler: Reconciler,
    collection: Collection,
    generation: int,
    connection: sqlite3.Connection,
    *,
    on_progress: ProgressCallback | None = None,
) -> ReconciliationResult:
    """Scan `collection.root`, hash each candidate, and reconcile the result.

    Glue between the scanner, hashing, and the reconciler. `connection`
    should be a connection owned by whichever thread calls this — Phase 3's
    worker pool opens its own when dispatching this off the GUI thread,
    never reusing the session's main-thread connection.

    `on_progress`, if given, is called after each candidate file is hashed
    (or found unreadable) with the running count and the *previous* scan's
    total file count as its denominator — this scan's own total isn't known
    until it finishes walking the tree, so last time's count is the best
    estimate available while it's still under way. That count is persisted
    (via `ScanStatsRepository`) once this scan itself finishes walking, for
    the *next* call to use.

    A file whose size and mtime match its active record from the last scan
    isn't read at all: its stored hash is reused (see
    `_recorded_hash_if_unchanged` for when that's trusted and when it isn't),
    so a rescan of an unchanged collection costs one directory walk, not a
    read of every byte. Anything doubtful is hashed as before.

    Hashing itself -- the slow part on a large root, since it means reading
    every candidate file's full contents -- runs on a pool of threads
    rather than one file at a time: each `hash_file` call is independent
    (its own file handle, its own hashlib state) and spends most of its
    time in I/O or in hashlib's C extension, both of which release the
    GIL, so real wall-clock concurrency is available here without needing
    separate processes. `ThreadPoolExecutor`'s own default sizing (a small
    multiple of the CPU count) is used rather than a hand-picked constant,
    same reasoning as everywhere else in this codebase that leans on a
    stdlib default over a guessed number. Reconciliation itself (the
    `reconcile()` call below) stays single-threaded -- it's a sequence of
    dependent SQLite writes under one transaction, not an independent-unit
    workload like hashing is.

    Hashing is submitted to the pool *while still walking the tree*, not
    only once the whole walk finishes: each file goes to a worker the
    moment `scan()` yields it, so the pool is already chewing through
    early files well before `scan()` itself returns. Without this, a slow
    walk (a large root, especially over a network share) would leave
    `on_progress` completely silent until the walk finished, no matter how
    fast hashing itself later turned out to be -- the whole point of a
    progress indicator is to move throughout the pass, not sit frozen for
    its first phase and then race through the second. Completed hashes are
    drained from a queue (fed by each future's `add_done_callback`, which
    fires on whichever worker thread finished it) opportunistically
    between submissions, and to completion once the walk itself is done.
    """
    stats_repository = ScanStatsRepository(connection)
    expected_total = stats_repository.get_last_file_count()
    recorded_by_path = {
        m.relative_path: m
        for m in MediaRepository(connection).list_all()
        if m.state == MediaState.ACTIVE
    }
    scan_started_at = time.time()

    hashed_files: list[HashedFile] = []
    unreadable_paths: set[str] = set()
    processed = 0
    submitted = 0

    # (scanned_file, its now-finished future) pairs, pushed by whichever
    # thread finishes each hash -- a plain `Queue` rather than shared state
    # plus a lock, so the only code that ever touches `hashed_files`/
    # `unreadable_paths`/`processed` above runs on this thread.
    completed: queue.Queue[tuple[ScannedFile, Future[str]]] = queue.Queue()

    def _on_done(scanned_file: ScannedFile, future: Future[str]) -> None:
        completed.put((scanned_file, future))

    def _record(scanned_file: ScannedFile, content_hash: str | None) -> None:
        """Count one file as processed; `None` means it couldn't be read."""
        nonlocal processed
        if content_hash is None:
            unreadable_paths.add(scanned_file.relative_path)
        else:
            hashed_files.append(
                HashedFile(
                    relative_path=scanned_file.relative_path,
                    content_hash=content_hash,
                    size=scanned_file.size,
                    mtime=scanned_file.mtime,
                )
            )
        processed += 1
        if on_progress is not None:
            on_progress(processed, expected_total)

    def _apply(scanned_file: ScannedFile, future: Future[str]) -> None:
        try:
            content_hash = future.result()
        except OSError:
            _record(scanned_file, None)
        else:
            _record(scanned_file, content_hash)

    def _drain_ready() -> None:
        """Apply every hash that's already finished, without blocking."""
        while True:
            try:
                scanned_file, future = completed.get_nowait()
            except queue.Empty:
                return
            _apply(scanned_file, future)

    with ThreadPoolExecutor(thread_name_prefix="prismic-hash") as executor:
        for scanned_file in scan(collection):
            known_hash = _recorded_hash_if_unchanged(
                scanned_file, recorded_by_path.get(scanned_file.relative_path), scan_started_at
            )
            if known_hash is not None:
                # Size and mtime match the last scan: reuse the stored hash
                # instead of reading the file. Counted on both sides so the
                # drain loop below still ends when every submission is applied.
                submitted += 1
                _record(scanned_file, known_hash)
            else:
                future = executor.submit(hash_file, scanned_file.absolute_path)
                future.add_done_callback(partial(_on_done, scanned_file))
                submitted += 1
            _drain_ready()
        while processed < submitted:
            _apply(*completed.get())

    stats_repository.set_last_file_count(processed)

    return reconciler.reconcile(
        connection, generation, hashed_files, unreadable_paths=frozenset(unreadable_paths)
    )
