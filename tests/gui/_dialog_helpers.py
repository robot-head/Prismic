"""Shared constructors for small message-dialog UI tests."""

from PySide6.QtWidgets import QMessageBox, QWidget

from prismic.ui.frameless_dialog import MessageDialog


def message_dialog(parent: QWidget | None = None) -> MessageDialog:
    return MessageDialog(
        parent=parent,
        title="Title",
        text="Text",
        buttons=QMessageBox.StandardButton.Ok,
        default=QMessageBox.StandardButton.Ok,
    )
