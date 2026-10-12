from collections import defaultdict
from pathlib import Path

from prismic.application.input.chord import ChordState
from prismic.application.tag_ranking import promote_ranked_tags
from prismic.application.tag_ranking_settings import TagRankingSettingsStore
from prismic.domain.tag import Tag
from prismic.persistence.preferences import PreferencesStore


def test_default_chord_timeout_allows_a_key_until_one_second() -> None:
    chord = ChordState()
    chord.press("g")

    assert chord.advance_time(0.999) is False
    assert chord.is_pending is True
    assert chord.advance_time(0.001) is True
    assert chord.is_pending is False


def test_nonmatching_lexicographically_later_key_cancels_prefix() -> None:
    chord = ChordState()
    chord.press("g")

    assert chord.match({("h", "h"): "go_home"}) is None
    assert chord.is_pending is False


def test_default_mega_popular_threshold_is_fifteen_percent(tmp_path: Path) -> None:
    settings = TagRankingSettingsStore(PreferencesStore(tmp_path / "preferences.json"))

    assert settings.load().mega_popular_threshold == 0.15


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
