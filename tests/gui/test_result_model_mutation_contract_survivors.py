"""Value equality and index-boundary checks for the result list model."""

from __future__ import annotations

from PySide6.QtCore import Qt

from prismic.domain.media import Media, MediaState
from prismic.ui.result_model import MediaIdRole, ResultListModel


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


def test_result_model_returns_no_data_for_negative_and_past_end_rows() -> None:
    model = _model()

    class ValidIndex:
        def __init__(self, row: int) -> None:
            self._row = row

        def isValid(self) -> bool:
            return True

        def row(self) -> int:
            return self._row

    for row in (-1, model.rowCount()):
        assert model.data(ValidIndex(row)) is None  # type: ignore[arg-type]


def test_result_model_reports_zero_rows_below_a_valid_parent() -> None:
    model = _model()

    assert model.rowCount(model.index(0, 0)) == 0
