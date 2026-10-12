import pytest

from prismic.application.commands import TagCreateCommand, TagDeleteCommand, TagRenameCommand
from prismic.application.commands.base import Command, CommandContext
from prismic.application.commands.mapping_commands import MappingSetForManyCommand


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


class _CommandWithoutUndo(Command):
    def execute(self, context: CommandContext) -> None:
        pass


def test_command_subclass_must_implement_undo() -> None:
    with pytest.raises(TypeError, match="undo"):
        _CommandWithoutUndo()


def test_tag_commands_keep_undo_state_out_of_constructor_and_repr(context) -> None:
    commands = (
        (TagCreateCommand, ("vacation",), "_created_tag_id"),
        (TagRenameCommand, (1, "travel"), "_previous_name"),
        (TagDeleteCommand, (1,), "_deleted_tag_name"),
    )

    for command_type, args, private_field in commands:
        command = command_type(*args)
        assert private_field not in repr(command)
        with pytest.raises(TypeError):
            command_type(*args, **{private_field: "injected"})

    tag = context.tags.create("vacation")
    delete = TagDeleteCommand(tag_id=tag.id)
    delete.execute(context)
    assert "_mapped_media_ids" not in repr(delete)
    assert "_was_selected" not in repr(delete)
