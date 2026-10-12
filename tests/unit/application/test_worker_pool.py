import threading
from concurrent.futures import Future
from threading import Event, Lock

from prismic.application.worker_pool import WorkerPool


def test_submit_runs_the_function_and_returns_its_result() -> None:
    pool = WorkerPool()
    try:
        future = pool.submit(lambda a, b: a + b, 2, 3)
        assert future.result(timeout=5) == 5
    finally:
        pool.shutdown()


def test_submit_runs_off_the_calling_thread() -> None:
    pool = WorkerPool()
    try:
        future = pool.submit(threading.get_ident)
        worker_thread_id = future.result(timeout=5)
        assert worker_thread_id != threading.get_ident()
    finally:
        pool.shutdown()


def test_context_manager_shuts_down_on_exit() -> None:
    with WorkerPool() as pool:
        future = pool.submit(lambda: "done")
        assert future.result(timeout=5) == "done"
    # The executor is shut down; submitting after exit raises.
    try:
        pool.submit(lambda: None)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected submit() after shutdown to raise")


def test_default_worker_pool_runs_two_tasks_but_queues_a_third() -> None:
    pool = WorkerPool()
    release = Event()
    two_started = Event()
    third_started = Event()
    lock = Lock()
    started = 0

    def blocked_task() -> None:
        nonlocal started
        with lock:
            started += 1
            if started == 2:
                two_started.set()
            elif started == 3:
                third_started.set()
        release.wait(timeout=3)

    futures: list[Future[None]] = [pool.submit(blocked_task) for _ in range(3)]
    try:
        assert two_started.wait(timeout=1)
        assert not third_started.wait(timeout=0.2)
    finally:
        release.set()
        pool.shutdown()

    assert all(future.result(timeout=1) is None for future in futures)
