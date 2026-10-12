"""A titled tag list: a search-to-filter-or-create box on top, a list of
tag rows below.

Checked tags are always sorted to the top, so what's already applied (or,
for the filter panel, already active) reads at a glance; typing in the
search box narrows only the *unchecked* tags beneath them, leaving the
checked ones pinned in place. Hitting Enter always asks the caller to
create a tag with the typed name and immediately check it -- never picks
a row off the filtered list instead, even when one happens to fuzzy-match
what was typed, so Enter's outcome is exactly what was typed, not
whatever the filter narrowed down to. Clicking a filtered row is still
how you select an existing tag without typing its full name.

Row interaction itself (whole-row toggle, hover rename/delete icons,
inline rename) lives in `TagRowDelegate`; this widget only wires its
signals through and owns the search/filter bookkeeping. Purely a
presentation shell around `TagListModel` -- every user action comes out
as a Qt signal; nothing here calls into the application layer directly
(see `main_window.py`, which dispatches commands).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QHoverEvent, QMouseEvent
from PySide6.QtWidgets import QLabel, QLineEdit, QListView, QWidget

from prismic.domain.tag import Tag
from prismic.ui._layouts import vertical_stack
from prismic.ui.tag_model import TagListModel
from prismic.ui.tag_row_delegate import TagRowDelegate


class TagPanel(QWidget):
    toggle_requested = Signal(int)  # tag_id
    create_and_check_requested = Signal(str)  # name -- create the tag, then apply/select it
    rename_requested = Signal(int, str)  # tag_id, new_name
    delete_requested = Signal(int)  # tag_id
    hover_row_changed = Signal(object)  # int row index, or None when hovering no row

    def __init__(
        self, title: str, parent: QWidget | None = None, *, show_shortcuts: bool = False
    ) -> None:
        super().__init__(parent)
        self._tags: list[Tag] = []
        self._checked_ids: frozenset[int] = frozenset()

        self.model = TagListModel(self)

        self.search_box = QLineEdit(self)
        self.search_box.setObjectName("tagSearchBox")
        self.search_box.setPlaceholderText("Search or create…")
        self.search_box.textChanged.connect(self._apply_filter)
        self.search_box.returnPressed.connect(self._commit_search)

        self.list_view = QListView(self)
        self.list_view.setObjectName("tagList")
        # Never horizontal-scroll: a row's own text elides to fit instead
        # (TagRowDelegate), so a horizontal scrollbar here would only ever
        # be Qt reacting to a sub-pixel width miscalculation, not anything
        # actually cut off.
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.viewport().setMouseTracking(True)
        self.list_view.viewport().installEventFilter(self)
        self.list_view.setModel(self.model)
        self._delegate = TagRowDelegate(
            self.list_view, self.list_view, show_shortcuts=show_shortcuts
        )
        self._delegate.toggle_requested.connect(self.toggle_requested)
        self._delegate.delete_requested.connect(self.delete_requested)
        self._delegate.rename_committed.connect(self.rename_requested)
        self.list_view.setItemDelegate(self._delegate)

        # Public rather than a local: `MainWindow` reads this label's own
        # rendered height to size the shuffle/full-screen toolbar row it
        # places above the item-tags panel, so that row matches this
        # box's height exactly rather than a hard-coded guess at it.
        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("panelTitle")

        # Title + search box grouped into one widget so the hover-explainer
        # (see HoverHintController in main_window.py) can treat them as a
        # single hoverable target for this panel's focus shortcut, rather
        # than just the search box itself.
        self.header = QWidget(self)
        self.header.setObjectName("tagPanelHeader")
        vertical_stack(self.header, (self.title_label, self.search_box))
        vertical_stack(self, (self.header, self.list_view), stretch_index=1)

    def set_tags(self, tags: list[Tag], checked_ids: frozenset[int]) -> None:
        self._tags = tags
        self._checked_ids = checked_ids
        self._apply_filter()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.list_view.viewport():
            # QAbstractItemView drives its own row-hover repainting (the
            # rename/delete icons above) off HoverMove, not MouseMove --
            # mouse-tracking being on doesn't guarantee plain QMouseMove
            # events reach here too, so both are handled the same way.
            if isinstance(event, QMouseEvent | QHoverEvent) and event.type() in (
                QEvent.Type.MouseMove,
                QEvent.Type.HoverMove,
            ):
                index = self.list_view.indexAt(event.position().toPoint())
                self.hover_row_changed.emit(index.row() if index.isValid() else None)
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
                self.hover_row_changed.emit(None)
        return super().eventFilter(watched, event)

    def focus_search(self) -> None:
        self.search_box.setFocus()
        self.search_box.selectAll()

    def clear_search_keep_focus(self) -> None:
        """Clear the search box after a tag toggle, no matter what
        triggered it (row click, quick-select shortcut, or Enter-to-
        create) -- restoring focus explicitly rather than trusting that
        `clear()` alone leaves it in place."""
        had_focus = self.search_box.hasFocus()
        self.search_box.clear()
        if had_focus:
            self.search_box.setFocus()

    def set_shortcut_mode_selected(self, selected: bool) -> None:
        """Only meaningful for a panel constructed with `show_shortcuts`;
        a no-op otherwise since the delegate never reads the flag it'd
        set."""
        self._delegate.set_show_checked_shortcuts(selected)

    def set_shortcut_labels(self, labels: dict[int, str]) -> None:
        """Which key label each quick-select slot paints in its checkbox.

        Same caveat as `set_shortcut_mode_selected`: only a panel built
        with `show_shortcuts` paints them at all."""
        self._delegate.set_shortcut_labels(labels)

    def _unchecked_matches(self, query: str) -> list[Tag]:
        query = query.strip().lower()
        unchecked = [t for t in self._tags if t.id not in self._checked_ids]
        if not query:
            return unchecked
        return [t for t in unchecked if _is_fuzzy_match(query, t.name.lower())]

    def _apply_filter(self) -> None:
        checked = [t for t in self._tags if t.id in self._checked_ids]
        unchecked = self._unchecked_matches(self.search_box.text())
        self.model.set_tags(checked + unchecked, self._checked_ids)

    def _commit_search(self) -> None:
        query = self.search_box.text().strip()
        if not query:
            return
        self.create_and_check_requested.emit(query)
        self.clear_search_keep_focus()


def _is_fuzzy_match(query: str, text: str) -> bool:
    """True if every character of `query` appears in `text` in order,
    not necessarily contiguously -- "aion" matches "vacation" (v-A-c-a-t-
    I-O-N). A strict superset of substring matching, so this never hides
    a match the old substring search would have found. Both arguments are
    expected already lowercased."""
    remaining = iter(text)
    return all(char in remaining for char in query)
