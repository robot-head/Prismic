import pytest

from prismic.application.commands.base import CommandContext
from prismic.application.commands.tag_commands import (
    TagCreateCommand,
    TagDeleteCommand,
    TagRenameCommand,
)
from prismic.domain.media import MediaState
from prismic.persistence.errors import UnknownTagError
from prismic.persistence.repositories.media_repository import MediaRepository


def _tag_with_mapping(context: CommandContext, media: MediaRepository) -> tuple[int, int]:
    tag = context.tags.create("vacation")
    photo = media.create(
        relative_path="a.jpg", content_hash="a", size=1, mtime=1.0, state=MediaState.ACTIVE
    )
    context.mappings.add(photo.id, tag.id)
    return tag.id, photo.id


def test_create_execute_creates_the_tag(context: CommandContext) -> None:
    command = TagCreateCommand(name="vacation")

    command.execute(context)

    assert [t.name for t in context.tags.list_all()] == ["vacation"]


def test_create_undo_removes_the_tag(context: CommandContext) -> None:
    command = TagCreateCommand(name="vacation")
    command.execute(context)

    command.undo(context)

    assert context.tags.list_all() == []


def test_rename_execute_changes_the_name(context: CommandContext) -> None:
    tag = context.tags.create("vacation")
    command = TagRenameCommand(tag_id=tag.id, new_name="travel")

    command.execute(context)

    assert context.tags.get(tag.id).name == "travel"  # type: ignore[union-attr]


def test_rename_undo_restores_the_previous_name(context: CommandContext) -> None:
    tag = context.tags.create("vacation")
    command = TagRenameCommand(tag_id=tag.id, new_name="travel")
    command.execute(context)

    command.undo(context)

    assert context.tags.get(tag.id).name == "vacation"  # type: ignore[union-attr]


def test_rename_unknown_tag_raises(context: CommandContext) -> None:
    command = TagRenameCommand(tag_id=999, new_name="anything")

    with pytest.raises(UnknownTagError):
        command.execute(context)


def test_delete_execute_removes_the_tag_and_its_mappings(
    context: CommandContext, media: MediaRepository
) -> None:
    tag_id, photo_id = _tag_with_mapping(context, media)
    command = TagDeleteCommand(tag_id=tag_id)

    command.execute(context)

    assert context.tags.get(tag_id) is None
    assert context.mappings.tags_for_media(photo_id) == []


def test_delete_execute_removes_it_from_the_active_filter(context: CommandContext) -> None:
    tag = context.tags.create("vacation")
    context.state.selected_tag_ids.append(tag.id)
    command = TagDeleteCommand(tag_id=tag.id)

    command.execute(context)

    assert tag.id not in context.state.selected_tag_ids


def test_delete_undo_restores_name_mappings_and_filter_membership(
    context: CommandContext, media: MediaRepository
) -> None:
    tag_id, photo_id = _tag_with_mapping(context, media)
    context.state.selected_tag_ids.append(tag_id)
    command = TagDeleteCommand(tag_id=tag_id)
    command.execute(context)

    command.undo(context)

    tags_after_undo = context.tags.list_all()
    assert [t.name for t in tags_after_undo] == ["vacation"]
    recreated = tags_after_undo[0]
    assert recreated.id != tag_id  # ids aren't reused across delete/undo
    assert [t.id for t in context.mappings.tags_for_media(photo_id)] == [recreated.id]
    assert context.state.selected_tag_ids == [recreated.id]


def test_delete_unknown_tag_raises(context: CommandContext) -> None:
    command = TagDeleteCommand(tag_id=999)

    with pytest.raises(UnknownTagError):
        command.execute(context)
