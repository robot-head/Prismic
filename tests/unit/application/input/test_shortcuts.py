from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from prismic.application.input import shortcuts
from prismic.application.input.shortcuts import (
    QUICK_SELECT_SLOT_COUNT,
    SHORTCUTS,
    ShortcutBindings,
    ShortcutScope,
    keycaps,
)
from prismic.persistence.preferences import PreferencesStore


@pytest.fixture
def bindings(tmp_path: Path) -> ShortcutBindings:
    return ShortcutBindings(PreferencesStore(tmp_path / "preferences.json"))


def _custom_open_collection_binding(
    tmp_path: Path,
) -> tuple[PreferencesStore, ShortcutBindings]:
    store = PreferencesStore(tmp_path / "preferences.json")
    bindings = ShortcutBindings(store)
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "F5")
    return store, bindings


# -- The registry itself ----------------------------------------------------


def test_every_shortcut_id_is_unique() -> None:
    ids = [definition.id for definition in SHORTCUTS]
    assert len(ids) == len(set(ids))


def test_every_shortcut_has_a_label_and_a_description() -> None:
    """Settings renders both verbatim -- an empty one would ship a blank
    row rather than fail anywhere."""
    for definition in SHORTCUTS:
        assert definition.label.strip(), definition.id
        assert definition.description.strip(), definition.id


def test_shortcut_definitions_are_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        SHORTCUTS[0].label = "changed"  # type: ignore[misc]


def test_categories_group_contiguously() -> None:
    """Settings starts a new heading each time the category changes while
    walking `SHORTCUTS` in order, so a category that reappears after
    another one would render as two separate headings with the same
    name."""
    seen: list[str] = []
    for definition in SHORTCUTS:
        if not seen or seen[-1] != definition.category:
            assert definition.category not in seen, definition.category
            seen.append(definition.category)


def test_defaults_do_not_collide_within_a_scope(bindings: ShortcutBindings) -> None:
    for definition in SHORTCUTS:
        assert bindings.conflicts(definition.id, definition.default) == (), definition.id


def test_focus_mode_and_play_pause_share_space_across_scopes(
    bindings: ShortcutBindings,
) -> None:
    """The one deliberate double-booking in the defaults: both are Space,
    resolved by input context rather than by the key (see keyboard.py).
    Different scopes, so it isn't reported as a conflict."""
    assert bindings.binding(shortcuts.FOCUS_MODE) == "Space"
    assert bindings.binding(shortcuts.VIEWER_PLAY_PAUSE) == "Space"
    assert bindings.conflicts(shortcuts.FOCUS_MODE, "Space") == ()


def test_every_quick_select_slot_has_a_shortcut(bindings: ShortcutBindings) -> None:
    for slot in range(shortcuts.QUICK_SELECT_SLOT_COUNT):
        assert bindings.binding(shortcuts.quick_select_id(slot))


def test_quick_select_ids_are_one_based() -> None:
    for slot in range(shortcuts.QUICK_SELECT_SLOT_COUNT):
        assert shortcuts.quick_select_id(slot) == f"tagging.quick_select_{slot + 1}"


def test_quick_select_defaults_are_the_digit_row(bindings: ShortcutBindings) -> None:
    assert bindings.quick_select_slot("1") == 0
    assert bindings.quick_select_slot("9") == 8
    assert bindings.quick_select_slot("0") == 9
    assert bindings.quick_select_slot("Ctrl+1") is None


def test_type_literally_modifier_is_its_own_configurable_shortcut(
    bindings: ShortcutBindings,
) -> None:
    """Holding a modifier plus a quick-select key types the character
    instead of toggling, while a tag search box has focus (see
    `MainWindow._handle_quick_select_while_typing`) -- which modifier is
    itself a shortcut, not a hard-coded "Ctrl", so rebinding it changes
    the escape hatch for every quick-select slot at once."""
    assert bindings.binding(shortcuts.TYPE_LITERALLY_MODIFIER) == "Ctrl"
    assert bindings.literal_typing_modifier() == "Ctrl"

    bindings.set_binding(shortcuts.TYPE_LITERALLY_MODIFIER, "Alt")

    assert bindings.literal_typing_modifier() == "Alt"


def test_the_type_literally_modifier_does_not_conflict_with_the_numbering_swap(
    bindings: ShortcutBindings,
) -> None:
    """Both default to "Ctrl" -- one fires on tapping it alone, the other
    only matters combined with some other key, so a user can have both on
    Ctrl at once with neither ever getting in the other's way. Different
    scopes are what keeps that from being reported as a conflict."""
    assert bindings.conflicts(shortcuts.TYPE_LITERALLY_MODIFIER, "Ctrl") == ()
    assert bindings.conflicts(shortcuts.SWAP_TAG_NUMBERING, "Ctrl") == ()


def test_only_the_first_quick_select_description_explains_the_escape_hatch() -> None:
    """Easy to miss since it isn't a separate, independently bindable
    shortcut *per slot* -- Settings is the one place that could say so.
    Repeating the same paragraph on all ten rows would just bury it."""
    first = shortcuts.definition(shortcuts.quick_select_id(0)).description
    assert "Type the key instead of toggling" in first

    for slot in range(1, shortcuts.QUICK_SELECT_SLOT_COUNT):
        description = shortcuts.definition(shortcuts.quick_select_id(slot)).description
        assert "Type the key instead of toggling" not in description
        assert "modifier" not in description.lower()


# -- keycaps ------------------------------------------------------------------


def test_keycaps_splits_a_combination_into_one_label_per_key() -> None:
    assert keycaps("Ctrl+Shift+O") == ("Ctrl", "Shift", "O")
    assert keycaps("Space") == ("Space",)


def test_keycaps_of_an_unbound_shortcut_is_empty() -> None:
    assert keycaps("") == ()


def test_keycaps_handles_the_plus_key_itself() -> None:
    """A naive split on "+" turns "Ctrl++" into an empty trailing segment
    instead of the "+" key it actually names."""
    assert keycaps("Ctrl++") == ("Ctrl", "+")


# -- Reading and writing bindings --------------------------------------------


def test_an_untouched_shortcut_reports_its_default(bindings: ShortcutBindings) -> None:
    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"
    assert bindings.is_default(shortcuts.OPEN_COLLECTION_FOLDER)


def test_setting_a_binding_overrides_the_default(bindings: ShortcutBindings) -> None:
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "F5")

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "F5"
    assert not bindings.is_default(shortcuts.OPEN_COLLECTION_FOLDER)


def test_setting_a_binding_back_to_its_default_clears_the_override(
    bindings: ShortcutBindings,
) -> None:
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "F5")

    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "Ctrl+O")

    assert bindings.is_default(shortcuts.OPEN_COLLECTION_FOLDER)


def test_reset_restores_the_default(bindings: ShortcutBindings) -> None:
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "F5")

    bindings.reset(shortcuts.OPEN_COLLECTION_FOLDER)

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"


def test_reset_all_restores_every_default(bindings: ShortcutBindings) -> None:
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "F5")
    bindings.set_binding(shortcuts.NAVIGATE_NEXT, "F6")

    bindings.reset_all()

    assert all(bindings.is_default(definition.id) for definition in SHORTCUTS)


def test_a_shortcut_can_be_unbound(bindings: ShortcutBindings) -> None:
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "")

    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == ""
    assert bindings.shortcut_for("") is None  # an unbound one is never "pressed"


def test_shortcut_for_finds_the_command_a_key_triggers(bindings: ShortcutBindings) -> None:
    assert bindings.shortcut_for("Ctrl+,") == shortcuts.OPEN_SETTINGS
    assert bindings.shortcut_for("F5") is None

    bindings.set_binding(shortcuts.OPEN_SETTINGS, "F5")

    assert bindings.shortcut_for("F5") == shortcuts.OPEN_SETTINGS
    assert bindings.shortcut_for("Ctrl+,") is None


def test_shortcut_for_only_searches_the_requested_scope(bindings: ShortcutBindings) -> None:
    assert bindings.shortcut_for("Space", ShortcutScope.GLOBAL) == shortcuts.FOCUS_MODE
    assert bindings.shortcut_for("Space", ShortcutScope.VIEWER) == shortcuts.VIEWER_PLAY_PAUSE


def test_binding_lookups_compare_equal_strings_by_value(bindings: ShortcutBindings) -> None:
    shortcut_binding = "Ctrl+Shift+F9"
    bindings.set_binding(shortcuts.OPEN_SETTINGS, shortcut_binding)
    bindings.set_binding(shortcuts.quick_select_id(0), shortcut_binding)
    equal_binding = ("!" + shortcut_binding)[1:]
    assert equal_binding == shortcut_binding
    assert equal_binding is not shortcut_binding

    assert bindings.shortcut_for(equal_binding) == shortcuts.OPEN_SETTINGS
    assert bindings.quick_select_slot(equal_binding) == 0


def test_conflicts_excludes_an_equal_shortcut_id_by_value(bindings: ShortcutBindings) -> None:
    shortcut_id = shortcuts.OPEN_COLLECTION_FOLDER
    equal_id = ("!" + shortcut_id)[1:]
    assert equal_id == shortcut_id
    assert equal_id is not shortcut_id

    assert bindings.conflicts(equal_id, bindings.binding(shortcut_id)) == ()


def test_definitions_is_exposed_as_a_property(bindings: ShortcutBindings) -> None:
    assert bindings.definitions is SHORTCUTS


def test_conflicts_reports_another_shortcut_on_the_same_key(
    bindings: ShortcutBindings,
) -> None:
    assert bindings.conflicts(shortcuts.OPEN_COLLECTION_FOLDER, "Ctrl+T") == (
        shortcuts.TOGGLE_THUMBNAILS,
    )


def test_conflicts_ignores_the_shortcut_being_asked_about(bindings: ShortcutBindings) -> None:
    assert bindings.conflicts(shortcuts.OPEN_SETTINGS, "Ctrl+,") == ()


def test_a_bare_modifier_is_a_tap_gesture(bindings: ShortcutBindings) -> None:
    """A modifier on its own can't be a key press -- holding Ctrl is how
    half the other shortcuts start -- so a binding of just "Ctrl" means
    the tap. The numbering swap defaults to one."""
    assert shortcuts.is_modifier_only("Ctrl")
    assert bindings.binding(shortcuts.SWAP_TAG_NUMBERING) == "Ctrl"


def test_a_combination_is_not_a_tap_gesture() -> None:
    assert not shortcuts.is_modifier_only("Ctrl+R")
    assert not shortcuts.is_modifier_only("R")
    assert not shortcuts.is_modifier_only("")


def test_nothing_in_the_registry_restricts_which_shortcuts_can_be_tapped(
    bindings: ShortcutBindings,
) -> None:
    """The gesture is a property of what the user bound, not of the
    command -- so any shortcut takes a bare modifier, and it resolves
    like any other binding."""
    bindings.set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "Alt")

    assert bindings.shortcut_for("Alt") == shortcuts.OPEN_COLLECTION_FOLDER
    assert shortcuts.is_modifier_only(bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER))


def test_a_modifier_binding_collides_with_another_like_any_other_key(
    bindings: ShortcutBindings,
) -> None:
    assert bindings.conflicts(shortcuts.OPEN_COLLECTION_FOLDER, "Ctrl") == (
        shortcuts.SWAP_TAG_NUMBERING,
    )


# -- Persistence ---------------------------------------------------------------


def test_overrides_survive_a_reload(tmp_path: Path) -> None:
    store, _bindings = _custom_open_collection_binding(tmp_path)

    assert ShortcutBindings(store).binding(shortcuts.OPEN_COLLECTION_FOLDER) == "F5"


def test_only_overrides_are_written_not_the_whole_table(tmp_path: Path) -> None:
    """So a changed default reaches everyone who hadn't customized that
    particular shortcut, instead of being frozen at whatever the table
    said the first time the app ran."""
    store, _bindings = _custom_open_collection_binding(tmp_path)

    assert store.load()["shortcuts"] == {shortcuts.OPEN_COLLECTION_FOLDER: "F5"}


def test_resetting_the_last_override_removes_the_section_entirely(tmp_path: Path) -> None:
    store, bindings = _custom_open_collection_binding(tmp_path)

    bindings.reset(shortcuts.OPEN_COLLECTION_FOLDER)

    assert "shortcuts" not in store.load()


def test_unrelated_preferences_are_left_alone(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "preferences.json")
    store.save({"something-else": 42})

    ShortcutBindings(store).set_binding(shortcuts.OPEN_COLLECTION_FOLDER, "F5")

    assert store.load()["something-else"] == 42


def test_an_unknown_shortcut_id_in_the_file_is_ignored(tmp_path: Path) -> None:
    """The preferences file is plain, hand-editable JSON -- a stale id
    from an older build shouldn't crash startup or survive the next
    save."""
    store = PreferencesStore(tmp_path / "preferences.json")
    store.save({"shortcuts": {"nope.not.a.shortcut": "F5", shortcuts.OPEN_COLLECTION_FOLDER: "F6"}})

    bindings = ShortcutBindings(store)
    bindings.set_binding(shortcuts.NAVIGATE_NEXT, "F7")

    assert "nope.not.a.shortcut" not in store.load()["shortcuts"]
    assert bindings.binding(shortcuts.OPEN_COLLECTION_FOLDER) == "F6"


def test_a_non_string_binding_in_the_file_is_ignored(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "preferences.json")
    store.save({"shortcuts": {shortcuts.OPEN_COLLECTION_FOLDER: 5}})

    assert ShortcutBindings(store).binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"


def test_a_malformed_shortcuts_section_is_ignored(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "preferences.json")
    store.save({"shortcuts": "not a mapping"})

    assert ShortcutBindings(store).binding(shortcuts.OPEN_COLLECTION_FOLDER) == "Ctrl+O"


@pytest.mark.parametrize(
    "slot",
    range(QUICK_SELECT_SLOT_COUNT),
    ids=lambda slot: f"slot-{slot + 1}",
)
def test_quick_select_definitions_number_every_slot_and_explain_typing_once(slot: int) -> None:
    definition = shortcuts.definition(shortcuts.quick_select_id(slot))
    number = slot + 1

    assert definition.label == f"Toggle numbered tag {number}"
    assert f"numbers {number} " in definition.description
    assert definition.description.startswith(
        f"Toggle whichever tag the Edit list currently numbers {number} "
    )
    assert ("Type the key instead of toggling" in definition.description) is (slot == 0)
    assert ("Still works while a tag search box has focus" in definition.description) is (slot == 0)


def test_keycaps_parse_multiple_modifiers_in_noncanonical_order() -> None:
    assert keycaps("Alt+Ctrl+Shift+K") == ("Alt", "Ctrl", "Shift", "K")
