"""The Settings window.

Two panels -- Shortcuts and Tag ranking -- built as a sidebar-plus-stack
rather than a bare list, so a further panel is an `addWidget` and a list
row rather than a rewrite of the window around it.

The shortcut list is generated from `SHORTCUTS` in
`application/input/shortcuts.py`, in the order declared there, grouped by
that definition's own category. Nothing is enumerated by hand here, so a
shortcut added to the registry shows up in this window automatically and
one removed from it disappears -- there is no second list to forget to
update.

Purely presentational plus one piece of state (`ShortcutBindings`, which
persists itself). Nothing here touches a collection, a session, or the
database; `MainWindow` listens for `bindings_changed` and re-applies the
new keys to the live UI.

Frameless, like every dialog in the app -- see `frameless_dialog.py` for
the shared window chrome (`FramelessDialog`, `TitleBar`) and for
`MessageDialog`, the themed replacement for the confirmation prompts this
window raises (`_confirm_conflicts`, `_restore_defaults`).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFocusEvent, QHideEvent, QIntValidator, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from prismic.application.input.shortcuts import (
    SHORTCUTS,
    ShortcutBindings,
    ShortcutDefinition,
    ShortcutScope,
    is_modifier_only,
    keycaps,
    normalize,
)
from prismic.application.input.shortcuts import (
    definition as shortcut_definition,
)
from prismic.application.tag_ranking_settings import (
    DEFAULT_CORRELATION_THRESHOLD,
    DEFAULT_MEGA_POPULAR_THRESHOLD,
    TagRankingSettings,
    TagRankingSettingsStore,
)
from prismic.persistence.repositories.tag_correlation_repository import DEFAULT_MIN_COOCCURRENCE
from prismic.ui.frameless_dialog import FramelessDialog, MessageDialog
from prismic.ui.keyboard import MODIFIER_KEY_NAMES, key_text

_UNSET_TEXT = "Not set"
_CAPTURING_TEXT = "Press a key…"


def _row_layout(
    parent: QWidget,
    text_column: QVBoxLayout,
    editor: QWidget,
    *trailing_widgets: QWidget,
) -> None:
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(10)
    layout.addLayout(text_column, 1)
    layout.addWidget(editor)
    for widget in trailing_widgets:
        layout.addWidget(widget)


def _reset_button(parent: QWidget, on_click: Callable[[], None]) -> QPushButton:
    button = QPushButton("Reset", parent)
    button.setObjectName("shortcutSmallButton")
    button.clicked.connect(on_click)
    return button


def binding_display(binding: str, *, held: bool = False) -> str:
    """A binding as one human-readable string ("Ctrl + Shift + O").

    Spaced around the separator rather than Qt's tight "Ctrl+Shift+O": at
    the size these are rendered, an unspaced run of short tokens reads as
    one word. Built from `keycaps()` so it stays in step with how the
    hover-explainer bar splits the same string into boxes.

    A bare modifier gets spelled out, because "Ctrl" on its own would
    otherwise read as an unfinished combination. Which gesture it's
    spelled out *as* isn't a property of the binding string alone,
    though: for almost every shortcut a lone modifier means "tapped
    alone, then released" (see `shortcuts.is_modifier_only()`), but for a
    `ShortcutScope.MODIFIER` entry (`TYPE_LITERALLY_MODIFIER` today) it
    means "held down while some other key is pressed" instead -- a
    genuinely different gesture on the same physical key. `held` is the
    caller's way of saying which one applies to the shortcut this binding
    belongs to.
    """
    if is_modifier_only(binding):
        gesture = "held" if held else "tapped alone"
        return f"{normalize(binding)} ({gesture})"
    caps = keycaps(binding)
    return " + ".join(caps) if caps else _UNSET_TEXT


class KeyCaptureButton(QPushButton):
    """Click, then press the key combination to bind.

    While capturing, this widget has to win every key in the alphabet
    *including* the ones Qt normally spends on its own navigation: Tab
    would move focus, Space and Enter would re-activate this button,
    Escape would close the dialog. So capture is handled in `event()`
    ahead of Qt's own handling rather than in `keyPressEvent`, and
    `ShortcutOverride` is accepted too so a combination that matches some
    `QAction`'s shortcut is delivered here as an ordinary key press
    instead of firing that action.

    A modifier tapped on its own is a binding too, not a half-finished
    combination -- the release is what tells the two apart, so both are
    handled here. Every shortcut accepts one; see
    `shortcuts.is_modifier_only()` for what it then means, and `held`
    below for the one case where it means something other than a tap.

    Escape is the one key that can't be bound this way, because it's the
    only way out of a capture the user didn't mean to start -- it cancels
    instead. That doesn't make Escape unbindable in general: it's the
    default for Dismiss, and a shortcut that's been moved off Escape can
    be put back with the row's own Reset button.
    """

    binding_captured = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, held: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("shortcutCaptureButton")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._binding = ""
        # Whether a bare-modifier binding on *this* shortcut means "held
        # down for another key" rather than "tapped alone" -- purely a
        # display concern, passed straight to `binding_display()`. See
        # that function's own docstring for why this isn't something the
        # binding string alone can say.
        self._held = held
        # A modifier that has gone down with nothing else since. Its
        # release is what turns it into a binding -- see `event()`.
        self._pending_modifier: int | None = None
        self.clicked.connect(self._on_clicked)

    @property
    def is_capturing(self) -> bool:
        return self.isChecked()

    def set_binding(self, binding: str) -> None:
        self._binding = binding
        self._refresh_text()

    def _refresh_text(self) -> None:
        if self.is_capturing:
            self.setText(_CAPTURING_TEXT)
        else:
            self.setText(binding_display(self._binding, held=self._held))
        # Styled from the property rather than an inline stylesheet, so
        # the whole look stays in theme.py with everything else.
        self.setProperty("unset", not self._binding and not self.is_capturing)
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def _on_clicked(self) -> None:
        self._refresh_text()
        if self.is_capturing:
            self.grabKeyboard()
        else:
            self.releaseKeyboard()

    def _stop_capturing(self) -> None:
        if self.is_capturing:
            self.releaseKeyboard()
            self.setChecked(False)
            self._refresh_text()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        # Clicking elsewhere (or tabbing away, which only happens once
        # capture has already ended) abandons a capture rather than
        # leaving an invisible one armed on an unfocused widget.
        self._stop_capturing()
        super().focusOutEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        # `grabKeyboard()` is an application-wide grab: while it's held,
        # every key event in the process comes here regardless of what
        # the user thinks they're typing into. Losing focus is the usual
        # way out (above), but closing the Settings window with a capture
        # still armed doesn't necessarily deliver a focus-out first --
        # and a grab held by a hidden, or since-destroyed, widget would
        # take the keyboard away from the whole app with nothing on
        # screen to explain why.
        self._stop_capturing()
        super().hideEvent(event)

    def event(self, event: QEvent) -> bool:
        if not self.is_capturing or not isinstance(event, QKeyEvent):
            return super().event(event)
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if event.type() == QEvent.Type.KeyRelease:
            return self._handle_release(event)
        if event.type() != QEvent.Type.KeyPress:
            return super().event(event)
        if event.key() == Qt.Key.Key_Escape:
            self._stop_capturing()
            return True
        if not event.isAutoRepeat():
            if self._pending_modifier is not None:
                # Something else went down while a modifier was held, so
                # it's a combination now, not a tap.
                self._pending_modifier = None
            elif event.key() in MODIFIER_KEY_NAMES:
                self._pending_modifier = event.key()
        captured = key_text(event)
        if captured is None:
            # A bare modifier. It could still become a combination (the
            # user is mid-chord) or end as a tap -- its release decides.
            return True
        self._pending_modifier = None
        self._stop_capturing()
        self.binding_captured.emit(captured)
        return True

    def _handle_release(self, event: QKeyEvent) -> bool:
        """A modifier let go with nothing pressed since it went down is a
        tap, and taps are bindable like any other input -- that's how the
        Edit list's numbering swap gets its default of plain Ctrl. Every
        other release is swallowed, since the press it belongs to was
        already dealt with above."""
        pending = self._pending_modifier
        if pending is None or event.isAutoRepeat() or event.key() != pending:
            return True
        self._pending_modifier = None
        self._stop_capturing()
        self.binding_captured.emit(MODIFIER_KEY_NAMES[pending])
        return True


class ShortcutRow(QWidget):
    """One shortcut: what it does on the left, what it's bound to on the
    right, and the two buttons for unbinding it and putting it back."""

    changed = Signal()

    def __init__(
        self,
        definition: ShortcutDefinition,
        bindings: ShortcutBindings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("shortcutRow")
        self.definition = definition
        self._bindings = bindings
        # See `binding_display()`: a bare modifier means something
        # different for this one scope than it does for every other
        # shortcut, and both the editor and the search haystack need to
        # know which reading applies here.
        self._held = definition.scope is ShortcutScope.MODIFIER

        self._label = QLabel(definition.label)
        self._label.setObjectName("shortcutLabel")
        self._description = QLabel(definition.description)
        self._description.setObjectName("shortcutDescription")
        self._description.setWordWrap(True)
        self._conflict = QLabel()
        self._conflict.setObjectName("shortcutConflict")
        self._conflict.setWordWrap(True)
        self._conflict.setVisible(False)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        text_column.addWidget(self._label)
        text_column.addWidget(self._description)
        text_column.addWidget(self._conflict)

        # One editor for every shortcut, with no per-command variations:
        # whether a binding turns out to be a key, a combination or a
        # bare modifier tap is decided by what the user presses into it,
        # not by anything the registry says about the command.
        self._editor = KeyCaptureButton(self, held=self._held)
        self._editor.binding_captured.connect(self._assign)
        self._editor.setFixedWidth(180)

        self._clear_button = QPushButton("Clear", self)
        self._clear_button.setObjectName("shortcutSmallButton")
        self._clear_button.clicked.connect(lambda: self._assign(""))
        self._reset_button = _reset_button(self, self._reset)

        _row_layout(self, text_column, self._editor, self._clear_button, self._reset_button)

        self.refresh()

    def matches(self, query: str) -> bool:
        """Whether this row survives the panel's search box. Matching on
        the binding too means "what's on Ctrl+T again?" is answerable by
        typing the key, not just the feature's name."""
        query = query.strip().lower()
        if not query:
            return True
        haystack = " ".join(
            (
                self.definition.label,
                self.definition.description,
                self.definition.category,
                binding_display(self._bindings.binding(self.definition.id), held=self._held),
            )
        ).lower()
        return query in haystack

    def refresh(self) -> None:
        binding = self._bindings.binding(self.definition.id)
        self._editor.set_binding(binding)
        self._clear_button.setEnabled(bool(binding))
        self._reset_button.setEnabled(not self._bindings.is_default(self.definition.id))
        conflicts = self._bindings.conflicts(self.definition.id, binding)
        if conflicts:
            names = ", ".join(shortcut_definition(other).label for other in conflicts)
            self._conflict.setText(f"Also bound to: {names}")
            self._conflict.setVisible(True)
        else:
            self._conflict.setVisible(False)

    def _assign(self, binding: str) -> None:
        current = self._bindings.binding(self.definition.id)
        if binding == current:
            self.refresh()
            return
        if binding and not self._confirm_conflicts(binding):
            self.refresh()
            return
        self._bindings.set_binding(self.definition.id, binding)
        self.changed.emit()

    def _confirm_conflicts(self, binding: str) -> bool:
        """Ask before taking a key off whatever else is using it.

        Returns False if the user backs out, leaving both shortcuts as
        they were. Only same-scope collisions are asked about -- see
        `ShortcutScope` for why Space on both Focus Mode and the viewer's
        play/pause is not one."""
        conflicts = self._bindings.conflicts(self.definition.id, binding)
        if not conflicts:
            return True
        names = ", ".join(shortcut_definition(other).label for other in conflicts)
        answer = MessageDialog.question(
            self,
            "Shortcut already in use",
            f"{binding_display(binding, held=self._held)} is already bound to {names}.\n\n"
            f"Assign it to “{self.definition.label}” and clear the other?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        for other in conflicts:
            self._bindings.set_binding(other, "")
        return True

    def _reset(self) -> None:
        self._bindings.reset(self.definition.id)
        self.changed.emit()


class ShortcutsPanel(QWidget):
    """Every shortcut in the app, grouped by category, each editable."""

    changed = Signal()

    def __init__(self, bindings: ShortcutBindings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bindings = bindings

        self._search_box = QLineEdit(self)
        self._search_box.setObjectName("settingsSearchBox")
        self._search_box.setPlaceholderText("Search shortcuts…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._apply_search)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(0)

        self.rows: list[ShortcutRow] = []
        self._headers: dict[str, QLabel] = {}
        self._separators_by_row: dict[ShortcutRow, QFrame] = {}
        current_category: str | None = None
        for definition in SHORTCUTS:
            if definition.category != current_category:
                current_category = definition.category
                header = QLabel(current_category.upper())
                header.setObjectName("panelTitle")
                content_layout.addWidget(header)
                self._headers[current_category] = header
            row = ShortcutRow(definition, bindings, content)
            row.changed.connect(self._on_row_changed)
            content_layout.addWidget(row)
            self.rows.append(row)
            separator = QFrame(content)
            separator.setObjectName("rowSeparator")
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setFixedHeight(1)
            content_layout.addWidget(separator)
            self._separators_by_row[row] = separator
        content_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Never horizontal-scroll, for the same reason `TagPanel` and the
        # result list don't: every row fits the viewport by construction
        # (the descriptions wrap, the editors are fixed-width), so a
        # horizontal scrollbar here is only ever Qt reacting to a
        # transient width miscalculation, not to anything actually cut
        # off. Left on the default policy it does exactly that -- on the
        # first layout pass, before the vertical scrollbar's width has
        # been taken out of the viewport, the content is momentarily too
        # wide and a horizontal bar appears for one frame and then goes
        # away again. That one frame is a visible flash when the window
        # opens.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        self._restore_button = QPushButton("Restore all defaults", self)
        self._restore_button.clicked.connect(self._restore_defaults)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addWidget(self._restore_button)
        footer.addStretch(1)

        self._empty_label = QLabel("No shortcuts match that search.")
        self._empty_label.setObjectName("emptyStateLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._search_box)
        layout.addWidget(self._empty_label)
        layout.addWidget(scroll, 1)
        layout.addLayout(footer)

    @property
    def search_box(self) -> QLineEdit:
        return self._search_box

    def visible_rows(self) -> list[ShortcutRow]:
        return [row for row in self.rows if row.isVisibleTo(self)]

    def _apply_search(self) -> None:
        query = self._search_box.text()
        shown_by_category: dict[str, int] = dict.fromkeys(self._headers, 0)
        for row in self.rows:
            visible = row.matches(query)
            row.setVisible(visible)
            self._separators_by_row[row].setVisible(visible)
            if visible:
                shown_by_category[row.definition.category] += 1
        for category, header in self._headers.items():
            header.setVisible(shown_by_category[category] > 0)
        self._empty_label.setVisible(not any(shown_by_category.values()))

    def _on_row_changed(self) -> None:
        # Every row, not just the edited one: taking a key away from
        # another shortcut (or restoring a default that collides with
        # one) changes what those rows should be showing too.
        self.refresh()
        self.changed.emit()

    def refresh(self) -> None:
        for row in self.rows:
            row.refresh()

    def _restore_defaults(self) -> None:
        answer = MessageDialog.question(
            self, "Restore default shortcuts", "Put every shortcut back to its default key?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._bindings.reset_all()
        self._on_row_changed()


class ThresholdRow(QWidget):
    """One percentage setting: what it does on the left, an editable
    percentage field and a reset-to-default button on the right -- the
    same left-text/right-controls shape as `ShortcutRow`, minus the
    capture-a-key machinery a plain percentage doesn't need."""

    changed = Signal()

    def __init__(
        self,
        label: str,
        description: str,
        *,
        default_fraction: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("shortcutRow")
        self._default_fraction = default_fraction
        self._fraction = default_fraction

        text_label = QLabel(label)
        text_label.setObjectName("shortcutLabel")
        text_description = QLabel(description)
        text_description.setObjectName("shortcutDescription")
        text_description.setWordWrap(True)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        text_column.addWidget(text_label)
        text_column.addWidget(text_description)

        self._editor = QLineEdit(self)
        self._editor.setValidator(QIntValidator(1, 100, self))
        self._editor.setFixedWidth(50)
        self._editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._editor.editingFinished.connect(self._commit)
        percent_sign = QLabel("%", self)

        self._reset_button = _reset_button(self, self._reset)

        _row_layout(self, text_column, self._editor, percent_sign, self._reset_button)

        self.refresh()

    @property
    def fraction(self) -> float:
        return self._fraction

    def set_fraction(self, fraction: float) -> None:
        self._fraction = fraction
        self.refresh()

    def refresh(self) -> None:
        self._editor.setText(str(round(self._fraction * 100)))
        self._reset_button.setEnabled(self._fraction != self._default_fraction)

    def _commit(self) -> None:
        text = self._editor.text()
        fraction = (int(text) if text else round(self._fraction * 100)) / 100
        if fraction == self._fraction:
            self.refresh()
            return
        self._fraction = fraction
        self.refresh()
        self.changed.emit()

    def _reset(self) -> None:
        if self._fraction == self._default_fraction:
            return
        self._fraction = self._default_fraction
        self.refresh()
        self.changed.emit()


class TagRankingPanel(QWidget):
    """The two thresholds behind the item tag panel's "check this next"
    promotion (see `application.tag_ranking.promote_ranked_tags`):
    correlated tags and mega-popular tags. Persists itself the same way
    `ShortcutsPanel` does -- through the store it's handed, on every
    change, rather than waiting for the dialog to be closed."""

    changed = Signal()

    def __init__(self, store: TagRankingSettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        settings = store.load()

        header = QLabel("TAG RANKING")
        header.setObjectName("panelTitle")

        self.correlation_row = ThresholdRow(
            "Correlated tags",
            "In the item tag panel, a tag that usually appears alongside a "
            "tag you've already checked is promoted to the top of the "
            'unchecked list. "Usually" means at least this percentage of '
            "the checked tag's files also carry the other one, counted only "
            f"once both tags appear together on at least {DEFAULT_MIN_COOCCURRENCE} files.",
            default_fraction=DEFAULT_CORRELATION_THRESHOLD,
            parent=self,
        )
        self.correlation_row.set_fraction(settings.correlation_threshold)
        self.correlation_row.changed.connect(self._on_row_changed)

        self.mega_popular_row = ThresholdRow(
            "Mega-popular tags",
            "A tag used on at least this percentage of the entire "
            "collection is promoted to the very top of the item tag "
            "panel's unchecked list, regardless of what's already checked.",
            default_fraction=DEFAULT_MEGA_POPULAR_THRESHOLD,
            parent=self,
        )
        self.mega_popular_row.set_fraction(settings.mega_popular_threshold)
        self.mega_popular_row.changed.connect(self._on_row_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.mega_popular_row)
        layout.addWidget(self.correlation_row)
        layout.addStretch(1)

    def _on_row_changed(self) -> None:
        self._store.save(
            TagRankingSettings(
                correlation_threshold=self.correlation_row.fraction,
                mega_popular_threshold=self.mega_popular_row.fraction,
            )
        )
        self.changed.emit()


class SettingsDialog(FramelessDialog):
    bindings_changed = Signal()
    tag_ranking_changed = Signal()

    def __init__(
        self,
        bindings: ShortcutBindings,
        parent: QWidget | None = None,
        *,
        tag_ranking_settings: TagRankingSettingsStore | None = None,
    ) -> None:
        super().__init__("Settings", parent, resizable=True)
        self.resize(760, 620)

        self.shortcuts_panel = ShortcutsPanel(bindings, self)
        self.shortcuts_panel.changed.connect(self.bindings_changed)

        self.tag_ranking_panel = TagRankingPanel(
            tag_ranking_settings if tag_ranking_settings is not None else TagRankingSettingsStore(),
            self,
        )
        self.tag_ranking_panel.changed.connect(self.tag_ranking_changed)

        self.panel_list = QListWidget(self)
        self.panel_list.setObjectName("settingsPanelList")
        self.panel_list.addItem("Shortcuts")
        self.panel_list.addItem("Tag ranking")
        self.panel_list.setCurrentRow(0)
        self.panel_list.setFixedWidth(150)
        self.panel_list.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.shortcuts_panel)
        self._stack.addWidget(self.tag_ranking_panel)
        self.panel_list.currentRowChanged.connect(self._stack.setCurrentIndex)

        self.title_bar.close_requested.connect(self.accept)

        close_button = QPushButton("Close", self)
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close_button)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.panel_list)
        body.addWidget(self._stack, 1)

        layout = self._install_body_layout(body, stretch=1)
        footer_widget = QWidget(self)
        footer_widget.setObjectName("settingsFooter")
        footer_widget.setLayout(footer)
        layout.addWidget(footer_widget)

        self._center_on_parent()
