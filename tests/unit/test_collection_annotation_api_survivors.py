"""Keep collection persistence API type annotations resolvable at runtime."""

from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import get_type_hints

from prismic.persistence.collection import OpenCollection, find_collection_file, open_collection


def test_collection_file_lookup_annotations_resolve() -> None:
    assert get_type_hints(find_collection_file) == {
        "directory": Path,
        "return": Path | None,
    }


def test_collection_context_manager_annotations_resolve() -> None:
    assert get_type_hints(OpenCollection.__exit__) == {
        "exc_type": type[BaseException] | None,
        "exc_value": BaseException | None,
        "traceback": TracebackType | None,
        "return": type(None),
    }


def test_open_collection_path_annotations_resolve() -> None:
    assert get_type_hints(open_collection) == {
        "path": str | os.PathLike[str],
        "return": OpenCollection,
    }
