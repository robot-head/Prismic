"""Shared conversion from stored shortcut bindings to Qt key sequences."""

from PySide6.QtGui import QKeySequence


def portable_key_sequence(binding: str) -> QKeySequence:
    if not binding:
        return QKeySequence()
    return QKeySequence(binding, QKeySequence.SequenceFormat.PortableText)
