"""CRUD access to the `media` table."""

from __future__ import annotations

import sqlite3
from typing import TypedDict, Unpack

from prismic.domain.media import Media, MediaState
from prismic.persistence.errors import UnknownMediaError


class _MediaFields(TypedDict):
    relative_path: str
    content_hash: str
    size: int
    mtime: float
    state: MediaState


def _row_to_media(row: sqlite3.Row) -> Media:
    return _make_media(
        media_id=row["id"],
        relative_path=row["relative_path"],
        content_hash=row["content_hash"],
        size=row["size"],
        mtime=row["mtime"],
        state=MediaState(row["state"]),
    )


def _make_media(
    media_id: int,
    relative_path: str,
    content_hash: str,
    size: int,
    mtime: float,
    state: MediaState,
) -> Media:
    return Media(
        id=media_id,
        relative_path=relative_path,
        content_hash=content_hash,
        size=size,
        mtime=mtime,
        state=state,
    )


class MediaRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self,
        relative_path: str,
        content_hash: str,
        size: int,
        mtime: float,
        state: MediaState,
    ) -> Media:
        cursor = self._connection.execute(
            """
            INSERT INTO media (relative_path, content_hash, size, mtime, state)
            VALUES (?, ?, ?, ?, ?)
            """,
            (relative_path, content_hash, size, mtime, state.value),
        )
        media_id = cursor.lastrowid
        assert media_id is not None
        return _make_media(media_id, relative_path, content_hash, size, mtime, state)

    def get(self, media_id: int) -> Media | None:
        row = self._connection.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        return _row_to_media(row) if row is not None else None

    def get_by_relative_path(self, relative_path: str) -> Media | None:
        row = self._connection.execute(
            "SELECT * FROM media WHERE relative_path = ?", (relative_path,)
        ).fetchone()
        return _row_to_media(row) if row is not None else None

    def find_by_content_hash(self, content_hash: str) -> list[Media]:
        rows = self._connection.execute(
            "SELECT * FROM media WHERE content_hash = ?", (content_hash,)
        ).fetchall()
        return [_row_to_media(row) for row in rows]

    def update(
        self,
        media_id: int,
        **fields: Unpack[_MediaFields],
    ) -> Media:
        cursor = self._connection.execute(
            """
            UPDATE media
            SET relative_path = ?, content_hash = ?, size = ?, mtime = ?, state = ?
            WHERE id = ?
            """,
            (
                fields["relative_path"],
                fields["content_hash"],
                fields["size"],
                fields["mtime"],
                fields["state"].value,
                media_id,
            ),
        )
        if cursor.rowcount == 0:
            raise UnknownMediaError(media_id)
        return _make_media(
            media_id,
            fields["relative_path"],
            fields["content_hash"],
            fields["size"],
            fields["mtime"],
            fields["state"],
        )

    def list_all(self) -> list[Media]:
        rows = self._connection.execute("SELECT * FROM media ORDER BY relative_path").fetchall()
        return [_row_to_media(row) for row in rows]

    def count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS n FROM media").fetchone()
        return int(row["n"])
