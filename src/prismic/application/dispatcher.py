"""The command dispatcher.

Every mutation goes through here so it uniformly gets a transaction, a
post-commit state recompute, and an undo-history entry — per overview
section 1's central invariant, UI (and everything else) never implements
persistence or undo directly.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from prismic.application.commands.base import Command, CommandContext
from prismic.application.history import History
from prismic.application.state import ApplicationState
from prismic.persistence import database
from prismic.persistence.repositories.mapping_repository import MappingRepository
from prismic.persistence.repositories.media_repository import MediaRepository
from prismic.persistence.repositories.tag_repository import TagRepository

_CommandMethod = Callable[[CommandContext], None]


class CommandDispatcher:
    def __init__(
        self,
        connection: sqlite3.Connection,
        state: ApplicationState,
        tags: TagRepository,
        media: MediaRepository,
        mappings: MappingRepository,
        history: History,
    ) -> None:
        self._connection = connection
        self._state = state
        self._tags = tags
        self._media = media
        self._mappings = mappings
        self._history = history

    def execute(self, command: Command) -> None:
        """Run `command`, publish new state, and record it for undo.

        A failed transaction (the command's `execute` raising) leaves state
        and history untouched — nothing is published, nothing is pushed.
        """
        self._run(command.execute)
        self._history.push(command)

    def undo(self) -> bool:
        """Undo the most recent command. Returns False if there was none."""
        command = self._history.pop_undo()
        if command is None:
            return False
        self._run(command.undo)
        return True

    def redo(self) -> bool:
        """Redo the most recently undone command. Returns False if there
        was none."""
        command = self._history.pop_redo()
        if command is None:
            return False
        self._run(command.execute)
        return True

    def _run(self, apply: _CommandMethod) -> None:
        context = CommandContext(
            tags=self._tags, media=self._media, mappings=self._mappings, state=self._state
        )
        with database.transaction(self._connection):
            apply(context)
        self._state.recompute(self._media, self._mappings)
