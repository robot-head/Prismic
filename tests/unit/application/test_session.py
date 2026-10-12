from pathlib import Path
from threading import Event, Thread

from prismic.application import session as session_module
from prismic.application.session import PrismicSession
from prismic.indexing.reconciler import ReconciliationResult


def test_close_waits_for_an_in_flight_reconciliation(tmp_path: Path, monkeypatch) -> None:
    collection_root = tmp_path / "collection"
    collection_root.mkdir()
    worker_started = Event()
    allow_worker_to_finish = Event()
    close_started = Event()
    close_finished = Event()
    sessions: list[PrismicSession] = []
    errors: list[BaseException] = []

    def blocked_reconciliation(*args, **kwargs) -> ReconciliationResult:
        worker_started.set()
        if not allow_worker_to_finish.wait(timeout=5):
            raise TimeoutError("test did not release the reconciliation worker")
        return ReconciliationResult(applied=True)

    monkeypatch.setattr(session_module, "run_reconciliation", blocked_reconciliation)

    def open_and_close_session() -> None:
        try:
            session = PrismicSession.open(collection_root)
            sessions.append(session)
            if not worker_started.wait(timeout=2):
                raise TimeoutError("initial reconciliation did not start")
            close_started.set()
            session.close()
        except BaseException as error:
            errors.append(error)
        finally:
            close_finished.set()

    closer = Thread(target=open_and_close_session, daemon=True)
    closer.start()
    try:
        assert close_started.wait(timeout=2)
        assert not close_finished.wait(timeout=0.2)
    finally:
        allow_worker_to_finish.set()
        closer.join(timeout=5)

    assert not closer.is_alive()
    assert close_finished.is_set()
    assert errors == []
    assert len(sessions) == 1
    assert sessions[0].initial_reconciliation.result(timeout=1).applied
