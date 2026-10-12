from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from prismic.domain.media import Media, MediaState
from prismic.ui.result_model import MediaIdRole, ResultListModel
from tests.gui._media_helpers import make_media


def test_result_model_exposes_media_id_role_and_rejects_out_of_range_indices(
    qtbot: QtBot,
) -> None:
    assert int(MediaIdRole) == int(Qt.ItemDataRole.UserRole) + 1
    model = ResultListModel()
    model.set_media([make_media(media_id=29)])

    assert model.data(model.index(0, 0), MediaIdRole) == 29
    assert model.data(model.index(5, 0)) is None


def _model() -> ResultListModel:
    model = ResultListModel()
    model.set_media(
        [
            Media(
                id=1000,
                relative_path="photo.jpg",
                content_hash="hash",
                size=12,
                mtime=1.0,
                state=MediaState.ACTIVE,
            )
        ]
    )
    return model


def test_result_model_uses_value_equality_for_media_ids_and_roles() -> None:
    model = _model()
    index = model.index(0, 0)

    class EqualValue(int):
        pass

    assert model.row_for_media_id(EqualValue(1000)) == 0
    assert model.data(index, EqualValue(int(MediaIdRole))) == 1000
    assert model.data(index, EqualValue(int(Qt.ItemDataRole.DisplayRole))) == "photo.jpg"
    assert model.data(index, int(MediaIdRole) + 1) is None


@pytest.mark.parametrize("row_offset", [-1, 0], ids=["negative", "past-end"])
def test_result_model_returns_no_data_for_invalid_rows(row_offset: int) -> None:
    model = _model()
    row = model.rowCount() + row_offset

    class ValidIndex:
        def __init__(self, row: int) -> None:
            self._row = row

        def isValid(self) -> bool:
            return True

        def row(self) -> int:
            return self._row

    assert model.data(ValidIndex(row)) is None  # type: ignore[arg-type]


def test_result_model_reports_zero_rows_below_a_valid_parent() -> None:
    model = _model()

    assert model.rowCount(model.index(0, 0)) == 0


@pytest.mark.parametrize(
    "role",
    [-1, MediaIdRole + 1],
    ids=["negative-role", "unassigned-role"],
)
def test_result_model_returns_none_for_unknown_roles(role: int) -> None:
    model = ResultListModel()
    model.set_media([make_media()])

    assert model.data(model.index(0, 0), role) is None


def test_result_model_returns_none_for_far_past_end_rows() -> None:
    model = ResultListModel()
    model.set_media([make_media()])

    class ValidIndex:
        def isValid(self) -> bool:
            return True

        def row(self) -> int:
            return model.rowCount() + 1

    assert model.data(ValidIndex()) is None  # type: ignore[arg-type]
