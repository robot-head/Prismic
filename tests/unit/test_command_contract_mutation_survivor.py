import pytest

from prismic.application.commands.base import Command, CommandContext


class _CommandWithoutUndo(Command):
    def execute(self, context: CommandContext) -> None:
        pass


def test_command_subclass_must_implement_undo() -> None:
    with pytest.raises(TypeError, match="undo"):
        _CommandWithoutUndo()
