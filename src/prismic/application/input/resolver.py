"""Keyboard command-resolution precedence, independent of any widget.

Per overview section 10, an event is offered to each context in this order
until one consumes it:

    text-editing context -> local/modal interaction -> viewer interaction
    -> global application command

The actual Qt key-event wiring (translating `QKeyEvent` to `InputEvent`,
registering real handlers bound to widgets) is Phase 5's job — this module
only defines the data structures and the resolution order itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto


# Declaration order is the dispatch precedence below.
class InputContext(Enum):
    TEXT_EDITING = auto()
    """A text-entry widget has focus (e.g. renaming a tag) — it gets first
    refusal on every keystroke."""

    LOCAL_MODAL = auto()
    """A modal/local interaction is in progress (e.g. a confirmation, an
    in-progress chord) that should intercept input before anything else."""

    VIEWER = auto()
    """The media viewer's own interactions (zoom, pan, playback, seek)."""

    GLOBAL_COMMAND = auto()
    """Application-wide shortcuts, tried last."""


INPUT_CONTEXT_PRECEDENCE: tuple[InputContext, ...] = (
    InputContext.TEXT_EDITING,
    InputContext.LOCAL_MODAL,
    InputContext.VIEWER,
    InputContext.GLOBAL_COMMAND,
)


@dataclass(frozen=True, slots=True)
class InputEvent:
    """A single abstract key input, independent of Qt's `QKeyEvent`."""

    key: str


InputHandler = Callable[[InputEvent], bool]
"""Returns True if it consumed the event, False to let the next context try."""


class InputResolver:
    """Dispatches an `InputEvent` to registered context handlers in
    precedence order, stopping at the first one that consumes it."""

    def __init__(self) -> None:
        self._handlers: dict[InputContext, InputHandler] = {}

    def register(self, context: InputContext, handler: InputHandler) -> None:
        self._handlers[context] = handler

    def unregister(self, context: InputContext) -> None:
        self._handlers.pop(context, None)

    def dispatch(self, event: InputEvent) -> bool:
        for context in INPUT_CONTEXT_PRECEDENCE:
            handler = self._handlers.get(context)
            if handler is not None and handler(event):
                return True
        return False
