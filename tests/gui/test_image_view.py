from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from prismic.media.image import ImageLoadError, load_image
from prismic.ui.image_view import ImageView
from tests.gui._mutation_helpers import wheel_event

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "media"


def _loaded_view(qtbot: QtBot, *, size: tuple[int, int] | None = None) -> ImageView:
    view = ImageView()
    if size is not None:
        view.resize(*size)
    qtbot.addWidget(view)
    image = load_image(FIXTURES_DIR / "supported_image.png")
    assert not isinstance(image, ImageLoadError)
    view.set_image(image)
    return view


def test_set_image_fits_to_window_at_zoom_one(qtbot: QtBot) -> None:
    view = _loaded_view(qtbot)

    assert view.zoom == 1.0


def test_zoom_in_increases_zoom_level(qtbot: QtBot) -> None:
    view = _loaded_view(qtbot)

    view.zoom_in()

    assert view.zoom == 1.25


def test_zoom_out_decreases_zoom_level(qtbot: QtBot) -> None:
    view = _loaded_view(qtbot)

    view.zoom_out()

    assert view.zoom == 0.8


@pytest.mark.parametrize(
    ("delta", "expected_zoom"),
    [(120, 1.25), (-120, 0.8), (0, 0.8)],
    ids=["up", "down", "zero-is-nonpositive"],
)
def test_wheel_event_zooms_by_delta_direction(
    qtbot: QtBot, delta: int, expected_zoom: float
) -> None:
    view = _loaded_view(qtbot)

    event = wheel_event(delta)
    view.wheelEvent(event)

    assert view.zoom == expected_zoom


def test_double_click_zooms_in_then_fits_back(qtbot: QtBot) -> None:
    view = _loaded_view(qtbot, size=(200, 200))
    assert view.zoom == 1.0

    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton)
    assert view.zoom == 2.0

    qtbot.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton)
    assert view.zoom == 1.0


def test_pan_mode_is_scroll_hand_drag(qtbot: QtBot) -> None:
    view = ImageView()
    qtbot.addWidget(view)

    assert view.zoom == 1.0
    assert view.dragMode() == view.DragMode.ScrollHandDrag
