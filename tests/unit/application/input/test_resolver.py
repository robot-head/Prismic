from dataclasses import FrozenInstanceError

import pytest

from prismic.application.input.resolver import (
    INPUT_CONTEXT_PRECEDENCE,
    InputContext,
    InputEvent,
    InputHandler,
    InputResolver,
)


def _recording_handler(calls: list[str], label: str, *, consumes: bool) -> InputHandler:
    def handler(event: InputEvent) -> bool:
        calls.append(label)
        return consumes

    return handler


def test_dispatch_with_no_handlers_reports_unconsumed() -> None:
    resolver = InputResolver()

    assert resolver.dispatch(InputEvent(key="a")) is False


def test_text_editing_takes_precedence_over_global_command() -> None:
    resolver = InputResolver()
    calls: list[str] = []
    resolver.register(InputContext.TEXT_EDITING, _recording_handler(calls, "text", consumes=True))
    resolver.register(
        InputContext.GLOBAL_COMMAND, _recording_handler(calls, "global", consumes=True)
    )

    consumed = resolver.dispatch(InputEvent(key="a"))

    assert consumed is True
    assert calls == ["text"]


def test_falls_through_to_the_next_context_when_unconsumed() -> None:
    resolver = InputResolver()
    calls: list[str] = []
    resolver.register(InputContext.TEXT_EDITING, _recording_handler(calls, "text", consumes=False))
    resolver.register(InputContext.VIEWER, _recording_handler(calls, "viewer", consumes=True))
    resolver.register(
        InputContext.GLOBAL_COMMAND, _recording_handler(calls, "global", consumes=True)
    )

    consumed = resolver.dispatch(InputEvent(key="a"))

    assert consumed is True
    assert calls == ["text", "viewer"]


def test_precedence_order_is_text_local_viewer_global() -> None:
    assert INPUT_CONTEXT_PRECEDENCE == (
        InputContext.TEXT_EDITING,
        InputContext.LOCAL_MODAL,
        InputContext.VIEWER,
        InputContext.GLOBAL_COMMAND,
    )


def test_unregister_removes_a_handler() -> None:
    resolver = InputResolver()
    resolver.register(InputContext.GLOBAL_COMMAND, lambda event: True)

    resolver.unregister(InputContext.GLOBAL_COMMAND)

    assert resolver.dispatch(InputEvent(key="a")) is False


def test_input_event_is_immutable() -> None:
    event = InputEvent(key="a")

    with pytest.raises(FrozenInstanceError):
        event.key = "b"  # type: ignore[misc]
