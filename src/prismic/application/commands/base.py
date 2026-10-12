"""The command shape every mutating operation follows.

`CommandDispatcher` wraps `execute`/`undo` in a transaction and publishes
new state only after a successful commit — a validation failure raised
before any mutation rolls back an empty (harmless) transaction and leaves
history and state untouched.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from prismic.application import state
from prismic.persistence.repositories import mapping_repository, media_repository, tag_repository


@dataclass
class CommandContext:
    tags: tag_repository.TagRepository
    media: media_repository.MediaRepository
    mappings: mapping_repository.MappingRepository
    state: state.ApplicationState


class Command(ABC):
    """A single undoable user action: validate, then mutate.

    Implementations should raise before mutating anything if a precondition
    fails (e.g. an unknown id, an already-selected filter tag) — the
    dispatcher's transaction wrapping only guarantees atomicity, not
    validation, so `execute`/`undo` must do their own checks first.
    """

    @abstractmethod
    def execute(self, context: CommandContext) -> None: ...

    @abstractmethod
    def undo(self, context: CommandContext) -> None: ...
