"""PrismicSession: the single active collection session.

Composes the collection root, database connection, repositories,
application state, command dispatcher, undo history, filesystem
reconciler, and a background worker pool — per overview section 1. Only one
session is meant to be active per process (nothing here enforces that at
the interpreter level; it's a usage discipline the UI layer follows, since
Prismic only ever shows one main window onto one collection).
"""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path

from prismic.application.commands.base import Command
from prismic.application.dispatcher import CommandDispatcher
from prismic.application.history import History
from prismic.application.state import ApplicationState
from prismic.application.tag_recency import TagRecencyTracker
from prismic.application.worker_pool import WorkerPool
from prismic.context import ClosableContext
from prismic.domain.collection import Collection
from prismic.indexing.reconciler import (
    ProgressCallback,
    Reconciler,
    ReconciliationResult,
    run_reconciliation,
)
from prismic.persistence import database
from prismic.persistence.collection import OpenCollection, open_collection
from prismic.persistence.repositories.mapping_repository import MappingRepository
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.scan_stats_repository import ScanStatsRepository
from prismic.persistence.repositories.tag_correlation_repository import TagCorrelationRepository
from prismic.persistence.repositories.tag_repository import TagRepository


class PrismicSession(ClosableContext):
    """A fully-opened collection, ready for commands and queries.

    Construction matches Phase 1's open/close lifecycle: `open()` either
    returns a complete session or raises with nothing partially built (it
    delegates the opening itself to `persistence.collection.open_collection`,
    which already guarantees this). Call `close()` — or use as a context
    manager — to release the collection's connection, its lock, and the
    worker pool.
    """

    def __init__(self, opened: OpenCollection, on_progress: ProgressCallback | None = None) -> None:
        self._opened = opened
        self.tags = TagRepository(opened.connection)
        self.media = MediaRepository(opened.connection)
        self.mappings = MappingRepository(opened.connection)
        self.tag_correlations = TagCorrelationRepository(opened.connection)
        self.state = ApplicationState()
        self.tag_recency = TagRecencyTracker()
        self.history = History()
        self.dispatcher = CommandDispatcher(
            opened.connection, self.state, self.tags, self.media, self.mappings, self.history
        )
        self.reconciler = Reconciler()
        self.worker_pool = WorkerPool()
        self.state.recompute(self.media, self.mappings)

        # Whether the scan this constructor is about to kick off is this
        # root's very first (no `scan_stats` row written yet, so a stale
        # progress denominator would be misleadingly "0 of 0" rather than
        # meaningfully absent) -- read synchronously, strictly before
        # `_scan_in_background` ever starts the worker thread that would
        # eventually overwrite it, so there's no race to get this wrong.
        # `rescan()` recomputes it the same way before every later scan too,
        # so it always reflects whichever scan is currently in flight.
        self.is_first_scan = self._compute_is_first_scan()
        self.initial_reconciliation: Future[ReconciliationResult] = self._scan_in_background(
            on_progress
        )

    @classmethod
    def open(cls, path: Path, on_progress: ProgressCallback | None = None) -> PrismicSession:
        return cls(open_collection(path), on_progress)

    @property
    def collection(self) -> Collection:
        return self._opened.collection

    def execute(self, command: Command) -> None:
        self.dispatcher.execute(command)

    def undo(self) -> bool:
        return self.dispatcher.undo()

    def redo(self) -> bool:
        return self.dispatcher.redo()

    def rescan(self, on_progress: ProgressCallback | None = None) -> Future[ReconciliationResult]:
        """Kick off a fresh background scan/hash/reconcile pass.

        Any reconciliation already in flight becomes stale the moment this
        one begins (`Reconciler.begin_scan()` bumps the generation), so an
        in-flight pass finishing afterward is discarded rather than applied
        out of order.

        This does **not** update `state` when it completes — the worker
        thread only ever touches its own connection (see `_scan_in_background`),
        never the main-thread repositories `state.recompute` needs. The
        caller must call `refresh_state()` itself, from the main thread,
        once it observes the returned future is done. Marshaling that
        "future is done" notification onto the GUI thread is Phase 5's job
        (e.g. a queued Qt signal); nothing here assumes a GUI event loop
        exists.

        `on_progress`, if given, is called from the *background* thread as
        the scan proceeds (see `indexing.reconciler.run_reconciliation`) —
        a caller that needs it on the GUI thread must marshal it itself,
        the same way `FutureWatcher` marshals the future's completion.
        """
        self.is_first_scan = self._compute_is_first_scan()
        return self._scan_in_background(on_progress)

    def refresh_state(self) -> None:
        """Recompute `state` from the database's current contents.

        Call this from the main thread after a background reconciliation
        (`initial_reconciliation` or a `rescan()` future) completes, so newly
        discovered/changed/missing media is reflected in the result set.
        """
        self.state.recompute(self.media, self.mappings)

    def _compute_is_first_scan(self) -> bool:
        """Whether `scan_stats` holds no count yet, i.e. this root has never
        completed a scan -- read on the main thread, from the main-thread
        connection, never the background worker's own."""
        return ScanStatsRepository(self._opened.connection).get_last_file_count() == 0

    def _scan_in_background(
        self, on_progress: ProgressCallback | None
    ) -> Future[ReconciliationResult]:
        generation = self.reconciler.begin_scan()
        collection = self.collection
        database_path = collection.database_path

        def _task() -> ReconciliationResult:
            # A background thread must never touch the main session's
            # connection (see indexing.reconciler.Reconciler) — it opens its
            # own connection to the same file for the duration of this task.
            worker_connection = database.connect(database_path)
            try:
                return run_reconciliation(
                    self.reconciler,
                    collection,
                    generation,
                    worker_connection,
                    on_progress=on_progress,
                )
            finally:
                worker_connection.close()

        return self.worker_pool.submit(_task)

    def close(self) -> None:
        # Let in-flight background work finish before releasing the lock and
        # main connection underneath it.
        self.worker_pool.shutdown(wait=True)
        self._opened.close()
