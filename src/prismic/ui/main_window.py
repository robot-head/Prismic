"""Main application window.

Everything above persistence goes through the Phase 3 application layer:
no widget here reads or writes the database or filesystem directly. Reads
go through repositories/queries; every mutation goes through
`PrismicSession.execute()`.
"""

from __future__ import annotations

import random
from concurrent.futures import Future
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QObject,
    QSettings,
    Qt,
    QTimer,
)
from PySide6.QtGui import QAction, QCloseEvent, QKeyEvent, QKeySequence
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from prismic.application.commands.filter_commands import (
    FilterDeselectCommand,
    FilterSelectCommand,
)
from prismic.application.commands.mapping_commands import (
    MappingAddCommand,
    MappingRemoveCommand,
    MappingSetForManyCommand,
)
from prismic.application.commands.tag_commands import (
    TagCreateCommand,
    TagDeleteCommand,
    TagRenameCommand,
)
from prismic.application.input import shortcuts
from prismic.application.input.shortcuts import ShortcutBindings, keycaps
from prismic.application.queries.media_query import eligible_media
from prismic.application.session import PrismicSession
from prismic.application.tag_ranking import promote_ranked_tags
from prismic.application.tag_ranking_settings import TagRankingSettingsStore
from prismic.domain.media import Media
from prismic.domain.tag import Tag
from prismic.indexing.reconciler import ReconciliationResult
from prismic.persistence.errors import (
    CollectionLockedError,
    DuplicateTagNameError,
    PersistenceError,
)
from prismic.ui.column_splitter import ColumnSplitter
from prismic.ui.frameless_dialog import MessageDialog
from prismic.ui.future_watcher import FutureWatcher
from prismic.ui.hover_explainer_bar import HoverExplainerBar
from prismic.ui.hover_hint import HoverHintController
from prismic.ui.instance_bridge import InstanceBridge, request_focus
from prismic.ui.keyboard import (
    MODIFIER_KEY_NAMES,
    KeyboardController,
    key_text,
    literal_character,
    strip_modifier_prefix,
)
from prismic.ui.panel_toolbar import PanelToolbar
from prismic.ui.result_list_view import ResultListView
from prismic.ui.result_model import MediaIdRole, ResultListModel
from prismic.ui.scan_progress_bar import ScanProgressBar
from prismic.ui.selection_grid_view import GRID_THUMBNAIL_DIMENSION, SelectionGridView
from prismic.ui.settings_dialog import SettingsDialog
from prismic.ui.tag_model import CheckedRole, CheckedSlotRole, UncheckedSlotRole
from prismic.ui.tag_panel import TagPanel
from prismic.ui.thumbnail_delegate import ThumbnailDelegate
from prismic.ui.thumbnail_provider import ThumbnailProvider
from prismic.ui.thumbnail_services import ThumbnailServices
from prismic.ui.transient_message_bar import TransientMessageBar
from prismic.ui.viewer import MediaViewer

_VIEW_HISTORY_LIMIT = 1000


class MainWindow(QMainWindow):
    def __init__(
        self,
        initial_path: Path | None = None,
        bindings: ShortcutBindings | None = None,
        tag_ranking_settings: TagRankingSettingsStore | None = None,
    ) -> None:
        super().__init__()
        # Injectable so tests can hand in a store pointed at a temp file
        # instead of writing to (and reading back) the real user-wide
        # preferences file on the machine running them.
        self._bindings = bindings if bindings is not None else ShortcutBindings()
        self._tag_ranking_settings = (
            tag_ranking_settings if tag_ranking_settings is not None else TagRankingSettingsStore()
        )
        self.setWindowTitle("Prismic")
        self.resize(1280, 800)
        saved_geometry = QSettings().value("window/geometry")
        if saved_geometry is not None:
            self.restoreGeometry(saved_geometry)
        else:
            # No prior session to restore -- maximized is the sane default
            # rather than the arbitrary 1280x800 fallback size above.
            self.showMaximized()
        self.session: PrismicSession | None = None
        self._future_watchers: list[FutureWatcher] = []
        self._instance_bridge: InstanceBridge | None = None
        # Sticky last arrow-key direction, so preloading can bias further
        # ahead of travel than behind -- see _preload_neighbors().
        self._nav_direction = 1
        # Tap-gesture tracking, for shortcuts bound to a bare modifier
        # (the Edit list's numbering swap, by default). `_keys_down` is
        # every key currently held; `_tap_candidate_key` is a modifier
        # that has been alone the whole time it's been down, and its own
        # release fires whatever is bound to it.
        #
        # The set is doing real work, not bookkeeping: this filter is
        # installed on the *application*, so it sees each key event more
        # than once as Qt propagates it up the parent chain, and a plain
        # "any other press cancels the tap" flag cancels itself on the
        # second delivery of the very press that armed it. Adding to a
        # set is idempotent, so re-deliveries are harmless.
        self._keys_down: set[int] = set()
        self._tap_candidate_key: int | None = None
        # See _stable_item_tags(): the item-tag panel's checked-group
        # ordering for whichever file is current, held stable across
        # add/remove until that file changes.
        self._item_tag_order: list[int] = []
        self._item_tag_order_item_id: int | None = None
        # See `_apply_shuffle_mode`/`_reordered_by_shuffle`: whether the
        # result list is currently shuffled, the shuffled arrangement
        # itself (persists across refreshes rather than being
        # re-randomized every time), and -- regardless of whether
        # shuffle is on -- the order `_refresh_all()` actually displayed
        # last, which is what arrow-key navigation steps through instead
        # of the domain layer's own always-path-order `result_set`.
        self._shuffle_enabled = False
        self._shuffled_order: list[int] = []
        self._display_order: list[int] = []
        # See `_apply_true_fullscreen`: the window state from just before
        # entering full screen, so leaving it can restore *that* --
        # maximized included -- rather than always landing on plain
        # windowed, which is what `showNormal()` alone would do.
        self._pre_fullscreen_state = Qt.WindowState.WindowNoState
        # See `_record_view`/`_step_history`: every single file shown in the
        # viewer, in order, and where in that list the viewer currently is.
        # Ids, not result-set positions, so an entry stays reachable after
        # the filter stops including it.
        self._view_history: list[int] = []
        self._view_history_index = -1

        self._build_ui()
        self._build_status_bar()
        self._build_menu()

        self.keyboard = KeyboardController(
            self._bindings,
            on_navigate_previous=lambda: self._navigate(-1),
            on_navigate_next=lambda: self._navigate(1),
            on_history_back=lambda: self._step_history(-1),
            on_history_forward=lambda: self._step_history(1),
            on_undo=self._undo,
            on_redo=self._redo,
            on_focus_item_tags=self.item_tag_panel.focus_search,
            on_toggle_tag_shortcut=self._on_toggle_tag_shortcut,
            on_toggle_focus_mode=self._toggle_focus_mode,
            on_swap_tag_numbering=self._toggle_tag_shortcut_mode,
            on_shuffle_results=self.panel_toolbar.shuffle_button.toggle,
            on_true_fullscreen=self.panel_toolbar.fullscreen_button.toggle,
            parent=self,
        )
        self._apply_bindings()
        # Installed on the application, not just this window: a normal Qt
        # keyPressEvent override only fires when *this widget* has focus,
        # but Qt delivers key events to whatever child widget is focused
        # first -- and QAbstractItemView (the tag/result lists) has its own
        # built-in "type to search" behavior that swallows plain letter/
        # digit keys before they'd ever reach here. Global commands (and
        # the tag-shortcut digits, which deliberately win even over a
        # focused text box -- see keyboard.py) need to fire regardless of
        # which child last had a click, so they're intercepted at the
        # application level instead.
        app = QApplication.instance()
        assert app is not None  # a QApplication always exists by the time a QWidget is built
        app.installEventFilter(self)

        if initial_path is not None:
            # Deferred to the next event-loop iteration rather than opened
            # right here: the caller (bootstrap.run()) calls `.show()`
            # immediately after constructing this window, before starting
            # the event loop -- opening synchronously in __init__ meant a
            # "collection already open elsewhere" message dialog could pop up
            # against a window that was never actually shown yet, then an
            # empty placeholder window would appear only *after* the
            # dialog was dismissed. A zero-delay QTimer runs after `.show()`
            # has taken effect, so the window is visibly there first and
            # any error dialog reads as "this window couldn't open X"
            # rather than appearing to come from nowhere.
            QTimer.singleShot(0, lambda: self.open_collection(initial_path, is_startup=True))

    def _build_ui(self) -> None:
        self._placeholder = QLabel("No collection open")
        self._placeholder.setObjectName("emptyStateLabel")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Two independent tag lists rather than one dual-purpose one: the
        # top panel edits which tags are mapped to the file currently in
        # the viewer, the bottom narrows which files are browsable at all
        # (an intersection filter). Conflating "check to filter" and
        # "check to tag" into a single list would mean browsing could
        # silently mutate a file's tags -- kept deliberately separate.
        self.item_tag_panel = TagPanel("Edit this file", show_shortcuts=True)
        self.item_tag_panel.toggle_requested.connect(self._on_item_tag_toggle)
        self.item_tag_panel.create_and_check_requested.connect(self._on_item_create_and_check)
        self.item_tag_panel.rename_requested.connect(self._on_tag_rename)
        self.item_tag_panel.delete_requested.connect(self._on_tag_delete)
        self.item_tag_panel.hover_row_changed.connect(self._on_item_tag_hover)

        self.filter_panel = TagPanel("Filter")
        self.filter_panel.toggle_requested.connect(self._on_filter_toggle)
        self.filter_panel.create_and_check_requested.connect(self._on_filter_create_and_check)
        self.filter_panel.rename_requested.connect(self._on_tag_rename)
        self.filter_panel.delete_requested.connect(self._on_tag_delete)

        self._tag_splitter = QSplitter(Qt.Orientation.Vertical)
        self._tag_splitter.addWidget(self.item_tag_panel)
        self._tag_splitter.addWidget(self.filter_panel)
        self._tag_splitter.setSizes([1, 1])
        self._tag_splitter.setHandleWidth(1)

        # Sits above the item-tags panel, not inside it: shuffle and full
        # screen are both properties of the *browsing session* as a
        # whole (which items are visible/how much of the screen they get)
        # rather than of "Edit this file" specifically -- they just have
        # nowhere else short/wide enough to live without their own menu
        # entries, which they don't need for two toggles used with the
        # mouse. Height matched to the title box directly above it in
        # the same column, queried rather than guessed at, so a font or
        # padding change to one keeps the other in step automatically.
        self.panel_toolbar = PanelToolbar()
        self.panel_toolbar.setFixedHeight(self.item_tag_panel.title_label.sizeHint().height())
        self.panel_toolbar.shuffle_button.toggled.connect(self._apply_shuffle_mode)
        self.panel_toolbar.fullscreen_button.toggled.connect(self._apply_true_fullscreen)
        self.panel_toolbar.undo_button.clicked.connect(self._undo)
        self.panel_toolbar.redo_button.clicked.connect(self._redo)
        self.panel_toolbar.undo_button.setEnabled(False)
        self.panel_toolbar.redo_button.setEnabled(False)

        self._left_column = QWidget()
        left_column_layout = QVBoxLayout(self._left_column)
        left_column_layout.setContentsMargins(0, 0, 0, 0)
        left_column_layout.setSpacing(0)
        left_column_layout.addWidget(self.panel_toolbar)
        left_column_layout.addWidget(self._tag_splitter, 1)

        self.thumbnail_provider = ThumbnailProvider(parent=self)
        self.thumbnail_provider.thumbnail_ready.connect(self._on_thumbnail_ready)
        self.thumbnail_provider.decode_failed.connect(self._on_thumbnail_ready)
        # A separate, larger-decode instance for the selection grid --
        # not the same one the result list's small rows use, since that
        # one's `THUMBNAIL_DIMENSION` (160px) reads as visibly blurry once
        # stretched across a grid cell that's often several hundred pixels
        # wide. Its own cache means switching between the list's thumbnail
        # and the grid's larger one for the same file never collide.
        self.grid_thumbnail_provider = ThumbnailProvider(
            dimension=GRID_THUMBNAIL_DIMENSION, parent=self
        )

        self.result_model = ResultListModel(self)
        self.result_list = ResultListView()
        self.result_list.setObjectName("resultList")
        # Never horizontal-scroll -- see TagPanel's matching setting for why.
        self.result_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.result_list.viewport().setMouseTracking(True)
        self.result_list.setModel(self.result_model)
        self._thumbnail_delegate = ThumbnailDelegate(
            ThumbnailServices(
                self.thumbnail_provider,
                lambda: self.session.worker_pool if self.session is not None else None,
            ),
            self._resolve_media_path,
            self.result_list,
        )
        self.result_list.setItemDelegate(self._thumbnail_delegate)
        # Both signals feed the same handler: `currentChanged` alone misses
        # a shift/ctrl-click that adds rows without moving the current one
        # (e.g. ctrl-clicking a row that becomes current anyway still needs
        # `selectionChanged` for a *different* reason -- the full selected
        # set changed, not just the anchor), and `selectionChanged` alone
        # misses the reverse. The handler re-derives both from the view
        # regardless of which one fired, so there's no per-signal branching.
        self.result_list.selectionModel().currentChanged.connect(self._on_result_selection_changed)
        self.result_list.selectionModel().selectionChanged.connect(
            self._on_result_selection_changed
        )

        self.viewer = MediaViewer(
            worker_pool=lambda: self.session.worker_pool if self.session is not None else None
        )
        self.viewer.load_error.connect(self._on_viewer_error)
        self.selection_grid = SelectionGridView(
            ThumbnailServices(
                self.grid_thumbnail_provider,
                lambda: self.session.worker_pool if self.session is not None else None,
            )
        )
        # Swaps between the single-item viewer and the multi-select grid --
        # see `_show_current_media` -- rather than the viewer sitting
        # directly in the splitter as it used to.
        self._media_stack = QStackedWidget()
        self._media_stack.addWidget(self.viewer)
        self._media_stack.addWidget(self.selection_grid)

        splitter = ColumnSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._left_column)
        splitter.addWidget(self.result_list)
        splitter.addWidget(self._media_stack)
        # The drawn line stays 1px (see ColumnSplitter) but the actual
        # draggable area is much wider -- anything close to the old 1px
        # hitbox is too imprecise a mouse target to register as "wider" at
        # all, let alone easy to grab.
        splitter.setHandleWidth(20)
        saved_sizes = QSettings().value("window/columnSplitterSizes")
        if saved_sizes is not None:
            splitter.setSizes([int(size) for size in saved_sizes])
        else:
            splitter.setSizes([190, 260, 830])
        self._splitter = splitter

        self._central_stack = QStackedWidget()
        self._central_stack.addWidget(self._placeholder)
        self._central_stack.addWidget(self._splitter)
        self.setCentralWidget(self._central_stack)

    def _build_status_bar(self) -> None:
        self._hover_bar = HoverExplainerBar()
        self._scan_progress_bar = ScanProgressBar()
        self._transient_bar = TransientMessageBar()
        # Regular (non-permanent) widget: left-aligned, stretches to fill
        # whatever space the permanent widget on the right doesn't need --
        # see HoverExplainerBar's own size policy for what happens when
        # the two would otherwise overlap.
        self.statusBar().addWidget(self._hover_bar, 1)
        # Permanent: right-aligned, always visible -- this is what
        # replaces QStatusBar's own showMessage() area (see
        # TransientMessageBar's docstring). The scan indicator sits to its
        # left within that same permanent region, and is hidden except
        # while a reconciliation is in flight (see _watch_reconciliation).
        self.statusBar().addPermanentWidget(self._scan_progress_bar)
        self.statusBar().addPermanentWidget(self._transient_bar)

        self._hover_hints = HoverHintController(self._hover_bar, self._bindings, self)
        self._hover_hints.register_widget(
            self.viewer.play_pause_button, shortcuts.VIEWER_PLAY_PAUSE, "Play or pause the video"
        )
        self._hover_hints.register_widget(
            self.item_tag_panel.header, shortcuts.FOCUS_TAG_SEARCH, "Cycle between edit and filter"
        )
        self._hover_hints.register_widget(
            self.filter_panel.header, shortcuts.FOCUS_TAG_SEARCH, "Cycle between edit and filter"
        )
        self._hover_hints.register_static(
            self.panel_toolbar.undo_button, ("Ctrl", "Z"), "Undo the last tag change"
        )
        self._hover_hints.register_static(
            self.panel_toolbar.redo_button, ("Ctrl", "Y"), "Redo the last undone tag change"
        )
        self._hover_hints.register_widget(
            self.panel_toolbar.shuffle_button,
            shortcuts.SHUFFLE_RESULTS,
            shortcuts.definition(shortcuts.SHUFFLE_RESULTS).description,
        )
        self._hover_hints.register_widget(
            self.panel_toolbar.fullscreen_button,
            shortcuts.TRUE_FULLSCREEN,
            shortcuts.definition(shortcuts.TRUE_FULLSCREEN).description,
        )

    def _build_menu(self) -> None:
        # No key is spelled out in here: actions are registered by shortcut
        # id, and `_apply_bindings()` is the single place that turns an id
        # into a real key, so rebinding one in Settings updates its menu
        # entry too. Actions passed to `_register_action_shortcut` get a
        # real QShortcut; the two below it deliberately don't -- see their
        # own comments for why.
        self._shortcut_actions: dict[str, QAction] = {}

        file_menu = self.menuBar().addMenu("&File")

        open_folder_action = file_menu.addAction(
            "Open Collection Folder…", self._prompt_open_folder
        )
        self._register_action_shortcut(
            open_folder_action, file_menu, shortcuts.OPEN_COLLECTION_FOLDER
        )

        open_file_action = file_menu.addAction("Open .prismic File…", self._prompt_open_file)
        self._register_action_shortcut(open_file_action, file_menu, shortcuts.OPEN_COLLECTION_FILE)

        file_menu.addSeparator()

        # Menu-only, deliberately: no shortcut id, no QShortcut, no hover
        # hint -- rescanning is rare enough that it doesn't need a key of
        # its own competing for bindings.
        file_menu.addAction("Rescan", self._rescan)

        file_menu.addSeparator()

        settings_action = file_menu.addAction("Settings…", self.open_settings)
        self._register_action_shortcut(settings_action, file_menu, shortcuts.OPEN_SETTINGS)

        view_menu = self.menuBar().addMenu("&View")
        show_thumbnails_action = QAction("Show Thumbnails", self)
        show_thumbnails_action.setCheckable(True)
        show_thumbnails_action.setChecked(self._thumbnail_delegate.show_thumbnails)
        show_thumbnails_action.toggled.connect(self._on_toggle_thumbnails)
        view_menu.addAction(show_thumbnails_action)
        self._register_action_shortcut(
            show_thumbnails_action, view_menu, shortcuts.TOGGLE_THUMBNAILS
        )

        # Focus Mode's key goes into the action's *text*, after a literal
        # tab, rather than through `setShortcut()`: a QMenu right-aligns
        # that as a shortcut hint with no QShortcut actually created --
        # exactly what we want here, since a real one would collide with
        # the viewer's own play/pause button shortcut (both default to
        # Space) and go ambiguous, firing neither, whenever a video
        # happens to be showing. Focus Mode is dispatched through
        # KeyboardController instead -- see keyboard.py's module docstring
        # for why that sidesteps the collision. The text itself is filled
        # in by `_apply_bindings()`, not here.
        self._focus_mode_action = QAction(self)
        self._focus_mode_action.setCheckable(True)
        self._focus_mode_action.toggled.connect(self._apply_focus_mode)
        view_menu.addAction(self._focus_mode_action)
        self._hover_hints.register_action(
            self._focus_mode_action,
            view_menu,
            shortcuts.FOCUS_MODE,
            "Hide every panel except the media viewer",
        )

        # No QShortcut here either, for a different reason than Focus
        # Mode's: this one isn't a key combination at all. It's toggled by
        # tapping a modifier alone (pressed and released with no other key
        # in between) -- see MainWindow.eventFilter -- which has no
        # QKeySequence representation to attach to a QAction in the first
        # place.
        self._tag_shortcut_mode_action = QAction(self)
        self._tag_shortcut_mode_action.setCheckable(True)
        self._tag_shortcut_mode_action.toggled.connect(self._apply_tag_shortcut_mode)
        view_menu.addAction(self._tag_shortcut_mode_action)
        self._hover_hints.register_action(
            self._tag_shortcut_mode_action,
            view_menu,
            shortcuts.SWAP_TAG_NUMBERING,
            "Tap it alone to switch which tags the Edit list numbers",
        )

    def _register_action_shortcut(self, action: QAction, menu: QMenu, shortcut_id: str) -> None:
        """Give `action` a real QShortcut driven by `shortcut_id`, plus the
        hover-explainer hint that goes with it. The key itself is filled in
        by `_apply_bindings()`; the hint text is the shortcut's own
        description, so Settings and the status bar can't disagree about
        what a command does."""
        self._shortcut_actions[shortcut_id] = action
        self._hover_hints.register_action(
            action, menu, shortcut_id, shortcuts.definition(shortcut_id).description
        )

    # -- Shortcut bindings ----------------------------------------------------

    @property
    def bindings(self) -> ShortcutBindings:
        return self._bindings

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self._bindings, self, tag_ranking_settings=self._tag_ranking_settings
        )
        dialog.bindings_changed.connect(self._apply_bindings)
        dialog.tag_ranking_changed.connect(self._refresh_all)
        dialog.exec()

    def _apply_bindings(self) -> None:
        """Push the current bindings onto every part of the UI that needs a
        real key rather than a shortcut id.

        Called once at construction and again whenever Settings reports a
        change, so a rebind takes effect immediately -- no restart, and no
        stale key left behind in a menu entry or a hover hint."""
        for shortcut_id, action in self._shortcut_actions.items():
            binding = self._bindings.binding(shortcut_id)
            action.setShortcut(
                QKeySequence(binding, QKeySequence.SequenceFormat.PortableText)
                if binding
                else QKeySequence()
            )
        self._focus_mode_action.setText(self._menu_text("Focus Mode", shortcuts.FOCUS_MODE))
        self._tag_shortcut_mode_action.setText(
            self._menu_text("Number Selected Tags Instead", shortcuts.SWAP_TAG_NUMBERING)
        )
        self.viewer.set_play_pause_shortcut(self._bindings.binding(shortcuts.VIEWER_PLAY_PAUSE))
        self.item_tag_panel.set_shortcut_labels(self._quick_select_labels())
        # Whatever half-finished tap gesture was in flight was started
        # under the old bindings -- drop it rather than let it complete
        # against the new ones.
        self._tap_candidate_key = None

    def _menu_text(self, label: str, shortcut_id: str) -> str:
        """`label`, plus the shortcut's key right-aligned after a literal
        tab (QMenu's own convention for a hint with no QShortcut behind
        it). Just the label when the shortcut is unbound."""
        binding = self._bindings.binding(shortcut_id)
        return f"{label}\t{binding}" if binding else label

    def _quick_select_labels(self) -> dict[int, str]:
        """The one short label each quick-select slot paints inside its tag
        row's checkbox: the last key of its binding, so a rebind to
        "Ctrl+Q" still shows something meaningful ("Q") in a box far too
        small for the whole combination. Slots whose shortcut has been
        cleared are absent, and paint nothing."""
        labels: dict[int, str] = {}
        for slot in range(shortcuts.QUICK_SELECT_SLOT_COUNT):
            caps = keycaps(self._bindings.binding(shortcuts.quick_select_id(slot)))
            if caps:
                labels[slot] = caps[-1]
        return labels

    # -- Session lifecycle --------------------------------------------------

    def _prompt_open_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Open Collection Folder")
        if directory:
            self.open_collection(Path(directory))

    def _prompt_open_file(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self, "Open .prismic File", filter="Prismic Collection (*.prismic)"
        )
        if file_path:
            self.open_collection(Path(file_path))

    def open_collection(self, path: Path, *, is_startup: bool = False) -> None:
        self._focus_mode_action.setChecked(False)
        if self.session is not None:
            self.session.close()
            self.session = None
        if self._instance_bridge is not None:
            self._instance_bridge.release()
            self._instance_bridge = None
        self.thumbnail_provider.reset()

        try:
            session = PrismicSession.open(path, on_progress=self._scan_progress_bar.report_progress)
        except CollectionLockedError as exc:
            # The file lock is authoritative; this is just a best-effort
            # nicety on top of it. If another running instance is
            # reachable, ask it to raise itself instead of showing a plain
            # error -- and if this attempt was the CLI startup launch (the
            # OS double-click case), there's nothing else for this second
            # process to do, so it quits rather than leaving an empty
            # window behind.
            if request_focus(exc.path):
                if is_startup:
                    self.close()
                    return
                self._transient_bar.show_message(
                    "That collection is already open — brought its window to the front.",
                    5000,
                )
            else:
                MessageDialog.critical(self, "Could not open collection", str(exc))
            self._central_stack.setCurrentWidget(self._placeholder)
            return
        except PersistenceError as exc:
            MessageDialog.critical(self, "Could not open collection", str(exc))
            self._central_stack.setCurrentWidget(self._placeholder)
            return

        self.session = session
        self._view_history.clear()
        self._view_history_index = -1
        self._instance_bridge = InstanceBridge(self)
        self._instance_bridge.raise_requested.connect(self._on_raise_requested)
        self._instance_bridge.take_ownership(session.collection.database_path)
        self.setWindowTitle(f"Prismic — {session.collection.root.name}")
        self._central_stack.setCurrentWidget(self._splitter)
        self._watch_reconciliation(
            session.initial_reconciliation, is_first_scan=session.is_first_scan
        )
        self._refresh_all()
        # Two persistent QLineEdits (the tag search boxes) now live in the
        # main window's own widget tree rather than only inside transient
        # dialogs, so Qt's default initial-focus assignment on show() can
        # land on one of them instead of nothing in particular. The global
        # keyboard shortcuts deliberately stand down for *any* focused
        # QLineEdit (see eventFilter/_focus_is_text_editing) -- correct
        # while the user is actually typing a tag name, but it would
        # silently kill every shortcut from the moment a collection opens
        # if a search box just happened to inherit focus by default. Giving
        # the result list focus explicitly is what "immediately keyboard-
        # driven" actually requires here.
        self.result_list.setFocus()

    def _on_raise_requested(self) -> None:
        self.setWindowState(
            (self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
        )
        self.show()
        self.raise_()
        self.activateWindow()
        # Belt and braces: OS-level focus-stealing prevention (the same
        # mechanism documented in project guidance.md for this app's own
        # window at launch) can silently deny activateWindow() when this
        # process isn't already the foreground one -- observed live, not
        # just theorized. QApplication.alert() is the OS-sanctioned "ask
        # for attention" request (taskbar flash on Windows, dock bounce on
        # macOS) that works even when activation itself is denied.
        QApplication.alert(self)

    def _rescan(self) -> None:
        if self.session is None:
            return
        future = self.session.rescan(on_progress=self._scan_progress_bar.report_progress)
        self._watch_reconciliation(future, is_first_scan=self.session.is_first_scan)

    def _watch_reconciliation(
        self, future: Future[ReconciliationResult], *, is_first_scan: bool
    ) -> None:
        self._scan_progress_bar.reset_progress(is_first_scan=is_first_scan)
        self._scan_progress_bar.show()
        watcher = FutureWatcher(future, self)
        watcher.finished.connect(self._on_reconciliation_finished)
        self._future_watchers.append(watcher)

    def _on_reconciliation_finished(self, _result: object) -> None:
        self._scan_progress_bar.hide()
        if self.session is None:
            return
        self.session.refresh_state()
        self._refresh_all()

    def closeEvent(self, event: QCloseEvent) -> None:
        QSettings().setValue("window/geometry", self.saveGeometry())
        QSettings().setValue("window/columnSplitterSizes", self._splitter.sizes())
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if self._instance_bridge is not None:
            self._instance_bridge.release()
            self._instance_bridge = None
        if self.session is not None:
            self.session.close()
            self.session = None
        super().closeEvent(event)

    # -- Refreshing the UI from session state --------------------------------

    def _ordered_tags(self) -> list[Tag]:
        assert self.session is not None
        return self.session.tag_recency.order(self.session.tags.list_all())

    def _selection_or_current(self) -> frozenset[int]:
        """`state.selected_items`, falling back to `{state.current_item}`
        when it's empty *or* stale relative to `current_item`.

        `ApplicationState.recompute()` keeps the two in sync (`current_item`
        is always a member of `selected_items`) for any change that goes
        through a command, but code that pokes `state.current_item`
        directly without a `recompute()` in between -- mainly tests
        exercising a single-item scenario the old way -- would otherwise
        see every selection-aware code path below either treat that as
        "nothing selected" (empty `selected_items`) or, worse, keep
        reading a *stale* `selected_items` left over from before
        `current_item` changed, silently acting on the wrong file. This is
        what keeps that legacy direct-assignment pattern working without
        forcing every caller to also set `selected_items` in lockstep.
        """
        assert self.session is not None
        selected = self.session.state.selected_items
        current = self.session.state.current_item
        if selected and (current is None or current in selected):
            return selected
        return frozenset({current}) if current is not None else frozenset()

    def _refresh_all(self) -> None:
        if self.session is None:
            return
        tags = self._ordered_tags()
        self.filter_panel.set_tags(tags, frozenset(self.session.state.selected_tag_ids))

        media_list = eligible_media(
            self.session.media, self.session.mappings, self.session.state.selected_tag_ids
        )
        if self._shuffle_enabled:
            media_list = self._reordered_by_shuffle(media_list)
        self._display_order = [media.id for media in media_list]
        self.result_model.set_media(media_list)

        self._sync_result_selection()
        self._show_current_media()
        self._refresh_item_tag_panel(tags)
        self.panel_toolbar.undo_button.setEnabled(self.session.history.can_undo())
        self.panel_toolbar.redo_button.setEnabled(self.session.history.can_redo())

    def _reordered_by_shuffle(self, media_list: list[Media]) -> list[Media]:
        """`media_list` (in the query layer's own deterministic path
        order) rearranged per the persistent shuffle order.

        The arrangement itself survives across refreshes rather than
        being re-randomized every time this runs: an item already placed
        keeps its slot, one newly eligible is spliced in at a random
        position, and one no longer eligible just drops out. Only
        actually toggling shuffle on (`_apply_shuffle_mode`) produces a
        brand-new random order -- reshuffling on every refresh would make
        the list visibly jump around on every tag edit, which isn't what
        "shuffle" means in any player that icon is borrowed from."""
        by_id = {media.id: media for media in media_list}
        still_eligible = set(by_id)
        self._shuffled_order = [i for i in self._shuffled_order if i in still_eligible]
        placed = set(self._shuffled_order)
        for media in media_list:
            if media.id not in placed:
                self._shuffled_order.insert(random.randint(0, len(self._shuffled_order)), media.id)
        return [by_id[i] for i in self._shuffled_order]

    def _refresh_item_tag_panel(self, tags: list[Tag]) -> None:
        assert self.session is not None
        selected = self._selection_or_current()
        if not selected:
            self.item_tag_panel.set_tags(self._promote_tags(tags, frozenset()), frozenset())
            self._item_tag_order = []
            self._item_tag_order_item_id = None
            return
        if len(selected) == 1:
            current = next(iter(selected))
            mapped_ids = frozenset(t.id for t in self.session.mappings.tags_for_media(current))
            promoted = self._promote_tags(tags, mapped_ids)
            self.item_tag_panel.set_tags(
                self._stable_item_tags(promoted, mapped_ids, current), mapped_ids
            )
            return
        # Multi-select: "checked" means every selected file has the tag
        # (the intersection) -- anything less than all of them shows
        # unchecked, same as if none had it, per the product's own
        # definition of what the edit list should show for a bulk
        # selection. The stable manually-maintained order only makes
        # sense keyed to one file, so it's reset here and rebuilt fresh
        # once selection collapses back to a single item.
        self._item_tag_order = []
        self._item_tag_order_item_id = None
        common_ids = self._common_tag_ids(selected)
        self.item_tag_panel.set_tags(self._promote_tags(tags, common_ids), common_ids)

    def _promote_tags(self, tags: list[Tag], checked_ids: frozenset[int]) -> list[Tag]:
        """`tags` with "mega popular" and correlated-with-a-checked-tag
        candidates promoted to the top of its unchecked portion -- the
        item tag panel's own ranking, on top of (never touching) the
        recency/popularity order `tags` already comes in. Deliberately
        scoped to the item tag panel only, not the browse filter panel --
        the filter panel is what you use to explore what's already
        tagged, while this panel is where "what should I check next on
        this file" actually matters.
        """
        assert self.session is not None
        settings = self._tag_ranking_settings.load()
        self.session.tag_correlations.ensure_fresh()
        return promote_ranked_tags(
            tags,
            checked_ids,
            mega_popular_ids=self.session.tags.mega_popular_tag_ids(
                settings.mega_popular_threshold, self.session.media.count()
            ),
            correlations=self.session.tag_correlations.best_correlations_from(checked_ids),
            correlation_threshold=settings.correlation_threshold,
        )

    def _common_tag_ids(self, media_ids: frozenset[int]) -> frozenset[int]:
        assert self.session is not None
        tag_id_sets = [
            {t.id for t in self.session.mappings.tags_for_media(media_id)} for media_id in media_ids
        ]
        return frozenset(set.intersection(*tag_id_sets)) if tag_id_sets else frozenset()

    def _stable_item_tags(
        self, tags: list[Tag], mapped_ids: frozenset[int], current_item: int
    ) -> list[Tag]:
        """Reorders `tags` so the checked (mapped-to-`current_item`) subset
        follows a stable, manually-maintained order instead of the
        popularity/recency algorithm: checking a tag appends it to the
        bottom of that group, unchecking one just drops it out -- neither
        perturbs where the rest sit. That stable order is only rebuilt from
        the algorithmic order when `current_item` differs from the last
        call, i.e. the panel is loading a different file."""
        if current_item != self._item_tag_order_item_id:
            self._item_tag_order = [t.id for t in tags if t.id in mapped_ids]
            self._item_tag_order_item_id = current_item
        else:
            self._item_tag_order = [tid for tid in self._item_tag_order if tid in mapped_ids]
            already_ordered = set(self._item_tag_order)
            self._item_tag_order += [
                t.id for t in tags if t.id in mapped_ids and t.id not in already_ordered
            ]

        by_id = {t.id: t for t in tags}
        stable_checked = [by_id[tid] for tid in self._item_tag_order if tid in by_id]
        rest = [t for t in tags if t.id not in mapped_ids]
        return stable_checked + rest

    def _sync_result_selection(self) -> None:
        """State -> view: reflect `session.state`'s selection onto the
        real Qt selection model. The reverse direction --
        `_on_result_selection_changed`, view -> state -- is what an
        interactive click drives; this one runs after any non-interactive
        state change (`_refresh_all()`, `_navigate()`)."""
        assert self.session is not None
        selected = self._selection_or_current()
        current = self.session.state.current_item
        if not selected:
            self.result_list.clearSelection()
            return
        selection_model = self.result_list.selectionModel()
        item_selection = QItemSelection()
        for media_id in selected:
            row = self.result_model.row_for_media_id(media_id)
            if row is not None:
                index = self.result_model.index(row, 0)
                item_selection.select(index, index)
        selection_model.select(item_selection, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if current is not None:
            row = self.result_model.row_for_media_id(current)
            if row is not None:
                selection_model.setCurrentIndex(
                    self.result_model.index(row, 0), QItemSelectionModel.SelectionFlag.NoUpdate
                )

    def _show_current_media(self) -> None:
        assert self.session is not None
        selected = self._selection_or_current()
        if len(selected) > 1:
            self._media_stack.setCurrentWidget(self.selection_grid)
            items = []
            for media_id in self._display_order:
                if media_id not in selected:
                    continue
                path = self._resolve_media_path(media_id)
                if path is not None:
                    items.append((media_id, path))
            self.selection_grid.set_items(items)
            return
        self._media_stack.setCurrentWidget(self.viewer)
        current = self.session.state.current_item
        if current is None:
            self.viewer.clear()
            return
        media = self.session.media.get(current)
        if media is None:
            self.viewer.clear()
            return
        self._record_view(current)
        self.viewer.show_media(self.session.collection.root / media.relative_path)
        self._preload_neighbors(current)

    def _record_view(self, media_id: int) -> None:
        """Append `media_id` to the view history unless it's what the viewer
        is already on (a refresh re-showing the same file, or a history
        step landing on its own entry). Viewing something new after
        stepping back discards the forward entries, as in a browser."""
        history = self._view_history
        if 0 <= self._view_history_index < len(history) and (
            history[self._view_history_index] == media_id
        ):
            return
        del history[self._view_history_index + 1 :]
        history.append(media_id)
        if len(history) > _VIEW_HISTORY_LIMIT:
            del history[0]
        self._view_history_index = len(history) - 1

    def _step_history(self, delta: int) -> None:
        """Move through the view history, skipping entries whose file no
        longer exists. The target is shown even if the active filter no
        longer includes it -- that's the point of history -- in which case
        it's current without being in the results list, until the next
        recompute (any tag or filter change) repairs it the usual way."""
        if self.session is None:
            return
        index = self._view_history_index + delta
        while 0 <= index < len(self._view_history):
            media_id = self._view_history[index]
            if self.session.media.get(media_id) is not None:
                break
            index += delta
        else:
            return
        self._view_history_index = index
        self.session.state.current_item = media_id
        self.session.state.selected_items = frozenset({media_id})
        if media_id in self._display_order:
            self._sync_result_selection()
        else:
            # Not in the list, so there's nothing to highlight: clear the
            # view's selection with its signals off, since the change would
            # otherwise round-trip into `_on_result_selection_changed` and
            # reset the state just set.
            selection_model = self.result_list.selectionModel()
            blocked = selection_model.blockSignals(True)
            try:
                self.result_list.clearSelection()
            finally:
                selection_model.blockSignals(blocked)
            self.result_list.viewport().update()
        self._show_current_media()
        self._refresh_item_tag_panel(self._ordered_tags())

    def _preload_neighbors(self, current: int) -> None:
        """Warm the decode cache for the items around `current`, so
        arrow-key paging is usually a cache hit by the time the user
        actually lands on the next item.

        Biased two items ahead in `self._nav_direction` (the last arrow key
        pressed) and one behind: someone paging through a set of photos
        almost always keeps going the same way, including holding the key
        down or pressing it faster than one decode takes -- two-ahead is
        what keeps up with that, not just the single immediate neighbor.

        Steps through `self._display_order`, not the domain layer's own
        `session.state.result_set` -- the two agree exactly unless
        shuffle is on, in which case this is the one that reflects it.
        """
        assert self.session is not None
        result_set = self._display_order
        if current not in result_set:
            return
        index = result_set.index(current)
        root = self.session.collection.root
        ahead = self._nav_direction
        for offset in (ahead, 2 * ahead, -ahead):
            neighbor_index = index + offset
            if 0 <= neighbor_index < len(result_set):
                media = self.session.media.get(result_set[neighbor_index])
                if media is not None:
                    self.viewer.preload(root / media.relative_path)

    # -- User interaction -----------------------------------------------------

    def _on_result_selection_changed(self, *_args: object) -> None:
        """View -> state, for an interactive selection change (a click of
        any kind -- plain, shift, or ctrl -- handled by `ResultListView`
        itself; this just reads back whatever it ended up with). Ignores
        its arguments and re-derives the full selected set plus the
        current/anchor item fresh from the view every time, rather than
        trying to reason about which of `currentChanged`/`selectionChanged`
        fired or what exactly changed -- see the two signals' shared
        connection in `_build_ui` for why both land here."""
        if self.session is None:
            return
        selection_model = self.result_list.selectionModel()
        selected_indexes = selection_model.selectedIndexes()
        selected_ids = frozenset(
            media_id
            for index in selected_indexes
            if isinstance(media_id := self.result_model.data(index, MediaIdRole), int)
        )
        current_index = selection_model.currentIndex()
        current_id = (
            self.result_model.data(current_index, MediaIdRole) if current_index.isValid() else None
        )
        if not isinstance(current_id, int) or current_id not in selected_ids:
            # Qt's own current index (the keyboard-focus rectangle) doesn't
            # always land on a still-selected row -- ctrl-clicking to
            # *deselect* the current row still moves current there, per
            # Qt's own default handling, even though it just left the
            # selected set. Falling back to the lowest-row selected item
            # keeps `current_item` meaningful for single-item display (see
            # `_show_current_media`) and keeps the invariant `current_item`
            # is always a member of `selected_items` true here too, the
            # same invariant `ApplicationState.recompute()` enforces for
            # every non-interactive change.
            current_id = None
            if selected_indexes:
                lowest = min(selected_indexes, key=lambda index: index.row())
                lowest_id = self.result_model.data(lowest, MediaIdRole)
                current_id = lowest_id if isinstance(lowest_id, int) else None
        if (
            selected_ids == self.session.state.selected_items
            and current_id == self.session.state.current_item
        ):
            return
        self.session.state.selected_items = selected_ids
        self.session.state.current_item = current_id
        self._show_current_media()
        self._refresh_item_tag_panel(self._ordered_tags())

    def _navigate(self, delta: int) -> None:
        """Step `delta` positions through `self._display_order` -- the
        order actually on screen, which is `session.state.result_set`
        itself unless shuffle has rearranged it (see `_refresh_all`).

        Collapses a multi-selection back down to the single item landed
        on -- arrow-key paging is a single-item gesture, the same
        convention most file browsers use, and the alternative (leaving
        a stale multi-selection highlighted while paging one item at a
        time through the viewer) would just be confusing."""
        if self.session is None:
            return
        result_set = self._display_order
        if not result_set:
            return
        self._nav_direction = 1 if delta >= 0 else -1
        current = self.session.state.current_item
        if current is None or current not in result_set:
            new_index = 0
        else:
            index = result_set.index(current)
            new_index = max(0, min(len(result_set) - 1, index + delta))
        new_item = result_set[new_index]
        self.session.state.current_item = new_item
        self.session.state.selected_items = frozenset({new_item})
        self._sync_result_selection()
        self._show_current_media()
        self._refresh_item_tag_panel(self._ordered_tags())

    def _undo(self) -> None:
        if self.session is None:
            return
        self.session.undo()
        self._refresh_all()

    def _redo(self) -> None:
        if self.session is None:
            return
        self.session.redo()
        self._refresh_all()

    def _on_filter_toggle(self, tag_id: int) -> None:
        if self.session is None:
            return
        self.session.tag_recency.record_click(tag_id)
        if tag_id in self.session.state.selected_tag_ids:
            self.session.execute(FilterDeselectCommand(tag_id=tag_id))
        else:
            self.session.execute(FilterSelectCommand(tag_id=tag_id))
        self._refresh_all()
        self.filter_panel.clear_search_keep_focus()

    def _on_tag_create(self, name: str) -> None:
        if self.session is None:
            return
        try:
            self.session.execute(TagCreateCommand(name=name))
        except Exception as exc:  # noqa: BLE001 - shown to the user, not swallowed
            MessageDialog.warning(self, "Could not create tag", str(exc))
        self._refresh_all()

    def _on_tag_rename(self, tag_id: int, new_name: str) -> None:
        if self.session is None:
            return
        try:
            self.session.execute(TagRenameCommand(tag_id=tag_id, new_name=new_name))
        except Exception as exc:  # noqa: BLE001
            MessageDialog.warning(self, "Could not rename tag", str(exc))
        self._refresh_all()

    def _on_tag_delete(self, tag_id: int) -> None:
        if self.session is None:
            return
        self.session.execute(TagDeleteCommand(tag_id=tag_id))
        self._refresh_all()

    def _on_item_tag_toggle(self, tag_id: int) -> None:
        if self.session is None:
            return
        selected = self._selection_or_current()
        if not selected:
            return
        self.session.tag_recency.record_click(tag_id)
        if len(selected) == 1:
            current = next(iter(selected))
            mapped_ids = {t.id for t in self.session.mappings.tags_for_media(current)}
            if tag_id in mapped_ids:
                self.session.execute(MappingRemoveCommand(media_id=current, tag_id=tag_id))
            else:
                self.session.execute(MappingAddCommand(media_id=current, tag_id=tag_id))
        else:
            # The panel only ever shows this tag checked (see
            # `_refresh_item_tag_panel`) when *every* selected file
            # already has it -- so a toggle from checked always means
            # "remove from all," and from unchecked always means "add to
            # whichever ones don't have it yet," in one undo step.
            already_common = tag_id in self._common_tag_ids(selected)
            self.session.execute(
                MappingSetForManyCommand(
                    media_ids=selected, tag_id=tag_id, adding=not already_common
                )
            )
        self._refresh_all()
        self.item_tag_panel.clear_search_keep_focus()

    def _on_item_tag_hover(self, row: int | None) -> None:
        if row is None:
            self._hover_bar.clear()
            return
        model = self.item_tag_panel.model
        index = model.index(row, 0)
        active_selected = self._tag_shortcut_mode_action.isChecked()
        role = CheckedSlotRole if active_selected else UncheckedSlotRole
        slot = model.data(index, role)
        binding = (
            self._bindings.binding(shortcuts.quick_select_id(slot)) if isinstance(slot, int) else ""
        )
        if not binding:
            swap_keys = keycaps(self._bindings.binding(shortcuts.SWAP_TAG_NUMBERING))
            row_selected = bool(model.data(index, CheckedRole))
            if row_selected == active_selected or not swap_keys:
                # Either this row's own group already has the numbering
                # (it's just past the numbered slots, see
                # `_slot_for_position`), in which case swapping would only
                # take the numbering away from its whole group and give it
                # to the other one -- no move that actually helps this row
                # -- or the swap gesture is unbound, so there's no move to
                # suggest at all.
                self._hover_bar.clear()
                return
            group = "selected" if row_selected else "unselected"
            self._hover_bar.show_hint(swap_keys, f"Move quick-select shortcuts to {group} tags")
            return
        tag = model.tag_at(row)
        self._hover_bar.show_hint(keycaps(binding), f'Toggle "{tag.name}" on the current item')

    def _on_item_create_and_check(self, name: str) -> None:
        tag = self._create_tag_and_find(name)
        if tag is not None:
            self._on_item_tag_toggle(tag.id)

    def _on_filter_create_and_check(self, name: str) -> None:
        tag = self._create_tag_and_find(name)
        if tag is not None:
            self._on_filter_toggle(tag.id)

    def _create_tag_and_find(self, name: str) -> Tag | None:
        """Creates a tag and returns it, for the search box's Enter flow
        (`TagPanel._commit_search` always emits `create_and_check_requested`,
        never falls back to toggling a fuzzy-filtered match -- see its
        docstring). A tag already existing under this exact name isn't a
        duplicate-name *mistake* here the way `_on_tag_create` (used
        elsewhere, e.g. by tests seeding a tag directly) treats it as --
        with no "select from the list instead" alternative on offer, typing
        an existing tag's exact name and hitting Enter should just apply it,
        silently, not surface an error dialog for doing the obvious thing.
        `TagCreateCommand` doesn't hand back the row it inserted (nor does
        skipping it on a duplicate hand back the existing row), so this
        re-reads the tag list either way -- names are unique, so the match
        is unambiguous."""
        if self.session is None:
            return None
        try:
            self.session.execute(TagCreateCommand(name=name))
        except DuplicateTagNameError:
            pass
        except Exception as exc:  # noqa: BLE001 - shown to the user, not swallowed
            MessageDialog.warning(self, "Could not create tag", str(exc))
            return None
        else:
            self._refresh_all()
        for tag in self.session.tags.list_all():
            if tag.name == name:
                return tag
        return None

    def _on_toggle_thumbnails(self, checked: bool) -> None:
        self._thumbnail_delegate.show_thumbnails = checked
        # Row heights changed, which QListView doesn't pick up from a
        # repaint alone -- reset() forces it to re-query sizeHint for every
        # row. That also clears the view's own selection highlight, so the
        # current item's is restored right after.
        self.result_list.reset()
        self._sync_result_selection()

    def _toggle_focus_mode(self) -> None:
        self._focus_mode_action.setChecked(not self._focus_mode_action.isChecked())

    def _apply_focus_mode(self, checked: bool) -> None:
        """Hide (or restore) every panel except the media viewer itself.

        The viewer widget is left alone, apart from its video controls
        (see `_update_viewer_controls`). This otherwise only hides the
        browsing/tagging chrome around it: the tag panels
        and their shuffle/full-screen toolbar (`_left_column` wraps both,
        so hiding it gets the toolbar for free), the result list, and the
        menu/status bars.
        """
        visible = not checked
        self._left_column.setVisible(visible)
        self.result_list.setVisible(visible)
        self.menuBar().setVisible(visible)
        self.statusBar().setVisible(visible)
        self._update_viewer_controls()

    def _update_viewer_controls(self) -> None:
        """Video controls are chrome too: hidden in focus mode and full screen."""
        self.viewer.set_controls_suppressed(
            self._focus_mode_action.isChecked() or self.panel_toolbar.fullscreen_button.isChecked()
        )

    def _apply_shuffle_mode(self, checked: bool) -> None:
        """Toggle the shuffle button in `panel_toolbar`.

        Turning it on is the one moment a fresh random order gets
        generated -- from `session.state.result_set` (order doesn't
        matter, it's about to be shuffled), not from whatever
        `_shuffled_order` was left over from last time. `_refresh_all`
        is what actually applies it from here on, incrementally, per
        `_reordered_by_shuffle`."""
        self._shuffle_enabled = checked
        if checked and self.session is not None:
            self._shuffled_order = list(self.session.state.result_set)
            random.shuffle(self._shuffled_order)
        self._refresh_all()

    def _apply_true_fullscreen(self, checked: bool) -> None:
        """Real, OS-level full screen -- no title bar, no taskbar --
        independent of Focus Mode, which only hides this window's own
        side panels while staying a normal window. The two compose: both
        on at once is as distraction-free as this app gets.

        Getting back out again is handled in `eventFilter`, not here:
        this method only reacts to the button's own checked state,
        whichever set it.

        Restoring specifically whatever state preceded full screen --
        maximized included -- rather than always `showNormal()`: Qt's
        own `showFullScreen()`/`showNormal()` pair remembers the
        *geometry* to fall back to (so a plain windowed size/position
        survives correctly on its own), but not that the window had been
        maximized. Left to `showNormal()` alone, toggling full screen off
        would silently un-maximize a window that was maximized before
        it -- not what "restore ... to the size it was before" means
        when "before" was maximized.
        """
        self._update_viewer_controls()
        if checked:
            self._pre_fullscreen_state = self.windowState()
            self.showFullScreen()
            return
        was_maximized = bool(self._pre_fullscreen_state & Qt.WindowState.WindowMaximized)
        # Always through Normal first, even when heading straight back to
        # Maximized: asking to maximize a still-`WindowFullScreen` window
        # in one step is unreliable (observed silently ignored on
        # Windows) -- a clean two-step transition is not.
        self.showNormal()
        if was_maximized:
            self.showMaximized()

    def _on_toggle_tag_shortcut(self, slot: int) -> None:
        tag_id = self.item_tag_panel.model.tag_id_for_slot(
            slot, selected=self._tag_shortcut_mode_action.isChecked()
        )
        if tag_id is not None:
            self._on_item_tag_toggle(tag_id)

    def _toggle_tag_shortcut_mode(self) -> None:
        self._tag_shortcut_mode_action.setChecked(not self._tag_shortcut_mode_action.isChecked())

    def _apply_tag_shortcut_mode(self, selected: bool) -> None:
        self.item_tag_panel.set_shortcut_mode_selected(selected)
        self._transient_bar.show_message(
            "Numbering selected tags" if selected else "Numbering unselected tags", 2000
        )

    def _on_viewer_error(self, reason: str) -> None:
        self._transient_bar.show_message(f"Could not load media: {reason}", 5000)

    def _resolve_media_path(self, media_id: int) -> Path | None:
        if self.session is None:
            return None
        media = self.session.media.get(media_id)
        if media is None:
            return None
        return self.session.collection.root / media.relative_path

    def _on_thumbnail_ready(self, media_id: int) -> None:
        row = self.result_model.row_for_media_id(media_id)
        if row is not None:
            self.result_list.update(self.result_model.index(row, 0))

    # -- Keyboard -------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if QApplication.activeModalWidget() is not None:
            # A modal dialog owns input while it's up -- most of all the
            # Settings window, where the whole point of a keystroke is to
            # be captured as a new binding rather than to fire the command
            # it's currently bound to. (Qt already blocks the menu actions'
            # own QShortcuts under modality; this is the same rule for the
            # shortcuts dispatched by hand below it.)
            return super().eventFilter(watched, event)
        if self.panel_toolbar.fullscreen_button.isChecked() and event.type() in (
            QEvent.Type.KeyPress,
            QEvent.Type.MouseButtonPress,
        ):
            # Literally any key or click exits full screen -- not a
            # specific one (Escape, say) -- per the button's own tooltip.
            # Swallowed entirely rather than also let through to whatever
            # it would otherwise have done: "any key gets you out" reads
            # as its own dedicated gesture, not "exit, and also maybe
            # toggle thumbnails if it happened to be T."
            self.panel_toolbar.fullscreen_button.setChecked(False)
            event.accept()
            return True
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if not event.isAutoRepeat():
                self._keys_down.add(event.key())
                if len(self._keys_down) > 1 or event.key() not in MODIFIER_KEY_NAMES:
                    # Either something else is down too (so this modifier
                    # is being held *for* that key, not tapped), or this
                    # isn't a modifier at all.
                    self._tap_candidate_key = None
                elif self._tap_candidate_key is None:
                    self._tap_candidate_key = event.key()
            pressed = key_text(event)
            if pressed is not None and self._handle_dismiss(pressed):
                event.accept()
                return True
            if (
                pressed is not None
                and pressed == self._bindings.binding(shortcuts.FOCUS_TAG_SEARCH)
                and self._cycle_tag_search_focus()
            ):
                event.accept()
                return True
            if pressed is not None and self._focus_is_text_editing():
                if self._handle_quick_select_while_typing(pressed):
                    event.accept()
                    return True
            if self.session is not None and self.keyboard.handle_key_press(
                event, text_editing=self._focus_is_text_editing()
            ):
                event.accept()
                return True
            if (
                self.session is not None
                and not self._focus_is_text_editing()
                and self._start_typing_in_edit_panel(event)
            ):
                event.accept()
                return True
        elif event.type() == QEvent.Type.KeyRelease and isinstance(event, QKeyEvent):
            if not event.isAutoRepeat():
                self._keys_down.discard(event.key())
                if self._tap_candidate_key == event.key():
                    # Cleared before firing, so the same release arriving
                    # again further up the propagation chain can't fire it
                    # a second time.
                    self._tap_candidate_key = None
                    self._fire_tapped_modifier(MODIFIER_KEY_NAMES[event.key()])
            # Deliberately not consumed either way -- this is an
            # observation of the release, not a binding on it.
        elif event.type() == QEvent.Type.MouseButtonPress:
            # A modifier+click (of whatever kind, anywhere) is a held
            # modifier doing something else, same as a modifier+key combo
            # above -- its eventual release isn't a tap.
            self._tap_candidate_key = None
            self._dismiss_typing_focus_unless_clicking(watched)
        elif event.type() == QEvent.Type.WindowDeactivate:
            # Key releases that happen while another window has focus are
            # never delivered here, so a key held across an alt-tab would
            # otherwise stay in `_keys_down` forever and block every
            # future tap. Nothing is held, as far as this window knows.
            self._keys_down.clear()
            self._tap_candidate_key = None
        return super().eventFilter(watched, event)

    def _fire_tapped_modifier(self, modifier: str) -> None:
        """Run whatever is bound to `modifier` on its own, if anything.

        A bare modifier is a perfectly ordinary binding -- Settings
        captures one the same way it captures any other key, and the Edit
        list's numbering swap just happens to default to it. It can't be
        dispatched through the normal key path, though: a lone modifier
        has no key sequence (`key_text()` returns None for one), which is
        why the gesture is recognized from the press/release pair here
        instead."""
        shortcut_id = self._bindings.shortcut_for(modifier)
        if shortcut_id is not None:
            self._fire_shortcut(shortcut_id)

    def _fire_shortcut(self, shortcut_id: str) -> bool:
        """Run a shortcut's command by id, with no key event behind it.

        The commands live in three different places -- menu `QAction`s,
        `KeyboardController`'s callbacks, and the handful handled here --
        because each is dispatched differently during normal key
        handling. Anything that arrives as an id rather than a key needs
        one door into all of them, and this is it."""
        action = self._shortcut_actions.get(shortcut_id)
        if action is not None:
            action.trigger()
            return True
        if shortcut_id == shortcuts.DISMISS:
            return self._dismiss()
        for slot in range(shortcuts.QUICK_SELECT_SLOT_COUNT):
            if shortcut_id == shortcuts.quick_select_id(slot):
                self._on_toggle_tag_shortcut(slot)
                return True
        return self.keyboard.run(shortcut_id)

    def _handle_dismiss(self, pressed: str) -> bool:
        """The Dismiss shortcut: leave a tag search box, and/or leave focus
        mode. Returns whether it did either.

        Escape exits focus mode even when Dismiss has been rebound off it
        or cleared entirely. That's a deliberate safety hatch rather than a
        hidden binding: focus mode hides the menu bar, so a user who
        unbinds both Dismiss and Focus Mode would otherwise have no way
        back out short of quitting the app."""
        dismiss = self._bindings.binding(shortcuts.DISMISS)
        if bool(dismiss) and pressed == dismiss:
            return self._dismiss()
        if pressed == "Esc" and self._focus_mode_action.isChecked():
            self._focus_mode_action.setChecked(False)
            return True
        return False

    def _dismiss(self) -> bool:
        """The Dismiss command itself, with no key behind it -- also what
        `_fire_shortcut` runs when Dismiss is bound to a modifier tap."""
        handled = False
        if self._focus_is_text_editing():
            self._dismiss_typing_focus()
            handled = True
        if self._focus_mode_action.isChecked():
            # The reliable way out of focus mode -- Focus Mode's own key
            # can't be, since it's claimed by the viewer's play/pause
            # shortcut whenever a video is showing and the two share a
            # default (see keyboard.py's module docstring).
            self._focus_mode_action.setChecked(False)
            handled = True
        return handled

    def _handle_quick_select_while_typing(self, pressed: str) -> bool:
        """Quick-select tag shortcuts keep working while a text box has
        focus -- and holding the "type literally" modifier
        (`shortcuts.TYPE_LITERALLY_MODIFIER`, "Ctrl" by default, but its
        own rebindable shortcut like everything else) plus the same key
        types the character instead, so a key spent on quick-select is
        still typeable.

        Both halves live here rather than in `KeyboardController` because
        the second one needs the actual focused widget, not just a key
        string: letting that `QKeyEvent` fall through unhandled does not,
        in practice, type anything, since Windows hands Qt an empty
        `text()` for most Ctrl+digit combinations (confirmed
        empirically). Without inserting it directly, spending a digit on
        quick-select would silently make it untypable in these fields even
        with the modifier held."""
        slot = self._bindings.quick_select_slot(pressed)
        if slot is not None:
            self._on_toggle_tag_shortcut(slot)
            return True
        base = strip_modifier_prefix(pressed, self._bindings.literal_typing_modifier())
        if base is None or self._bindings.quick_select_slot(base) is None:
            return False
        character = literal_character(base)
        focused = QApplication.focusWidget()
        if character is not None and isinstance(focused, QLineEdit):
            focused.insert(character)
        return True

    def _start_typing_in_edit_panel(self, event: QKeyEvent) -> bool:
        """A plain a-z letter, pressed with no text box focused and no
        modifier bound to some other shortcut, jumps straight into the
        item-tag panel's search box and types the character there --
        the same "just start typing" convention a file browser's own
        type-ahead search uses, so a keystroke aimed at tagging doesn't
        need Tab or a click to land anywhere first.

        Only bare letters (Shift included, since that's how a capital
        letter is typed, not a shortcut combo) qualify, and only once
        every other binding -- Dismiss, the tag-search cycle key, a
        rebound global shortcut, quick-select -- has already had first
        refusal via the checks ahead of this one in `eventFilter`, so a
        user who rebinds a shortcut onto a bare letter still gets that
        shortcut, not this. The panel must actually be visible too: in
        Focus Mode it's hidden, and redirecting keystrokes into a search
        box the user can't see would be worse than doing nothing.

        The letter is derived from `event.key()` plus the Shift state,
        not from `event.text()` -- Qt's `Key_A`..`Key_Z` already line up
        with the ASCII uppercase letters, and `text()` is a layout/IME
        translation that isn't guaranteed to reflect Shift consistently
        for a synthetically generated event (observed live: a `QTest`-
        simulated Shift+V event came through with a lowercase `text()`).
        """
        if not self.item_tag_panel.isVisible():
            return False
        modifiers = event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier
        if modifiers != Qt.KeyboardModifier.NoModifier:
            return False
        key = event.key()
        if not (Qt.Key.Key_A <= key <= Qt.Key.Key_Z):
            return False
        letter = chr(key)
        if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            letter = letter.lower()
        self.item_tag_panel.focus_search()
        self.item_tag_panel.search_box.insert(letter)
        return True

    def _cycle_tag_search_focus(self) -> bool:
        """If focus is currently in one of the two tag search boxes, advance
        it around a 3-step loop: item-tag box -> filter box -> dismissed
        (back to the result list) -> item-tag box -> ... Report the key as
        handled for the first two steps; the third is a plain Tab-out, left
        to Qt's own focus handling instead of forced onto the result list,
        since the loop should end at "no longer typing," not at any one
        specific widget.

        Handled here, as a direct widget-identity check, rather than via
        `QWidget.setTabOrder`: Qt's tab-order chain is one single shared
        list for the whole window, and `setTabOrder(A, B)` only repositions
        a pair *within* it -- it can't carve out a closed loop excluding
        every other focusable widget, which is what "Tab between just these
        two boxes, then out" actually requires. Confirmed by trying it:
        `setTabOrder(A, B)` then `setTabOrder(B, A)` leaves A pointing at
        whatever followed B beforehand, not back at B."""
        focused = QApplication.focusWidget()
        if focused is self.item_tag_panel.search_box:
            self.filter_panel.search_box.setFocus()
            return True
        if focused is self.filter_panel.search_box:
            self._dismiss_typing_focus()
            return True
        return False

    def _dismiss_typing_focus(self) -> None:
        """Move focus off whatever text box currently has it and back to
        the result list -- the same "immediately keyboard-driven" default
        focus target `open_collection` sets on startup."""
        self.result_list.setFocus()

    def _dismiss_typing_focus_unless_clicking(self, clicked: QObject) -> None:
        """A click that lands on neither a text input nor a button leaves
        typing focus behind -- the blank space around a tag panel's
        title, a splitter handle, the menu bar, all count as "elsewhere."
        Clicking a tag row or the result list isn't specifically exempted
        either; it doesn't need to be, since both already take focus on
        click via their own strong focus policy, same as this would have
        landed them at anyway.

        Not consumed -- this only runs alongside whatever the click was
        actually for (opening a menu, moving focus to a clicked row, ...),
        never instead of it. `clicked` is `watched` from `eventFilter`:
        for a `MouseButtonPress`, that's exactly the widget Qt is about
        to deliver this press to, so an `isinstance` check on it is a
        direct answer to "what did this click land on," no hit-testing
        of our own required.
        """
        if not self._focus_is_text_editing():
            return
        if isinstance(clicked, QLineEdit | QAbstractButton):
            return
        self._dismiss_typing_focus()

    @staticmethod
    def _focus_is_text_editing() -> bool:
        return isinstance(QApplication.focusWidget(), QLineEdit)
