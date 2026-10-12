from pathlib import Path

import pytest

import prismic.application.tag_ranking_settings as ranking_settings
from prismic.application.commands import TagDeleteCommand
from prismic.application.commands.base import Command, CommandContext
from prismic.application.commands.mapping_commands import MappingSetForManyCommand
from prismic.application.input.chord import ChordState
from prismic.application.input.resolver import InputEvent
from prismic.application.input.shortcuts import SHORTCUTS, keycaps
from prismic.application.state import ApplicationState
from prismic.persistence.preferences import PreferencesStore
from tests.unit._record_contracts import assert_frozen_and_slotted


def test_commands_require_execute_and_undo_implementations() -> None:
    class MissingExecute(Command):
        def undo(self, context: CommandContext) -> None:
            pass

    class MissingUndo(Command):
        def execute(self, context: CommandContext) -> None:
            pass

    with pytest.raises(TypeError):
        MissingExecute()
    with pytest.raises(TypeError):
        MissingUndo()


def test_command_private_state_is_not_constructor_input_or_repr() -> None:
    mapping_command = MappingSetForManyCommand(media_ids=frozenset(), tag_id=1, adding=True)
    assert "_changed_media_ids" not in repr(mapping_command)
    with pytest.raises(TypeError):
        MappingSetForManyCommand(
            media_ids=frozenset(), tag_id=1, adding=True, _changed_media_ids=[1]
        )

    delete_command = TagDeleteCommand(tag_id=1)
    assert "_was_selected" not in repr(delete_command)
    with pytest.raises(TypeError):
        TagDeleteCommand(tag_id=1, _was_selected=True)


def test_chord_internal_state_is_not_constructor_input_or_repr() -> None:
    chord = ChordState()
    chord.press("g")

    assert repr(chord) == "ChordState(timeout_seconds=1.0)"
    with pytest.raises(TypeError):
        ChordState(_pending_keys=["g"])
    with pytest.raises(TypeError):
        ChordState(_elapsed_since_last_key=0.5)


def test_public_input_and_settings_records_are_frozen_and_slotted() -> None:
    records: tuple[tuple[object, str], ...] = (
        (InputEvent(key="a"), "key"),
        (SHORTCUTS[0], "label"),
        (ranking_settings.TagRankingSettings(), "correlation_threshold"),
    )

    for record, field in records:
        assert_frozen_and_slotted(record, field=field)


def test_quick_select_labels_and_descriptions_name_each_one_based_slot() -> None:
    for slot in range(10):
        definition = next(
            shortcut for shortcut in SHORTCUTS if shortcut.id == f"tagging.quick_select_{slot + 1}"
        )
        number = slot + 1

        assert definition.label == f"Toggle numbered tag {number}"
        assert f"numbers {number} " in definition.description
        assert ("Type the key instead of toggling" in definition.description) is (slot == 0)


def test_keycaps_parse_multiple_modifiers_in_noncanonical_order() -> None:
    assert keycaps("Alt+Ctrl+Shift+K") == ("Alt", "Ctrl", "Shift", "K")


@pytest.mark.parametrize(
    ("previous_order", "previous_current", "result_set", "expected"),
    [
        ([10, 20, 30, 40, 50], 40, [30, 50], 50),
        ([10, 20, 30, 40, 50], 40, [20, 30], 30),
        ([10, 20, 30, 40], 30, [10, 20], 20),
        ([10, 20, 30, 40], 40, [10], 10),
        ([99, 10, 20, 30, 40], 99, [20, 40], 20),
    ],
    ids=[
        "forward-wins-equal-distance",
        "nearest-backward",
        "backward-xor-boundary",
        "far-backward",
        "negative-index-does-not-wrap",
    ],
)
def test_current_item_fallback_search_uses_neighbor_positions(
    previous_order: list[int],
    previous_current: int,
    result_set: list[int],
    expected: int,
) -> None:
    state = ApplicationState(result_set=result_set)

    assert state._resolve_current_item(previous_order, previous_current) == expected


def test_tag_ranking_settings_reject_fraction_values_above_one(tmp_path: Path) -> None:
    preferences = PreferencesStore(tmp_path / "preferences.json")
    preferences.save({"tag_ranking": {"correlation_threshold": 1.5, "mega_popular_threshold": 1.5}})

    settings = ranking_settings.TagRankingSettingsStore(preferences).load()

    assert settings.correlation_threshold == ranking_settings.DEFAULT_CORRELATION_THRESHOLD
    assert settings.mega_popular_threshold == ranking_settings.DEFAULT_MEGA_POPULAR_THRESHOLD
