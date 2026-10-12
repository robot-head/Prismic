"""Shared setup for reconciliation tests that need filesystem race control."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from prismic.domain.collection import Collection


@dataclass(frozen=True)
class ReconciliationTestContext:
    root: Path
    collection: Collection
    connection: sqlite3.Connection
    monkeypatch: pytest.MonkeyPatch


@pytest.fixture
def reconciliation_test_context(
    tmp_path: Path,
    migrated_connection: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> ReconciliationTestContext:
    return ReconciliationTestContext(
        root=tmp_path,
        collection=Collection(tmp_path, tmp_path / "vacation.prismic"),
        connection=migrated_connection,
        monkeypatch=monkeypatch,
    )
