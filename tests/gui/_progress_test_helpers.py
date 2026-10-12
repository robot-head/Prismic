"""Shared scan progress updates for progress bar tests."""

from pytestqt.qtbot import QtBot

from prismic.ui.scan_progress_bar import ScanProgressBar


def report_progress(qtbot: QtBot, bar: ScanProgressBar) -> None:
    bar.report_progress(3, 0)
    qtbot.waitUntil(lambda: bar.value() == 3, timeout=1000)
