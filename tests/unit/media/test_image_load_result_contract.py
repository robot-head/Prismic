"""Behavioral contract tests for image loader results."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from prismic.media.loader import ImageLoadResult


def test_image_load_result_fields_are_immutable() -> None:
    result = ImageLoadResult(request_id=1, path=Path("photo.png"), image=None, error=None)

    with pytest.raises(FrozenInstanceError):
        result.request_id = 2  # type: ignore[misc]
