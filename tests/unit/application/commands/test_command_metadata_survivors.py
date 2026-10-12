import pytest
from PySide6.QtGui import QImage

from prismic.application.commands.tag_commands import (
    TagCreateCommand,
    TagDeleteCommand,
    TagRenameCommand,
)
from prismic.media.cache import ImageCache
from prismic.media.image import downsample


def test_tag_commands_keep_undo_state_out_of_constructor_and_repr(context) -> None:
    commands = (
        (TagCreateCommand, ("vacation",), "_created_tag_id"),
        (TagRenameCommand, (1, "travel"), "_previous_name"),
        (TagDeleteCommand, (1,), "_deleted_tag_name"),
    )

    for command_type, args, private_field in commands:
        command = command_type(*args)
        assert private_field not in repr(command)
        with pytest.raises(TypeError):
            command_type(*args, **{private_field: "injected"})

    tag = context.tags.create("vacation")
    delete = TagDeleteCommand(tag_id=tag.id)
    delete.execute(context)
    assert "_mapped_media_ids" not in repr(delete)
    assert "_was_selected" not in repr(delete)


def test_default_image_cache_budget_is_256_mib() -> None:
    assert ImageCache().max_bytes == 256 * 1024 * 1024


def test_downsample_preserves_an_image_that_fits_at_the_exact_boundary(qtbot) -> None:
    image = QImage(500, 250, QImage.Format.Format_RGB32)

    result = downsample(image, max_dimension=500)

    assert result is image
