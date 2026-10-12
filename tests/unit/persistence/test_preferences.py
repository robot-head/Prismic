from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from prismic.persistence import preferences
from prismic.persistence.preferences import (
    PreferencesStore,
    preferences_directory,
    preferences_file_path,
)


def test_preferences_directory_is_named_after_the_app() -> None:
    assert preferences_directory().name.lower() == "prismic"


def test_preferences_file_lives_inside_the_preferences_directory() -> None:
    assert preferences_file_path().parent == preferences_directory()


def test_preferences_location_is_outside_any_collection() -> None:
    # It's app-wide state, not per-collection — it must never live under a
    # collection root, unlike the `.prismic` database file.
    assert preferences_file_path().suffix != ".prismic"


def test_store_returns_nothing_when_the_file_does_not_exist(tmp_path: Path) -> None:
    assert PreferencesStore(tmp_path / "absent.json").load() == {}


def test_store_round_trips_what_it_saved(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "preferences.json")

    store.save({"shortcuts": {"view.focus_mode": "F8"}})

    assert store.load() == {"shortcuts": {"view.focus_mode": "F8"}}


def test_store_creates_the_preferences_directory_on_first_save(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "nested" / "deeper" / "preferences.json")

    store.save({"a": 1})

    assert store.path.exists()


@pytest.mark.parametrize(
    "contents",
    ["{ this is not json", "[1, 2, 3]"],
    ids=["corrupt-json", "non-object"],
)
def test_store_treats_invalid_or_non_object_files_as_empty(tmp_path: Path, contents: str) -> None:
    """Invalid preferences are conveniences, not authoritative data."""
    path = tmp_path / "preferences.json"
    path.write_text(contents, encoding="utf-8")

    assert PreferencesStore(path).load() == {}


def test_store_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    """The atomic-replace write goes through a `.tmp` sibling; a leftover
    one would sit next to the user's preferences forever."""
    directory = tmp_path / "prefs-only"
    store = PreferencesStore(directory / "preferences.json")

    store.save({"a": 1})

    assert sorted(p.name for p in directory.iterdir()) == ["preferences.json"]


@pytest.mark.parametrize(
    ("platform", "environment", "expected_parts"),
    [
        ("win32", {"APPDATA": "/profile/roaming"}, ("/profile/roaming", "Prismic")),
        ("win32", {}, ("home", "AppData", "Roaming", "Prismic")),
        (
            "darwin",
            {},
            ("home", "Library", "Application Support", "Prismic"),
        ),
        ("linux", {"XDG_CONFIG_HOME": "/config"}, ("/config", "prismic")),
        ("linux", {}, ("home", ".config", "prismic")),
        ("z-other", {"XDG_CONFIG_HOME": "/fallback"}, ("/fallback", "prismic")),
    ],
)
def test_preferences_directory_uses_platform_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    environment: dict[str, str],
    expected_parts: tuple[str, ...],
) -> None:
    home = tmp_path / "home"
    distinct_platform = bytearray(platform.encode()).decode("ascii")
    monkeypatch.setattr(preferences, "sys", SimpleNamespace(platform=distinct_platform))
    monkeypatch.setattr(preferences.Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    actual = preferences.preferences_directory()
    expected = (
        home.joinpath(*expected_parts[1:])
        if expected_parts[0] == "home"
        else Path(expected_parts[0]).joinpath(*expected_parts[1:])
    )

    assert actual == expected


def test_preferences_save_sorted_json_with_two_space_indentation(tmp_path: Path) -> None:
    store = preferences.PreferencesStore(tmp_path / "preferences.json")

    store.save({"z": 1, "a": 2})

    assert store.path.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "z": 1\n}'
