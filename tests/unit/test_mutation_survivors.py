from concurrent.futures import Future
from dataclasses import FrozenInstanceError
from threading import Event, Lock

import pytest

from prismic.application.input.shortcuts import (
    QUICK_SELECT_SLOT_COUNT,
    definition,
    quick_select_id,
)
from prismic.application.state import ApplicationState
from prismic.application.tag_recency import TagRecencyTracker
from prismic.application.worker_pool import WorkerPool
from prismic.domain.tag import Tag


def test_quick_select_definitions_number_every_slot_and_explain_typing_once() -> None:
    for slot in range(QUICK_SELECT_SLOT_COUNT):
        item = definition(quick_select_id(slot))

        assert item.label == f"Toggle numbered tag {slot + 1}"
        assert item.description.startswith(
            f"Toggle whichever tag the Edit list currently numbers {slot + 1} "
        )
        assert ("Still works while a tag search box has focus" in item.description) == (slot == 0)


def test_recency_window_keeps_a_one_second_old_click_recent() -> None:
    clock = [0.0]
    tracker = TagRecencyTracker(_clock=lambda: clock[0])
    clicked = Tag(id=3, name="clicked")
    other = Tag(id=1, name="other")
    tracker.record_click(clicked.id)
    clock[0] = 1.0

    assert tracker.order([other, clicked]) == [clicked, other]


def test_expired_recency_returns_to_the_callers_order() -> None:
    clock = [0.0]
    tracker = TagRecencyTracker(_clock=lambda: clock[0])
    clicked = Tag(id=3, name="clicked")
    other = Tag(id=1, name="other")
    tracker.record_click(clicked.id)
    clock[0] = 30 * 60 + 1

    assert tracker.order([other, clicked]) == [other, clicked]


def test_recency_window_includes_the_exact_boundary() -> None:
    clock = [0.0]
    tracker = TagRecencyTracker(_clock=lambda: clock[0])
    clicked = Tag(id=3, name="clicked")
    other = Tag(id=1, name="other")
    tracker.record_click(clicked.id)
    clock[0] = 30 * 60

    assert tracker.order([other, clicked]) == [clicked, other]


def test_current_item_fallback_uses_the_first_new_result() -> None:
    state = ApplicationState(result_set=[40, 50])

    assert state._resolve_current_item([10, 20, 30], 20) == 40


def test_tag_value_is_immutable() -> None:
    tag = Tag(id=1, name="vacation")

    with pytest.raises(FrozenInstanceError):
        tag.name = "renamed"  # type: ignore[misc]


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
