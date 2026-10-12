"""CRUD access to the `tags` table."""

from __future__ import annotations

import sqlite3

from prismic.domain.tag import Tag, validate_tag_name
from prismic.persistence.errors import DuplicateTagNameError, UnknownTagError
from prismic.persistence.repositories._base import SQLiteRepository


class TagRepository(SQLiteRepository):
    def create(self, name: str) -> Tag:
        validated = validate_tag_name(name)
        try:
            cursor = self._connection.execute("INSERT INTO tags (name) VALUES (?)", (validated,))
        except sqlite3.IntegrityError as exc:
            raise DuplicateTagNameError(validated) from exc
        tag_id = cursor.lastrowid
        assert tag_id is not None
        return Tag(id=tag_id, name=validated)

    def rename(self, tag_id: int, new_name: str) -> Tag:
        validated = validate_tag_name(new_name)
        try:
            cursor = self._connection.execute(
                "UPDATE tags SET name = ? WHERE id = ?", (validated, tag_id)
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateTagNameError(validated) from exc
        if cursor.rowcount == 0:
            raise UnknownTagError(tag_id)
        return Tag(id=tag_id, name=validated)

    def delete(self, tag_id: int) -> None:
        self._connection.execute("DELETE FROM media_tags WHERE tag_id = ?", (tag_id,))
        cursor = self._connection.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        if cursor.rowcount == 0:
            raise UnknownTagError(tag_id)

    def get(self, tag_id: int) -> Tag | None:
        row = self._connection.execute(
            "SELECT id, name FROM tags WHERE id = ?", (tag_id,)
        ).fetchone()
        return Tag(id=row["id"], name=row["name"]) if row is not None else None

    def list_all(self) -> list[Tag]:
        # Most-used tags first -- what the user reaches for again is what
        # should be nearest the top, in both the filter panel and the
        # per-item tag panel (both list views share this one ordering).
        # Name is only the tie-break for tags with equal (often zero) use.
        rows = self._connection.execute(
            """
            SELECT tags.id, tags.name, COUNT(media_tags.media_id) AS use_count
            FROM tags
            LEFT JOIN media_tags ON media_tags.tag_id = tags.id
            GROUP BY tags.id
            ORDER BY use_count DESC, tags.name
            """
        ).fetchall()
        return [Tag(id=row["id"], name=row["name"]) for row in rows]

    def mega_popular_tag_ids(self, min_fraction: float, total_media_count: int) -> frozenset[int]:
        """Ids of tags present on at least `min_fraction` of all media --
        the "mega popular" promotion tier, same use-count basis
        `list_all()` orders by (every mapping counted, regardless of
        whether that media is currently active on disk), so a tag ranking
        highest under the everyday popularity order and one qualifying
        here never disagree over what "popular" means.
        """
        if total_media_count <= 0:
            return frozenset()
        rows = self._connection.execute(
            """
            SELECT tags.id AS id, COUNT(media_tags.media_id) AS use_count
            FROM tags
            LEFT JOIN media_tags ON media_tags.tag_id = tags.id
            GROUP BY tags.id
            """
        ).fetchall()
        return frozenset(
            row["id"] for row in rows if row["use_count"] / total_media_count >= min_fraction
        )
