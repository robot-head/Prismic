import pytest

from prismic.application.tag_recency import TagRecencyTracker
from prismic.domain.tag import Tag
from tests.unit._tag_records import A as _A
from tests.unit._tag_records import B as _B
from tests.unit._tag_records import C as _C


def test_unclicked_tags_keep_their_given_order() -> None:
    tracker = TagRecencyTracker(_clock=lambda: 0.0)

    assert tracker.order([_A, _B, _C]) == [_A, _B, _C]


def test_a_recently_clicked_tag_moves_to_the_front() -> None:
    clock = [0.0]
    tracker = TagRecencyTracker(_clock=lambda: clock[0])

    tracker.record_click(_C.id)

    assert tracker.order([_A, _B, _C]) == [_C, _A, _B]


@pytest.mark.parametrize(
    ("clicks", "expected_order"),
    [
        (((_A.id, 0.0), (_B.id, 10.0)), [_B, _A, _C]),
        (((_A.id, 0.0), (_B.id, 10.0), (_A.id, 20.0)), [_A, _B, _C]),
    ],
    ids=["most-recent-first", "reclick-refreshes-recency"],
)
def test_most_recent_click_determines_the_tag_order(
    clicks: tuple[tuple[int, float], ...], expected_order: list[Tag]
) -> None:
    clock = [0.0]
    tracker = TagRecencyTracker(_clock=lambda: clock[0])

    for tag_id, timestamp in clicks:
        clock[0] = timestamp
        tracker.record_click(tag_id)

    assert tracker.order([_A, _B, _C]) == expected_order


@pytest.mark.parametrize("seconds_ago", [30 * 60 + 1, 30 * 60], ids=["expired", "boundary"])
def test_a_recent_clicks_cutoff_controls_the_original_order(seconds_ago: int) -> None:
    clock = [0.0]
    tracker = TagRecencyTracker(_clock=lambda: clock[0])

    tracker.record_click(_A.id)
    clock[0] = seconds_ago

    assert tracker.order([_A, _B, _C]) == [_A, _B, _C]
