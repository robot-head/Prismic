from __future__ import annotations

from pytestqt.qtbot import QtBot

from tests.gui._progress_test_helpers import report_progress
from tests.gui.helpers import make_scan_progress_bar


def test_reset_progress_defaults_to_the_later_scan_label(qtbot: QtBot) -> None:
    bar = make_scan_progress_bar(qtbot)

    bar.reset_progress()

    assert bar.format() == "Detecting any moved files"
    assert (bar.minimum(), bar.maximum()) == (0, 0)


def test_reset_progress_with_is_first_scan_shows_the_scanning_label(qtbot: QtBot) -> None:
    bar = make_scan_progress_bar(qtbot)

    bar.reset_progress(is_first_scan=True)

    assert bar.format() == "Scanning all files"


def test_the_label_does_not_change_as_progress_ticks_in(qtbot: QtBot) -> None:
    """The label reflects which *pass* this is, decided once up front --
    not re-derived per tick from `expected_total`, which would flicker if
    a brand-new collection's `expected_total` (0) were confused with an
    ordinary rescan of a genuinely empty one."""
    bar = make_scan_progress_bar(qtbot)
    bar.reset_progress(is_first_scan=True)

    report_progress(qtbot, bar)

    assert bar.format() == "Scanning all files"


def test_scan_progress_bar_starts_in_later_scan_mode_and_clamps_its_range(qtbot: QtBot) -> None:
    bar = make_scan_progress_bar(qtbot)

    assert bar.format() == "Detecting any moved files"
    assert bar.isTextVisible()
    assert (bar.minimumWidth(), bar.maximumWidth()) == (300, 300)
    assert (bar.minimum(), bar.maximum(), bar.value()) == (0, 0, 0)

    report_progress(qtbot, bar)

    assert (bar.minimum(), bar.maximum()) == (0, 3)
