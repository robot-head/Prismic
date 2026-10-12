from prismic.application.commands.base import Command, CommandContext
from prismic.application.history import History


class _RecordingCommand(Command):
    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, context: CommandContext) -> None:
        pass

    def undo(self, context: CommandContext) -> None:
        pass


def _history_with_two_commands() -> tuple[History, _RecordingCommand, _RecordingCommand]:
    history = History()
    first = _RecordingCommand("first")
    second = _RecordingCommand("second")
    history.push(first)
    history.push(second)
    return history, first, second


def test_pop_undo_on_empty_history_returns_none() -> None:
    history = History()

    assert history.pop_undo() is None
    assert history.can_undo() is False


def test_push_then_pop_undo_is_lifo() -> None:
    history, first, second = _history_with_two_commands()

    assert history.pop_undo() is second
    assert history.pop_undo() is first
    assert history.pop_undo() is None


def test_can_undo_reflects_stack_contents() -> None:
    history = History()
    assert history.can_undo() is False

    history.push(_RecordingCommand("a"))
    assert history.can_undo() is True

    history.pop_undo()
    assert history.can_undo() is False


def test_len_reflects_stack_size() -> None:
    history = History()
    history.push(_RecordingCommand("a"))
    history.push(_RecordingCommand("b"))

    assert len(history) == 2

    history.pop_undo()
    assert len(history) == 1


def test_pop_redo_on_empty_history_returns_none() -> None:
    history = History()

    assert history.pop_redo() is None
    assert history.can_redo() is False


def test_undo_then_redo_is_lifo() -> None:
    history, _first, second = _history_with_two_commands()

    history.pop_undo()
    assert history.can_redo() is True

    assert history.pop_redo() is second
    assert history.pop_redo() is None
    assert history.can_undo() is True


def test_new_command_clears_redo_stack() -> None:
    history = History()
    history.push(_RecordingCommand("a"))
    history.pop_undo()
    assert history.can_redo() is True

    history.push(_RecordingCommand("b"))
    assert history.can_redo() is False
