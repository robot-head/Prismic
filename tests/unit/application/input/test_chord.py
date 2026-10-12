import pytest

from prismic.application.input.chord import ChordState


@pytest.mark.parametrize("cancel_after_press", [False, True], ids=["new", "cancelled"])
def test_empty_or_cancelled_chord_has_no_pending_state(cancel_after_press: bool) -> None:
    chord = ChordState()
    if cancel_after_press:
        chord.press("g")
        chord.cancel()

    assert chord.is_pending is False
    assert chord.pending_keys == ()


def test_press_accumulates_pending_keys() -> None:
    chord = ChordState()

    chord.press("g")
    chord.press("g")

    assert chord.pending_keys == ("g", "g")
    assert chord.is_pending is True


def test_match_on_an_exact_chord_returns_the_command_and_clears() -> None:
    chord = ChordState()
    chords: dict[tuple[str, ...], str] = {("g", "g"): "go_to_start"}
    chord.press("g")
    chord.press("g")

    result = chord.match(chords)

    assert result == "go_to_start"
    assert chord.is_pending is False


@pytest.mark.parametrize(
    ("pressed_keys", "expected_pending"),
    [("g", True), ("x", False)],
    ids=["valid-prefix", "dead-end"],
)
def test_match_without_a_complete_chord_returns_none(
    pressed_keys: str, expected_pending: bool
) -> None:
    chord = ChordState()
    chords: dict[tuple[str, ...], str] = {("g", "g"): "go_to_start"}
    for key in pressed_keys:
        chord.press(key)

    result = chord.match(chords)

    assert result is None
    assert chord.is_pending is expected_pending


def test_advance_time_within_timeout_does_not_cancel() -> None:
    chord = ChordState(timeout_seconds=1.0)
    chord.press("g")

    timed_out = chord.advance_time(0.5)

    assert timed_out is False
    assert chord.is_pending is True


def test_advance_time_past_timeout_cancels() -> None:
    chord = ChordState(timeout_seconds=1.0)
    chord.press("g")

    timed_out = chord.advance_time(1.5)

    assert timed_out is True
    assert chord.is_pending is False


def test_advance_time_with_nothing_pending_is_a_no_op() -> None:
    chord = ChordState()

    assert chord.advance_time(10.0) is False


def test_a_new_key_press_resets_the_timeout_clock() -> None:
    chord = ChordState(timeout_seconds=1.0)
    chord.press("g")

    chord.advance_time(0.9)
    chord.press("g")  # resets the clock
    timed_out = chord.advance_time(0.9)

    assert timed_out is False
    assert chord.pending_keys == ("g", "g")


def test_chord_internal_state_is_not_constructor_input_or_repr() -> None:
    chord = ChordState()
    chord.press("g")

    assert repr(chord) == "ChordState(timeout_seconds=1.0)"
    with pytest.raises(TypeError):
        ChordState(_pending_keys=["g"])
    with pytest.raises(TypeError):
        ChordState(_elapsed_since_last_key=0.5)


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
