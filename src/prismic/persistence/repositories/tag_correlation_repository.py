"""Materialized tag-to-tag co-occurrence data, backing the "tags that
usually go together" promotion in the item tag panel.

Recomputed wholesale (`recompute()`) rather than kept incrementally in
sync with every `MappingAddCommand`/`MappingRemoveCommand` -- a full
rebuild is one cheap self-join over `media_tags`, and the alternative
(an incremental update triggered from inside every mapping command) would
couple the command layer to this cache for a perf win that doesn't matter
at the collection sizes this app targets. `ensure_fresh()` throttles how
often that rebuild actually runs, since the panel that reads this data
refreshes far more often (every click, every tag toggle) than the
underlying tag data meaningfully changes.

Raw counts are stored, not a precomputed "meets the threshold" boolean --
the correlation-percentage setting can change at any time in Settings,
and storing counts means that takes effect on the next read rather than
needing its own recompute.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterable

from prismic.persistence import database

DEFAULT_MIN_COOCCURRENCE = 5
"""Both tags must appear together on at least this many files for the
pair to be tracked at all -- a floor against promoting a "correlation"
that's really just two tags that happened to land on the same one or two
files. Deliberately not user-configurable (see `requirements-amendments.md`):
it's a statistical-significance guard, not a tuning knob."""

DEFAULT_THROTTLE_SECONDS = 60.0


class TagCorrelationRepository:
    def __init__(
        self, connection: sqlite3.Connection, *, clock: Callable[[], float] = time.time
    ) -> None:
        self._connection = connection
        self._clock = clock

    def recompute(self, *, min_cooccurrence: int = DEFAULT_MIN_COOCCURRENCE) -> None:
        """Rebuild the entire table from `media_tags`'s current contents.

        Directional: two tags A and B that co-occur on `n` files produce
        *two* rows, (A, B, n, count(A)) and (B, A, n, count(B)) -- "80% of
        A's files also have B" and "80% of B's files also have A" are
        different claims sharing the same numerator but not the same
        denominator, and the panel only ever asks one direction at a time
        (given a checked tag, what's correlated *with* it).
        """
        with database.transaction(self._connection):
            self._connection.execute("DELETE FROM tag_correlations")
            self._connection.execute(
                """
                INSERT INTO tag_correlations (tag_x_id, tag_y_id, both_count, x_count)
                SELECT a.tag_id, b.tag_id, COUNT(*), x_counts.x_count
                FROM media_tags a
                JOIN media_tags b
                    ON a.media_id = b.media_id AND a.tag_id != b.tag_id
                JOIN (
                    SELECT tag_id, COUNT(*) AS x_count FROM media_tags GROUP BY tag_id
                ) x_counts ON x_counts.tag_id = a.tag_id
                GROUP BY a.tag_id, b.tag_id
                HAVING COUNT(*) >= ?
                """,
                (min_cooccurrence,),
            )
            self._connection.execute(
                "UPDATE tag_correlation_stats SET computed_at = ? WHERE id = 1", (self._clock(),)
            )

    def last_computed_at(self) -> float | None:
        row = self._connection.execute(
            "SELECT computed_at FROM tag_correlation_stats WHERE id = 1"
        ).fetchone()
        assert row is not None  # the singleton row is seeded by migration, never absent
        value = row["computed_at"]
        return float(value) if value is not None else None

    def ensure_fresh(
        self,
        *,
        min_cooccurrence: int = DEFAULT_MIN_COOCCURRENCE,
        max_age_seconds: float = DEFAULT_THROTTLE_SECONDS,
    ) -> None:
        """Recompute only if the cache has never been built, or was built
        more than `max_age_seconds` ago. Call this before reading
        correlations for anything a user is actively looking at -- it's
        the throttle that lets `best_correlations_from` be called on
        every panel refresh without that meaning a full table rebuild on
        every refresh.
        """
        last = self.last_computed_at()
        if last is None or self._clock() - last >= max_age_seconds:
            self.recompute(min_cooccurrence=min_cooccurrence)

    def best_correlations_from(self, tag_ids: Iterable[int]) -> dict[int, float]:
        """Every tag y correlated with at least one of `tag_ids` (the
        checked/"X" tags), mapped to the *strongest* (both_count / x_count)
        ratio among all of them -- the union-ranked-by-strongest-match
        merge rule for multiple checked tags.
        """
        ids = list(tag_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self._connection.execute(
            f"""
            SELECT tag_y_id, MAX(CAST(both_count AS REAL) / x_count) AS ratio
            FROM tag_correlations
            WHERE tag_x_id IN ({placeholders})
            GROUP BY tag_y_id
            """,
            ids,
        ).fetchall()
        return {row["tag_y_id"]: row["ratio"] for row in rows}
