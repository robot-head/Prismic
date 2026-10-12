import sqlite3
from dataclasses import dataclass

import pytest

from prismic.application.commands.filter_commands import FilterSelectCommand
from prismic.application.commands.mapping_commands import MappingAddCommand
from prismic.application.commands.tag_commands import TagCreateCommand
from prismic.application.dispatcher import CommandDispatcher
from prismic.application.history import History
from prismic.application.state import ApplicationState
from prismic.domain.media import MediaState
from prismic.persistence.errors import UnknownMediaError, UnknownTagError
from prismic.persistence.repositories import mapping_repository, media_repository, tag_repository


def _make_media(media: media_repository.MediaRepository):
    return media.create(
        relative_path="a.jpg", content_hash="a", size=1, mtime=1.0, state=MediaState.ACTIVE
    )


def _make_media_and_tag(
    media: media_repository.MediaRepository,
    tags: tag_repository.TagRepository,
) -> tuple[media_repository.Media, int]:
    return _make_media(media), tags.create("vacation").id


@pytest.fixture
def state() -> ApplicationState:
    return ApplicationState()


@dataclass(frozen=True)
class _DispatcherContext:
    connection: sqlite3.Connection
    state: ApplicationState
    tags: tag_repository.TagRepository
    media: media_repository.MediaRepository
    mappings: mapping_repository.MappingRepository


@pytest.fixture
def _dispatcher_context(
    migrated_connection: sqlite3.Connection,
    state: ApplicationState,
    tags: tag_repository.TagRepository,
    media: media_repository.MediaRepository,
    mappings: mapping_repository.MappingRepository,
) -> _DispatcherContext:
    return _DispatcherContext(migrated_connection, state, tags, media, mappings)


@pytest.fixture
def dispatcher(_dispatcher_context: _DispatcherContext) -> CommandDispatcher:
    context = _dispatcher_context
    return CommandDispatcher(
        context.connection,
        context.state,
        context.tags,
        context.media,
        context.mappings,
        History(),
    )


def test_execute_always_leaves_current_item_null_or_in_the_result_set(
    dispatcher: CommandDispatcher,
    state: ApplicationState,
    media: media_repository.MediaRepository,
    tags: tag_repository.TagRepository,
) -> None:
    photo, tag_id = _make_media_and_tag(media, tags)

    dispatcher.execute(FilterSelectCommand(tag_id=tag_id))
    assert state.current_item is None or state.current_item in state.result_set
    assert state.result_set == []  # nothing mapped to the tag yet

    dispatcher.execute(MappingAddCommand(media_id=photo.id, tag_id=tag_id))
    assert state.current_item is None or state.current_item in state.result_set
    assert state.result_set == [photo.id]


def test_execute_then_undo_restores_the_original_state(
    dispatcher: CommandDispatcher, tags: tag_repository.TagRepository
) -> None:
    before = tags.list_all()

    dispatcher.execute(TagCreateCommand(name="vacation"))
    assert [t.name for t in tags.list_all()] == ["vacation"]

    dispatcher.undo()

    assert tags.list_all() == before


def test_multiple_sequential_undos_unwind_in_reverse_order(
    dispatcher: CommandDispatcher, tags: tag_repository.TagRepository
) -> None:
    dispatcher.execute(TagCreateCommand(name="first"))
    dispatcher.execute(TagCreateCommand(name="second"))
    dispatcher.execute(TagCreateCommand(name="third"))
    assert [t.name for t in tags.list_all()] == ["first", "second", "third"]

    assert dispatcher.undo() is True
    assert [t.name for t in tags.list_all()] == ["first", "second"]

    assert dispatcher.undo() is True
    assert [t.name for t in tags.list_all()] == ["first"]

    assert dispatcher.undo() is True
    assert tags.list_all() == []

    assert dispatcher.undo() is False  # nothing left to undo


def test_undo_then_redo_reapplies_the_command(
    dispatcher: CommandDispatcher, tags: tag_repository.TagRepository
) -> None:
    dispatcher.execute(TagCreateCommand(name="vacation"))
    dispatcher.undo()
    assert tags.list_all() == []

    assert dispatcher.redo() is True
    assert [t.name for t in tags.list_all()] == ["vacation"]

    assert dispatcher.redo() is False  # nothing left to redo


def test_a_fresh_command_clears_the_redo_stack(
    dispatcher: CommandDispatcher, tags: tag_repository.TagRepository
) -> None:
    dispatcher.execute(TagCreateCommand(name="first"))
    dispatcher.undo()
    assert dispatcher.redo() is True

    dispatcher.execute(TagCreateCommand(name="second"))
    assert dispatcher.redo() is False


def test_a_failed_command_publishes_no_partial_mutation(
    dispatcher: CommandDispatcher,
    _dispatcher_context: _DispatcherContext,
) -> None:
    context = _dispatcher_context
    photo, tag_id = _make_media_and_tag(context.media, context.tags)
    state_before = (list(context.state.result_set), context.state.current_item)

    with pytest.raises(UnknownMediaError):
        dispatcher.execute(MappingAddCommand(media_id=999, tag_id=tag_id))

    # No mapping was written, state wasn't republished, and nothing landed
    # on the undo stack for a command that never actually applied.
    assert [tag.name for tag in context.tags.list_all()] == ["vacation"]
    assert context.mappings.tags_for_media(photo.id) == []
    assert (list(context.state.result_set), context.state.current_item) == state_before
    assert dispatcher.undo() is False


def test_every_mapping_written_references_an_existing_media_and_tag(
    dispatcher: CommandDispatcher,
    media: media_repository.MediaRepository,
    tags: tag_repository.TagRepository,
) -> None:
    photo = _make_media(media)

    with pytest.raises(UnknownTagError):
        dispatcher.execute(MappingAddCommand(media_id=photo.id, tag_id=999))
