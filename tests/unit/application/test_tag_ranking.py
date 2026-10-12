from collections import defaultdict

import pytest

from prismic.application.tag_ranking import promote_ranked_tags
from prismic.domain.tag import Tag
from tests.unit._tag_records import A as _A
from tests.unit._tag_records import B as _B
from tests.unit._tag_records import C as _C
from tests.unit._tag_records import D as _D


def _rank(
    tags: list[Tag],
    checked_ids: frozenset[int] = frozenset(),
    *,
    mega_popular_ids: frozenset[int] = frozenset(),
    correlations: dict[int, float] | None = None,
) -> list[Tag]:
    return promote_ranked_tags(
        tags,
        checked_ids,
        mega_popular_ids=mega_popular_ids,
        correlations=correlations or {},
        correlation_threshold=0.8,
    )


def test_with_no_promotion_signal_the_original_order_is_kept() -> None:
    result = _rank([_A, _B, _C])

    assert result == [_A, _B, _C]


@pytest.mark.parametrize(
    ("tags", "mega_popular_ids", "correlations", "expected"),
    [
        ([_A, _B, _C], frozenset(), {_C.id: 0.9}, [_A, _C, _B]),
        ([_A, _B, _C, _D], frozenset({_D.id}), {_C.id: 0.9}, [_A, _D, _C, _B]),
    ],
    ids=["correlated-tag", "mega-popular-before-correlated"],
)
def test_unchecked_promotion_orders_mega_popular_before_correlated(
    tags: list[Tag],
    mega_popular_ids: frozenset[int],
    correlations: dict[int, float],
    expected: list[Tag],
) -> None:
    # C correlates with A (checked); the second case also makes D mega-popular.
    result = _rank(
        tags,
        frozenset({_A.id}),
        mega_popular_ids=mega_popular_ids,
        correlations=correlations,
    )

    assert result == expected


def test_a_correlation_below_threshold_is_not_promoted() -> None:
    result = _rank(
        [_A, _B, _C],
        frozenset({_A.id}),
        correlations={_C.id: 0.5},
    )

    assert result == [_A, _B, _C]


def test_checked_tags_keep_their_exact_original_slots() -> None:
    # B is checked and sits between two unchecked tags; even though D
    # (unchecked) gets promoted, B must not move.
    result = _rank(
        [_A, _B, _C, _D],
        frozenset({_B.id}),
        mega_popular_ids=frozenset({_D.id}),
    )

    assert result[1] == _B
    assert result == [_D, _B, _A, _C]


def test_multiple_correlated_tags_are_ranked_by_strength_descending() -> None:
    result = _rank(
        [_A, _B, _C, _D],
        correlations={_B.id: 0.85, _C.id: 0.95, _D.id: 0.81},
    )

    assert result == [_C, _B, _D, _A]


def test_a_mega_popular_checked_tag_is_left_alone_not_double_counted() -> None:
    """A checked tag that also happens to be mega-popular doesn't get
    pulled out of its checked slot -- promotion only ever touches the
    unchecked tags."""
    result = _rank(
        [_A, _B, _C],
        frozenset({_A.id}),
        mega_popular_ids=frozenset({_A.id, _C.id}),
    )

    assert result == [_A, _C, _B]


def test_correlation_at_the_threshold_is_promoted() -> None:
    tags = [Tag(id=1, name="checked"), Tag(id=2, name="exact"), Tag(id=3, name="other")]

    ranked = promote_ranked_tags(
        tags,
        frozenset({1}),
        mega_popular_ids=frozenset(),
        correlations={2: 0.8},
        correlation_threshold=0.8,
    )

    assert ranked == [tags[0], tags[1], tags[2]]


def test_missing_correlation_uses_zero_when_threshold_is_zero() -> None:
    missing = Tag(id=1, name="missing")
    zero = Tag(id=2, name="zero")
    strong = Tag(id=3, name="strong")
    correlations: defaultdict[int, float] = defaultdict(float, {zero.id: 0.0, strong.id: 0.3})

    ranked = promote_ranked_tags(
        [missing, zero, strong],
        frozenset(),
        mega_popular_ids=frozenset(),
        correlations=correlations,
        correlation_threshold=0.0,
    )

    assert ranked == [strong, missing, zero]
