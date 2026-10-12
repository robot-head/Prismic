import pytest

import prismic.application.commands.tag_commands as tag_commands
from prismic.application.commands.base import CommandContext
from prismic.domain.media import MediaState
from prismic.persistence.errors import UnknownTagError
from prismic.persistence.repositories.media_repository import MediaRepository


def _rename_command(context: CommandContext) -> tuple[int, tag_commands.TagRenameCommand]:
    tag = context.tags.create("vacation")
    return tag.id, tag_commands.TagRenameCommand(tag_id=tag.id, new_name="travel")


def _tag_with_mapping(context: CommandContext, media: MediaRepository) -> tuple[int, int]:
    tag = context.tags.create("vacation")
    photo = media.create(
        relative_path="a.jpg", content_hash="a", size=1, mtime=1.0, state=MediaState.ACTIVE
    )
    context.mappings.add(photo.id, tag.id)
    return tag.id, photo.id


@pytest.mark.parametrize(
    ("undo", "expected_names"),
    [(False, ["vacation"]), (True, [])],
    ids=["execute", "undo"],
)
def test_create_execute_and_undo(
    context: CommandContext, undo: bool, expected_names: list[str]
) -> None:
    command = tag_commands.TagCreateCommand(name="vacation")
    command.execute(context)

    if undo:
        command.undo(context)

    assert [tag.name for tag in context.tags.list_all()] == expected_names


@pytest.mark.parametrize(
    ("undo", "expected_name"),
    [(False, "travel"), (True, "vacation")],
    ids=["execute", "undo"],
)
def test_rename_execute_and_undo(context: CommandContext, undo: bool, expected_name: str) -> None:
    tag_id, command = _rename_command(context)

    command.execute(context)

    if undo:
        command.undo(context)

    assert context.tags.get(tag_id).name == expected_name  # type: ignore[union-attr]


def test_rename_unknown_tag_raises(context: CommandContext) -> None:
    command = tag_commands.TagRenameCommand(tag_id=999, new_name="anything")

    with pytest.raises(UnknownTagError):
        command.execute(context)


@pytest.mark.parametrize("undo", [False, True], ids=["execute", "undo"])
def test_delete_execute_and_undo(
    context: CommandContext, media: MediaRepository, undo: bool
) -> None:
    tag_id, photo_id = _tag_with_mapping(context, media)
    context.state.selected_tag_ids.append(tag_id)
    command = tag_commands.TagDeleteCommand(tag_id=tag_id)

    command.execute(context)

    assert context.tags.get(tag_id) is None
    assert context.mappings.tags_for_media(photo_id) == []
    assert tag_id not in context.state.selected_tag_ids

    if undo:
        command.undo(context)

        tags_after_undo = context.tags.list_all()
        assert [tag.name for tag in tags_after_undo] == ["vacation"]
        recreated = tags_after_undo[0]
        assert recreated.id != tag_id  # ids aren't reused across delete/undo
        assert [tag.id for tag in context.mappings.tags_for_media(photo_id)] == [recreated.id]
        assert context.state.selected_tag_ids == [recreated.id]


def test_delete_execute_removes_it_from_the_active_filter(context: CommandContext) -> None:
    tag = context.tags.create("vacation")
    context.state.selected_tag_ids.append(tag.id)
    command = tag_commands.TagDeleteCommand(tag_id=tag.id)

    command.execute(context)

    assert tag.id not in context.state.selected_tag_ids


def test_delete_unknown_tag_raises(context: CommandContext) -> None:
    command = tag_commands.TagDeleteCommand(tag_id=999)

    with pytest.raises(UnknownTagError):
        command.execute(context)
