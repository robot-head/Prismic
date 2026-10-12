from prismic.application.tag_ranking import promote_ranked_tags
from tests.unit._tag_records import A as _A
from tests.unit._tag_records import B as _B
from tests.unit._tag_records import C as _C
from tests.unit._tag_records import D as _D


def test_with_no_promotion_signal_the_original_order_is_kept() -> None:
    result = promote_ranked_tags(
        [_A, _B, _C],
        frozenset(),
        mega_popular_ids=frozenset(),
        correlations={},
        correlation_threshold=0.8,
    )

    assert result == [_A, _B, _C]


def test_a_correlated_unchecked_tag_moves_ahead_of_the_rest() -> None:
    # C correlates with A (checked); B does not.
    result = promote_ranked_tags(
        [_A, _B, _C],
        frozenset({_A.id}),
        mega_popular_ids=frozenset(),
        correlations={_C.id: 0.9},
        correlation_threshold=0.8,
    )

    assert result == [_A, _C, _B]


def test_a_correlation_below_threshold_is_not_promoted() -> None:
    result = promote_ranked_tags(
        [_A, _B, _C],
        frozenset({_A.id}),
        mega_popular_ids=frozenset(),
        correlations={_C.id: 0.5},
        correlation_threshold=0.8,
    )

    assert result == [_A, _B, _C]


def test_mega_popular_ranks_above_correlated() -> None:
    # D is mega-popular; C is correlated but not mega-popular.
    result = promote_ranked_tags(
        [_A, _B, _C, _D],
        frozenset({_A.id}),
        mega_popular_ids=frozenset({_D.id}),
        correlations={_C.id: 0.9},
        correlation_threshold=0.8,
    )

    assert result == [_A, _D, _C, _B]


def test_checked_tags_keep_their_exact_original_slots() -> None:
    # B is checked and sits between two unchecked tags; even though D
    # (unchecked) gets promoted, B must not move.
    result = promote_ranked_tags(
        [_A, _B, _C, _D],
        frozenset({_B.id}),
        mega_popular_ids=frozenset({_D.id}),
        correlations={},
        correlation_threshold=0.8,
    )

    assert result[1] == _B
    assert result == [_D, _B, _A, _C]


def test_multiple_correlated_tags_are_ranked_by_strength_descending() -> None:
    result = promote_ranked_tags(
        [_A, _B, _C, _D],
        frozenset(),
        mega_popular_ids=frozenset(),
        correlations={_B.id: 0.85, _C.id: 0.95, _D.id: 0.81},
        correlation_threshold=0.8,
    )

    assert result == [_C, _B, _D, _A]


def test_a_mega_popular_checked_tag_is_left_alone_not_double_counted() -> None:
    """A checked tag that also happens to be mega-popular doesn't get
    pulled out of its checked slot -- promotion only ever touches the
    unchecked tags."""
    result = promote_ranked_tags(
        [_A, _B, _C],
        frozenset({_A.id}),
        mega_popular_ids=frozenset({_A.id, _C.id}),
        correlations={},
        correlation_threshold=0.8,
    )

    assert result == [_A, _C, _B]
