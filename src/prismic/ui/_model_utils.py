"""Small shared operations for the app's list-model implementations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class _HasId(Protocol):
    @property
    def id(self) -> int: ...


class _HasValidity(Protocol):
    def isValid(self) -> bool: ...


def find_row_by_id(items: Sequence[_HasId], item_id: int) -> int | None:
    for row, item in enumerate(items):
        if item.id == item_id:
            return row
    return None


def top_level_row_count(parent: _HasValidity | None, item_count: int) -> int:
    if parent is not None and parent.isValid():
        return 0
    return item_count
