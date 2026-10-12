"""The small toolbar row above the item-tags panel.

Two checkable view toggles that don't belong in the View menu alongside
Focus Mode and Show Thumbnails, because both are specifically about
*this* row's neighborhood -- shuffling the very list Focus Mode/
thumbnails already govern, and a screen-filling mode independent enough
from Focus Mode (which only hides side panels, keeping the normal window
frame) that conflating the two would be confusing. See
`MainWindow._build_ui` for how this row is sized to match the panel
title's own height, and `MainWindow._apply_shuffle_mode`/
`_apply_true_fullscreen` for what the two buttons actually do.

Undo/redo share the row too, to its left -- momentary actions rather
than view toggles (see `_ActionIconButton`), wired to `MainWindow._undo`/
`_redo` and enabled/disabled from `History.can_undo()`/`can_redo()`.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen, QPolygon
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from prismic.ui import theme

_BUTTON_SIZE = 22
_ICON_MARGIN = 5


class _IconButton(QToolButton):
    """A hand-painted icon button with shared sizing and rendering.

    Same "paint it, don't trust an emoji glyph or a bitmap asset"
    approach `TagRowDelegate` takes for its row icons, so these read as
    the same visual language rather than a mismatched import. The concrete
    button chooses its icon colour from its checked or enabled state.

    No native tooltip: like the viewer's play/pause button (also a plain
    `QPushButton`/`QToolButton` with no `QAction` behind it), the live
    keyboard shortcut and description are surfaced through the
    hover-explainer bar instead -- see `MainWindow._build_status_bar`,
    which is also where these two get registered with it. A tooltip here
    would just be a second, easily-stale copy of the same text.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panelToolbarButton")
        self.setFixedSize(_BUTTON_SIZE, _BUTTON_SIZE)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event: QPaintEvent) -> None:
        # The QSS-driven background first (transparent, then a hover/
        # pressed wash -- see theme.py), so the custom icon on top isn't
        # the *only* thing responding to the mouse.
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self._icon_color()
        painter.setPen(QPen(QColor(color), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = self.rect().adjusted(_ICON_MARGIN, _ICON_MARGIN, -_ICON_MARGIN, -_ICON_MARGIN)
        self._paint_icon(painter, rect)

    def _icon_color(self) -> str:
        raise NotImplementedError

    def _paint_icon(self, painter: QPainter, rect: QRect) -> None:
        raise NotImplementedError


class _ToggleIconButton(_IconButton):
    """A checkable, hand-painted icon button."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        # Not part of tab order: mouse hover and the keyboard shortcut are
        # how this toggle is discovered, not tabbing to it.

    def _icon_color(self) -> str:
        return theme.KEYCAP_BORDER if self.isChecked() else theme.TEXT_SECONDARY


class _ActionIconButton(_IconButton):
    """A plain icon for a momentary action, greyed out when disabled."""

    def _icon_color(self) -> str:
        return theme.TEXT_SECONDARY if self.isEnabled() else theme.BORDER


def _paint_chevron(painter: QPainter, rect: QRect, *, pointing_left: bool) -> None:
    cx, cy = rect.center().x(), rect.center().y()
    half_w = rect.width() * 0.28
    half_h = rect.height() * 0.34
    near_x = cx + half_w if pointing_left else cx - half_w
    far_x = cx - half_w if pointing_left else cx + half_w
    path = QPainterPath()
    path.moveTo(near_x, cy - half_h)
    path.lineTo(far_x, cy)
    path.lineTo(near_x, cy + half_h)
    painter.drawPath(path)


class UndoButton(_ActionIconButton):
    """A plain left-pointing chevron, the conventional "back"/"undo" glyph."""

    def _paint_icon(self, painter: QPainter, rect: QRect) -> None:
        _paint_chevron(painter, rect, pointing_left=True)


class RedoButton(_ActionIconButton):
    """A plain right-pointing chevron, the conventional "forward"/"redo"
    glyph -- the mirror image of `UndoButton`."""

    def _paint_icon(self, painter: QPainter, rect: QRect) -> None:
        _paint_chevron(painter, rect, pointing_left=False)


class ShuffleButton(_ToggleIconButton):
    """Two crossing arrows, the conventional "shuffle" glyph (🔀)."""

    def _paint_icon(self, painter: QPainter, rect: QRect) -> None:
        x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
        # The crossing happens in a shallow band around vertical center --
        # near-horizontal lines that only dip/rise slightly to swap sides,
        # like the emoji this glyph stands in for -- rather than each
        # curve spanning the full icon height, which reads as a tall,
        # steep X instead of two crossing arrows.
        band = (y1 - y0) * 0.34
        y_center = (y0 + y1) / 2
        near_y = y_center - band
        far_y = y_center + band
        # A compact, conventional arrowhead -- wings spread wider than the
        # head is deep, like the crossing-arrows emoji this glyph is
        # standing in for, not a long needle poking out past the curve.
        # Narrower than the vertical gap between the two arrows (`band`),
        # so the two arrowheads' wide ends don't touch each other.
        spread = 2.5
        length = 3
        shaft_end = x1 - length
        # The bend itself sits left of center rather than at the true
        # midpoint -- both control points share this x -- so the crossing
        # happens early and the curve has already gone most of the way
        # flat well before it reaches the arrowhead, instead of still
        # visibly bending right up to where the triangle starts.
        ctrl_x = x0 + (shaft_end - x0) * 0.35 + 1

        # Two S-curves crossing in the middle -- bottom-left to top-right,
        # and top-left to bottom-right -- each with a horizontal tangent
        # at both ends, so the arrowhead below sits flush on a straight
        # approach rather than at an angle.
        upper = QPainterPath()
        upper.moveTo(x0, far_y)
        upper.cubicTo(ctrl_x, far_y, ctrl_x, near_y, shaft_end, near_y)
        lower = QPainterPath()
        lower.moveTo(x0, near_y)
        lower.cubicTo(ctrl_x, near_y, ctrl_x, far_y, shaft_end, far_y)
        painter.drawPath(upper)
        painter.drawPath(lower)

        # A small filled triangle at the right end of each curve, apex
        # pointing right -- reads far cleaner at this size than two thin
        # diagonal strokes, which blur into a fuzzy blob once
        # anti-aliased rather than a crisp arrowhead.
        fill_color = painter.pen().color()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill_color)
        for tip_y in (near_y, far_y):
            painter.drawPolygon(
                QPolygon(
                    [
                        QPoint(x1, round(tip_y)),
                        QPoint(shaft_end, round(tip_y - spread)),
                        QPoint(shaft_end, round(tip_y + spread)),
                    ]
                )
            )


class FullScreenButton(_ToggleIconButton):
    """Four corner brackets pointing outward, the conventional
    "full screen" glyph -- the same shape whether entering or already in
    full screen, per this widget's own docstring on why checked state is
    colour only."""

    def _paint_icon(self, painter: QPainter, rect: QRect) -> None:
        x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
        arm = max(3, min(rect.width(), rect.height()) // 3)
        # top-left
        painter.drawLine(x0, y0 + arm, x0, y0)
        painter.drawLine(x0, y0, x0 + arm, y0)
        # top-right
        painter.drawLine(x1 - arm, y0, x1, y0)
        painter.drawLine(x1, y0, x1, y0 + arm)
        # bottom-left
        painter.drawLine(x0, y1 - arm, x0, y1)
        painter.drawLine(x0, y1, x0 + arm, y1)
        # bottom-right
        painter.drawLine(x1 - arm, y1, x1, y1)
        painter.drawLine(x1, y1, x1, y1 - arm)


class PanelToolbar(QWidget):
    """The row itself -- just lays the two buttons out flush left. Its
    height is fixed from the outside (see `MainWindow._build_ui`) to
    match the panel title above/below it; nothing in here assumes a
    particular height on its own."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panelToolbar")
        # Undo/redo sit to the left of shuffle/full-screen -- a distinct
        # group (momentary actions rather than view toggles), but sharing
        # this row rather than a bar of its own since it's just as much
        # about "this row's neighborhood" as the other two.
        self.undo_button = UndoButton(self)
        self.redo_button = RedoButton(self)
        self.shuffle_button = ShuffleButton(self)
        self.fullscreen_button = FullScreenButton(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)
        layout.addWidget(self.undo_button)
        layout.addWidget(self.redo_button)
        layout.addWidget(self.shuffle_button)
        layout.addWidget(self.fullscreen_button)
        layout.addStretch(1)
