from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from prismic.application.tag_ranking_settings import (
    DEFAULT_CORRELATION_THRESHOLD,
    DEFAULT_MEGA_POPULAR_THRESHOLD,
    TagRankingSettings,
    TagRankingSettingsStore,
)
from prismic.persistence.preferences import PreferencesStore


def _store(tmp_path: Path) -> TagRankingSettingsStore:
    return TagRankingSettingsStore(PreferencesStore(tmp_path / "preferences.json"))


def test_load_returns_defaults_when_nothing_saved(tmp_path: Path) -> None:
    settings = _store(tmp_path).load()

    assert settings.correlation_threshold == 0.8
    assert settings.correlation_threshold == DEFAULT_CORRELATION_THRESHOLD
    assert settings.mega_popular_threshold == DEFAULT_MEGA_POPULAR_THRESHOLD


def test_fraction_settings_accept_both_inclusive_boundaries(tmp_path: Path) -> None:
    preferences = PreferencesStore(tmp_path / "preferences.json")
    preferences.save({"tag_ranking": {"correlation_threshold": 0.0, "mega_popular_threshold": 1}})

    settings = TagRankingSettingsStore(preferences).load()

    assert settings.correlation_threshold == 0.0
    assert settings.mega_popular_threshold == 1.0


def test_settings_value_is_immutable(tmp_path: Path) -> None:
    settings = _store(tmp_path).load()

    with pytest.raises(FrozenInstanceError):
        settings.correlation_threshold = 0.5  # type: ignore[misc]


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.save(TagRankingSettings(correlation_threshold=0.6, mega_popular_threshold=0.25))

    settings = store.load()
    assert settings.correlation_threshold == 0.6
    assert settings.mega_popular_threshold == 0.25


def test_load_ignores_an_out_of_range_stored_value(tmp_path: Path) -> None:
    preferences = PreferencesStore(tmp_path / "preferences.json")
    preferences.save({"tag_ranking": {"correlation_threshold": 5.0, "mega_popular_threshold": -1}})

    settings = TagRankingSettingsStore(preferences).load()

    assert settings.correlation_threshold == DEFAULT_CORRELATION_THRESHOLD
    assert settings.mega_popular_threshold == DEFAULT_MEGA_POPULAR_THRESHOLD


def test_load_ignores_a_non_numeric_stored_value(tmp_path: Path) -> None:
    preferences = PreferencesStore(tmp_path / "preferences.json")
    preferences.save({"tag_ranking": {"correlation_threshold": "high"}})

    settings = TagRankingSettingsStore(preferences).load()

    assert settings.correlation_threshold == DEFAULT_CORRELATION_THRESHOLD


def test_save_does_not_disturb_other_preferences(tmp_path: Path) -> None:
    preferences = PreferencesStore(tmp_path / "preferences.json")
    preferences.save({"shortcuts": {"dismiss": "Escape"}})

    TagRankingSettingsStore(preferences).save(TagRankingSettings())

    assert preferences.load()["shortcuts"] == {"dismiss": "Escape"}
