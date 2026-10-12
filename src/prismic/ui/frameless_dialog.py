"""Dialog chrome shared by every custom window in the app.

`SettingsDialog` and `MessageDialog` are both all app-themed surfaces, so
a native OS title bar/icon/X around either one read as a different
program's window sitting on top of this one. Both go frameless instead,
replaced by `TitleBar` below -- which is what makes this module worth
having on its own rather than duplicating the frameless mechanics (the
window flag, the flash-free positioning, the title bar itself) once per
dialog and letting the copies drift.

`FramelessDialog` owns exactly that mechanics; it has no opinion on what
closing the window *means* (accept, reject, or something else), which is
left to each subclass to wire up on `title_bar.close_requested` itself.
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from prismic.ui import theme


class TitleBar(QWidget):
    """A window's own title strip, standing in for the native one.

    A frameless window still needs the two things a title bar is
    actually load-bearing for: somewhere to grab the window by, and a
    way to close it.

    Dragging is handed to `QWindow::startSystemMove()` rather than
    tracked by hand from mouse deltas. It asks the window manager to run
    its own move loop, which is what keeps edge snapping, multi-monitor
    boundaries and per-monitor DPI working -- all things a manual
    "remember the press offset and call move()" implementation quietly
    gets wrong, and which are the reason hand-rolled title bars tend to
    feel slightly off.
    """

    close_requested = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dialogTitleBar")

        self._label = QLabel(title, self)
        self._label.setObjectName("dialogTitle")

        self.close_button = QPushButton("✕", self)
        self.close_button.setObjectName("windowCloseButton")
        # Never the dialog's default button: Return belongs to whatever
        # the user is actually working in, not to closing the window.
        self.close_button.setAutoDefault(False)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.clicked.connect(self.close_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._label)
        layout.addStretch(1)
        layout.addWidget(self.close_button)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        # Deliberately swallowed. On a native title bar a double-click
        # maximizes, which for any of this app's fixed-purpose dialogs is
        # never what's wanted -- and without the native frame there'd be
        # no obvious way back out of it.
        event.accept()


class SizeGrip(QSizeGrip):
    """A resize corner that's actually visible.

    `QSizeGrip` leaves its own painting to the platform style, and this
    app's stylesheet sets a background on every `QWidget` -- which wins,
    blanking the style's diagonal lines and leaving a working but
    completely invisible handle. Drawing it here is the same approach
    `TagRowDelegate` takes for its row icons: paint it rather than hope
    the style survives the QSS.

    Resizing itself is still `QSizeGrip`'s; only the pixels are ours.
    """

    _SIZE = 16

    def __init__(self, parent: QWidget) -> None:
        # Required, not optional, unlike the other widgets here:
        # QSizeGrip resizes *its window*, so one without a parent has
        # nothing to act on.
        super().__init__(parent)
        self.setFixedSize(self._SIZE, self._SIZE)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme.TEXT_MUTED), 1.4))
        # Three diagonals of increasing length toward the corner -- the
        # conventional grip, so it needs no explaining.
        for offset in (3, 7, 11):
            painter.drawLine(
                self._SIZE - 2, self._SIZE - offset, self._SIZE - offset, self._SIZE - 2
            )


class FramelessDialog(QDialog):
    """A `QDialog` with no native frame, plus everything that loses.

    Subclasses build their own layout -- adding `self.title_bar` as the
    first widget -- and are responsible for two things this base
    deliberately doesn't do on their behalf: wiring
    `title_bar.close_requested` to whatever "close" means for that
    dialog, and calling `_center_on_parent()` once their layout (and any
    explicit `resize()`) is in place.
    """

    def __init__(
        self, title: str, parent: QWidget | None = None, *, resizable: bool = False
    ) -> None:
        super().__init__(parent)
        self.setObjectName("appDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        # No native title bar, icon or close button: see this module's
        # docstring. Set before `_center_on_parent()` calls `create()`,
        # since changing window flags after the native window exists
        # destroys and recreates it.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

        self.title_bar = TitleBar(title, self)

        # Frameless windows lose the native resize border along with the
        # rest of the frame. Only a dialog whose content can usefully
        # grow opts in -- a message box's size follows its text, so it
        # has nothing to gain from one.
        self._size_grip = SizeGrip(self) if resizable else None

    def _install_body_layout(self, body: QLayout, *, stretch: int = 0) -> QVBoxLayout:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_bar)
        layout.addLayout(body, stretch)
        return layout

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        grip = self._size_grip
        if grip is not None:
            # One pixel in from each edge, clearing the window's own
            # border.
            grip.move(self.width() - grip.width() - 1, self.height() - grip.height() - 1)
            grip.raise_()

    def _center_on_parent(self) -> None:
        """Place the window over its parent before it is ever shown.

        Not cosmetic bookkeeping -- this is what stops a visible flash on
        open. Left to itself, `QDialog::adjustPosition()` runs *twice*:
        once before the window is mapped, when the frame margins aren't
        known yet and count as zero, and again once they are. So the
        dialog appears at one position and then jumps by the size of its
        own title bar and border, on the frame *after* it became visible.
        Measured as a (-10, -10) `Move` arriving after `Show`, with the
        first `Paint` only afterwards.

        Calling `move()` at all sets `Qt::WA_Moved`, which is the flag
        `adjustPosition()` checks before doing anything -- so positioning
        it once, ourselves, replaces the two-step entirely.

        `create()` is what makes that a fair trade rather than swapping a
        flash for a misplaced window: it builds the native window without
        showing it, which is the point at which the frame margins become
        real (0/30/0/0 on Windows 11 -- a title bar and no border). With
        them in hand we can centre the *frame*, which is what Qt's second
        pass was for, while still doing it entirely before the window is
        on screen.
        """
        parent = self.parentWidget()
        if parent is None:
            return  # a parentless dialog is the platform's to place
        self.create()
        handle = self.windowHandle()
        margins = handle.frameMargins() if handle is not None else QMargins()

        frame = QRect(
            QPoint(),
            QSize(
                self.width() + margins.left() + margins.right(),
                self.height() + margins.top() + margins.bottom(),
            ),
        )
        frame.moveCenter(parent.window().frameGeometry().center())

        screen = parent.window().screen()
        if screen is not None:
            # The same clamp Qt applies, for when the main window is
            # itself partly off-screen -- without it, centring on that
            # window would put this one's title bar out of reach.
            available = screen.availableGeometry()
            frame.moveLeft(
                max(available.left(), min(frame.left(), available.right() - frame.width()))
            )
            frame.moveTop(
                max(available.top(), min(frame.top(), available.bottom() - frame.height()))
            )

        self.move(frame.left() + margins.left(), frame.top() + margins.top())


# Button captions in the order they should appear, left to right. Every
# call site in this app only ever asks for a subset of {Yes, Cancel} or
# {Ok} alone, but resolving generically off `QMessageBox.StandardButton`
# costs nothing extra and matches the static helpers this class replaces
# closely enough that a call site is a near-mechanical find/replace.
_BUTTON_ORDER: tuple[tuple[QMessageBox.StandardButton, str], ...] = (
    (QMessageBox.StandardButton.Yes, "Yes"),
    (QMessageBox.StandardButton.No, "No"),
    (QMessageBox.StandardButton.Ok, "OK"),
    (QMessageBox.StandardButton.Cancel, "Cancel"),
)


class MessageDialog(FramelessDialog):
    """A themed, frameless stand-in for `QMessageBox`'s static helpers.

    Not built on top of a real `QMessageBox`: that class constructs its
    own internal layout with no supported way to insert a title bar
    ahead of it, and instantiating one at all would still carry the
    native frame this module exists to remove. Rebuilt from a plain
    `QDialog` instead, with just enough of the original's surface
    (`question`/`warning`/`critical`, returning the same
    `QMessageBox.StandardButton` values) that a call site is a drop-in
    swap of which class it names.
    """

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton,
        default: QMessageBox.StandardButton,
    ) -> None:
        super().__init__(title, parent)
        # What `exec()` reports if the dialog closes some way other than
        # a button click -- Escape, or the title bar's own X. Matches
        # `QMessageBox`'s own convention of falling back to whichever
        # button was marked default.
        self.clicked_button = default
        self.title_bar.close_requested.connect(self.reject)

        label = QLabel(text, self)
        label.setObjectName("messageDialogText")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Wide enough for a normal sentence or two before wrapping, so a
        # short message doesn't stretch edge-to-edge and a long one
        # doesn't grow the dialog absurdly wide instead of tall.
        label.setMaximumWidth(420)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)
        for flag, caption in _BUTTON_ORDER:
            if not buttons & flag:
                continue
            button = QPushButton(caption, self)
            if flag == default:
                # A border rather than a filled accent: this marks "what
                # Enter does," not "the recommended choice" -- the two
                # aren't the same thing when the default is Cancel, which
                # it is for every confirmation in this app.
                button.setObjectName("messageDialogDefaultButton")
                button.setDefault(True)
            button.clicked.connect(lambda _checked=False, flag=flag: self._choose(flag))
            button_row.addWidget(button)

        body = QVBoxLayout()
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(16)
        body.addWidget(label)
        body.addLayout(button_row)

        self._install_body_layout(body)

        self.setMinimumWidth(360)
        self.adjustSize()  # settle to the layout's own size before centering
        self._center_on_parent()

    def _choose(self, flag: QMessageBox.StandardButton) -> None:
        self.clicked_button = flag
        self.accept()

    @staticmethod
    def question(
        parent: QWidget | None,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton = (
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        ),
        default: QMessageBox.StandardButton = QMessageBox.StandardButton.Cancel,
    ) -> QMessageBox.StandardButton:
        dialog = MessageDialog(parent, title, text, buttons, default)
        dialog.exec()
        return dialog.clicked_button

    @staticmethod
    def _show_ok(parent: QWidget | None, title: str, text: str) -> None:
        MessageDialog(
            parent, title, text, QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Ok
        ).exec()

    @staticmethod
    def warning(parent: QWidget | None, title: str, text: str) -> None:
        MessageDialog._show_ok(parent, title, text)

    @staticmethod
    def critical(parent: QWidget | None, title: str, text: str) -> None:
        MessageDialog._show_ok(parent, title, text)
