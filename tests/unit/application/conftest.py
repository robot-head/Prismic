import sqlite3

import pytest

from prismic.persistence.repositories import mapping_repository, media_repository, tag_repository


@pytest.fixture
def tags(migrated_connection: sqlite3.Connection) -> tag_repository.TagRepository:
    return tag_repository.TagRepository(migrated_connection)


@pytest.fixture
def media(migrated_connection: sqlite3.Connection) -> media_repository.MediaRepository:
    return media_repository.MediaRepository(migrated_connection)


@pytest.fixture
def mappings(migrated_connection: sqlite3.Connection) -> mapping_repository.MappingRepository:
    return mapping_repository.MappingRepository(migrated_connection)
