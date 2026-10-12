"""Shared media-row setup for unit tests."""

from prismic.domain.media import MediaState
from prismic.persistence.repositories.media_repository import MediaRepository


def add_active_media(media_repo: MediaRepository, relative_path: str) -> int:
    return media_repo.create(relative_path, relative_path, 1, 1.0, MediaState.ACTIVE).id
