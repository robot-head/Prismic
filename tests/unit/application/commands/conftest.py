import pytest

from prismic.application import state
from prismic.application.commands.base import CommandContext
from prismic.persistence.repositories import mapping_repository, media_repository, tag_repository


@pytest.fixture
def context(
    tags: tag_repository.TagRepository,
    media: media_repository.MediaRepository,
    mappings: mapping_repository.MappingRepository,
) -> CommandContext:
    return CommandContext(tags=tags, media=media, mappings=mappings, state=state.ApplicationState())
