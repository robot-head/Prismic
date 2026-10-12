import pytest

from prismic.application.commands import (
    CommandContext,
    FilterDeselectCommand,
    FilterSelectCommand,
)
from prismic.application.errors import TagAlreadySelectedError, TagNotSelectedError
from prismic.persistence.errors import UnknownTagError


def _select_tag(context: CommandContext) -> tuple[int, FilterSelectCommand]:
    tag = context.tags.create("vacation")
    return tag.id, FilterSelectCommand(tag_id=tag.id)


def test_select_execute_adds_to_the_filter(context: CommandContext) -> None:
    tag_id, command = _select_tag(context)

    command.execute(context)

    assert context.state.selected_tag_ids == [tag_id]


def test_select_undo_removes_from_the_filter(context: CommandContext) -> None:
    _tag_id, command = _select_tag(context)
    command.execute(context)

    command.undo(context)

    assert context.state.selected_tag_ids == []


def test_select_unknown_tag_raises(context: CommandContext) -> None:
    command = FilterSelectCommand(tag_id=999)

    with pytest.raises(UnknownTagError):
        command.execute(context)


def test_select_an_already_selected_tag_raises(context: CommandContext) -> None:
    tag = context.tags.create("vacation")
    FilterSelectCommand(tag_id=tag.id).execute(context)

    with pytest.raises(TagAlreadySelectedError):
        FilterSelectCommand(tag_id=tag.id).execute(context)


@pytest.mark.parametrize("undo", [False, True], ids=["execute", "undo"])
def test_deselect_execute_removes_from_the_filter_and_undo_restores_it(
    context: CommandContext, undo: bool
) -> None:
    tag = context.tags.create("vacation")
    FilterSelectCommand(tag_id=tag.id).execute(context)
    command = FilterDeselectCommand(tag_id=tag.id)

    command.execute(context)
    if undo:
        command.undo(context)

    assert context.state.selected_tag_ids == ([tag.id] if undo else [])


def test_deselect_a_tag_not_selected_raises(context: CommandContext) -> None:
    tag = context.tags.create("vacation")
    command = FilterDeselectCommand(tag_id=tag.id)

    with pytest.raises(TagNotSelectedError):
        command.execute(context)
