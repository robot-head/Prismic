import pytest

import prismic.application.commands.mapping_commands as mapping_commands
from prismic.application.commands.base import CommandContext
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
) -> tuple[int, int, int, mapping_commands.MappingSetForManyCommand]:
    has_it = _make_media(media, "has_it.jpg")
    lacks_it = _make_media(media, "lacks_it.jpg")
    tag = context.tags.create("vacation")
    context.mappings.add(has_it, tag.id)
    command = mapping_commands.MappingSetForManyCommand(
        media_ids=frozenset({has_it, lacks_it}), tag_id=tag.id, adding=adding
    )
    return has_it, lacks_it, tag.id, command


def _single_mapping_command(
    context: CommandContext, media: MediaRepository, *, adding: bool
) -> tuple[
    int,
    int,
    mapping_commands.MappingAddCommand | mapping_commands.MappingRemoveCommand,
]:
    media_id = _make_media(media)
    tag = context.tags.create("vacation")
    if adding:
        command = mapping_commands.MappingAddCommand(media_id=media_id, tag_id=tag.id)
    else:
        context.mappings.add(media_id, tag.id)
        command = mapping_commands.MappingRemoveCommand(media_id=media_id, tag_id=tag.id)
    return media_id, tag.id, command


@pytest.mark.parametrize(
    ("adding", "undo", "remains_mapped"),
    [
        (True, False, True),
        (True, True, False),
        (False, False, False),
        (False, True, True),
    ],
    ids=["add", "undo-add", "remove", "undo-remove"],
)
def test_single_mapping_commands_execute_and_undo(
    context: CommandContext, media: MediaRepository, adding: bool, undo: bool, remains_mapped: bool
) -> None:
    media_id, tag_id, command = _single_mapping_command(context, media, adding=adding)

    command.execute(context)
    if undo:
        command.undo(context)

    expected_ids = [tag_id] if remains_mapped else []
    assert [tag.id for tag in context.mappings.tags_for_media(media_id)] == expected_ids


def test_add_with_unknown_media_raises(context: CommandContext) -> None:
    tag = context.tags.create("vacation")
    command = mapping_commands.MappingAddCommand(media_id=999, tag_id=tag.id)

    with pytest.raises(UnknownMediaError):
        command.execute(context)


def test_add_with_unknown_tag_raises(context: CommandContext, media: MediaRepository) -> None:
    media_id = _make_media(media)
    command = mapping_commands.MappingAddCommand(media_id=media_id, tag_id=999)

    with pytest.raises(UnknownTagError):
        command.execute(context)


def test_remove_a_mapping_that_does_not_exist_raises(
    context: CommandContext, media: MediaRepository
) -> None:
    media_id = _make_media(media)
    tag = context.tags.create("vacation")
    command = mapping_commands.MappingRemoveCommand(media_id=media_id, tag_id=tag.id)

    with pytest.raises(UnknownMappingError):
        command.execute(context)


def test_set_for_many_adding_only_touches_media_lacking_the_tag(
    context: CommandContext, media: MediaRepository
) -> None:
    has_it, lacks_it, tag_id, command = _bulk_mapping_command(context, media, adding=True)

    command.execute(context)

    assert {t.id for t in context.mappings.tags_for_media(has_it)} == {tag_id}
    assert {t.id for t in context.mappings.tags_for_media(lacks_it)} == {tag_id}


@pytest.mark.parametrize("adding", [True, False], ids=["adding", "removing"])
def test_set_for_many_undo_only_changes_entries_it_modified(
    context: CommandContext, media: MediaRepository, adding: bool
) -> None:
    """The whole point of tracking only the ids that actually changed:
    undoing a bulk "add" must not strip the tag from a file that already
    had it going in -- that file was never this command's doing."""
    has_it, lacks_it, tag_id, command = _bulk_mapping_command(context, media, adding=adding)
    command.execute(context)

    command.undo(context)

    assert {tag.id for tag in context.mappings.tags_for_media(has_it)} == {tag_id}
    assert context.mappings.tags_for_media(lacks_it) == []


def test_set_for_many_removing_only_touches_media_with_the_tag(
    context: CommandContext, media: MediaRepository
) -> None:
    has_it, lacks_it, _tag_id, command = _bulk_mapping_command(context, media, adding=False)

    command.execute(context)

    assert context.mappings.tags_for_media(has_it) == []
    assert context.mappings.tags_for_media(lacks_it) == []


def test_set_for_many_with_unknown_tag_raises(
    context: CommandContext, media: MediaRepository
) -> None:
    media_id = _make_media(media)
    command = mapping_commands.MappingSetForManyCommand(
        media_ids=frozenset({media_id}), tag_id=999, adding=True
    )

    with pytest.raises(UnknownTagError):
        command.execute(context)
