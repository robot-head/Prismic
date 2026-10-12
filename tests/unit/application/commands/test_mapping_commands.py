import pytest

from prismic.application.commands.base import CommandContext
from prismic.application.commands.mapping_commands import (
    MappingAddCommand,
    MappingRemoveCommand,
    MappingSetForManyCommand,
)
from prismic.application.errors import UnknownMappingError
from prismic.domain.media import MediaState
from prismic.persistence.errors import UnknownMediaError, UnknownTagError
from prismic.persistence.repositories.media_repository import MediaRepository


def _make_media(media: MediaRepository, name: str = "a.jpg") -> int:
    return media.create(
        relative_path=name, content_hash=name, size=1, mtime=1.0, state=MediaState.ACTIVE
    ).id


def _bulk_mapping_command(
    context: CommandContext, media: MediaRepository, *, adding: bool
) -> tuple[int, int, int, MappingSetForManyCommand]:
    has_it = _make_media(media, "has_it.jpg")
    lacks_it = _make_media(media, "lacks_it.jpg")
    tag = context.tags.create("vacation")
    context.mappings.add(has_it, tag.id)
    command = MappingSetForManyCommand(
        media_ids=frozenset({has_it, lacks_it}), tag_id=tag.id, adding=adding
    )
    return has_it, lacks_it, tag.id, command


def _mapping_remove_command(
    context: CommandContext, media: MediaRepository
) -> tuple[int, int, MappingRemoveCommand]:
    media_id = _make_media(media)
    tag = context.tags.create("vacation")
    context.mappings.add(media_id, tag.id)
    command = MappingRemoveCommand(media_id=media_id, tag_id=tag.id)
    return media_id, tag.id, command


def test_add_execute_creates_the_mapping(context: CommandContext, media: MediaRepository) -> None:
    media_id = _make_media(media)
    tag = context.tags.create("vacation")
    command = MappingAddCommand(media_id=media_id, tag_id=tag.id)

    command.execute(context)

    assert [t.id for t in context.mappings.tags_for_media(media_id)] == [tag.id]


def test_add_undo_removes_the_mapping(context: CommandContext, media: MediaRepository) -> None:
    media_id = _make_media(media)
    tag = context.tags.create("vacation")
    command = MappingAddCommand(media_id=media_id, tag_id=tag.id)
    command.execute(context)

    command.undo(context)

    assert context.mappings.tags_for_media(media_id) == []


def test_add_with_unknown_media_raises(context: CommandContext) -> None:
    tag = context.tags.create("vacation")
    command = MappingAddCommand(media_id=999, tag_id=tag.id)

    with pytest.raises(UnknownMediaError):
        command.execute(context)


def test_add_with_unknown_tag_raises(context: CommandContext, media: MediaRepository) -> None:
    media_id = _make_media(media)
    command = MappingAddCommand(media_id=media_id, tag_id=999)

    with pytest.raises(UnknownTagError):
        command.execute(context)


def test_remove_execute_deletes_the_mapping(
    context: CommandContext, media: MediaRepository
) -> None:
    media_id, _tag_id, command = _mapping_remove_command(context, media)

    command.execute(context)

    assert context.mappings.tags_for_media(media_id) == []


def test_remove_undo_recreates_the_mapping(context: CommandContext, media: MediaRepository) -> None:
    media_id, tag_id, command = _mapping_remove_command(context, media)
    command.execute(context)

    command.undo(context)

    assert [t.id for t in context.mappings.tags_for_media(media_id)] == [tag_id]


def test_remove_a_mapping_that_does_not_exist_raises(
    context: CommandContext, media: MediaRepository
) -> None:
    media_id = _make_media(media)
    tag = context.tags.create("vacation")
    command = MappingRemoveCommand(media_id=media_id, tag_id=tag.id)

    with pytest.raises(UnknownMappingError):
        command.execute(context)


def test_set_for_many_adding_only_touches_media_lacking_the_tag(
    context: CommandContext, media: MediaRepository
) -> None:
    has_it, lacks_it, tag_id, command = _bulk_mapping_command(context, media, adding=True)

    command.execute(context)

    assert {t.id for t in context.mappings.tags_for_media(has_it)} == {tag_id}
    assert {t.id for t in context.mappings.tags_for_media(lacks_it)} == {tag_id}


def test_set_for_many_adding_undo_only_removes_what_it_actually_added(
    context: CommandContext, media: MediaRepository
) -> None:
    """The whole point of tracking only the ids that actually changed:
    undoing a bulk "add" must not strip the tag from a file that already
    had it going in -- that file was never this command's doing."""
    has_it, lacks_it, tag_id, command = _bulk_mapping_command(context, media, adding=True)
    command.execute(context)

    command.undo(context)

    assert {t.id for t in context.mappings.tags_for_media(has_it)} == {tag_id}
    assert context.mappings.tags_for_media(lacks_it) == []


def test_set_for_many_removing_only_touches_media_with_the_tag(
    context: CommandContext, media: MediaRepository
) -> None:
    has_it, lacks_it, _tag_id, command = _bulk_mapping_command(context, media, adding=False)

    command.execute(context)

    assert context.mappings.tags_for_media(has_it) == []
    assert context.mappings.tags_for_media(lacks_it) == []


def test_set_for_many_removing_undo_only_restores_what_it_actually_removed(
    context: CommandContext, media: MediaRepository
) -> None:
    has_it, lacks_it, tag_id, command = _bulk_mapping_command(context, media, adding=False)
    command.execute(context)

    command.undo(context)

    assert {t.id for t in context.mappings.tags_for_media(has_it)} == {tag_id}
    assert context.mappings.tags_for_media(lacks_it) == []


def test_set_for_many_with_unknown_tag_raises(
    context: CommandContext, media: MediaRepository
) -> None:
    media_id = _make_media(media)
    command = MappingSetForManyCommand(media_ids=frozenset({media_id}), tag_id=999, adding=True)

    with pytest.raises(UnknownTagError):
        command.execute(context)
