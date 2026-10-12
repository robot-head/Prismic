"""Shared assertions for immutable value-record contracts."""

from dataclasses import FrozenInstanceError

import pytest


def assert_frozen_and_slotted(record: object, *, field: str) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(record, field, "changed")

    assert not hasattr(record, "__dict__")
