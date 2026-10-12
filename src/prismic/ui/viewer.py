"""The media viewer: an image view with zoom/pan, or a video player with
play/pause/seek controls, switching between the two based on the current
item's extension. Navigation between items happens without leaving the
viewer — `show_media()` just swaps what's displayed in place.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImageReader, QKeySequence, QMovie
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QWidget,
)

from prismic.application.worker_pool import WorkerPool
from prismic.media.formats import SUPPORTED_VIDEO_EXTENSIONS
from prismic.media.image import ImageLoadError, load_image
from prismic.media.loader import ImageLoader, ImageLoadResult
from prismic.media.video import VideoPlayer
from prismic.ui._layouts import vertical_stack
from prismic.ui.future_watcher import FutureWatcher
from prismic.ui.image_view import ImageView

_ANIMATED_EXTENSIONS = frozenset({".gif"})
_QWIDGETSIZE_MAX = 16777215


class MediaViewer(QWidget):
    load_error = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        worker_pool: Callable[[], WorkerPool | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mediaViewer")
        # Resolved lazily on each load rather than captured once, matching
        # `ThumbnailDelegate`'s pattern -- the pool a session owns can change
        # (or become None) across collection open/close, and there's no
        # session at all yet when MainWindow constructs this widget.
        self._worker_pool = worker_pool if worker_pool is not None else (lambda: None)
        self._image_loader = ImageLoader()
        self._current_request_id = 0
        self._watchers: list[FutureWatcher] = []

        self._image_view = ImageView()
        self._video_widget = QVideoWidget()
        self._video_player = VideoPlayer(self)
        self._video_player.qt_player.setVideoOutput(self._video_widget)
        # Looped here rather than in `VideoPlayer`: it's how the viewer
        # wants clips shown, not a property of playback itself.
        self._video_player.qt_player.setLoops(QMediaPlayer.Loops.Infinite)
        self._video_player.load_failed.connect(self.load_error)
        self._video_player.qt_player.positionChanged.connect(self._on_position_changed)
        self._video_player.qt_player.durationChanged.connect(self._on_duration_changed)
        self._video_player.qt_player.playbackStateChanged.connect(self._on_playback_state_changed)

        self._empty_label = QLabel("No collection open")
        self._empty_label.setObjectName("emptyStateLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._stack = QStackedWidget()
        self._stack.setObjectName("viewerStack")
        self._stack.addWidget(self._empty_label)
        self._stack.addWidget(self._image_view)
        self._stack.addWidget(self._video_widget)

        self._play_pause_button = QPushButton("Play")
        self._play_pause_button.setObjectName("playPauseButton")
        # Space by default, but user-configurable like every other
        # shortcut -- `MainWindow` pushes the current binding in via
        # `set_play_pause_shortcut()` once it has one.
        self._play_pause_button.setShortcut(QKeySequence(Qt.Key.Key_Space))
        self._play_pause_button.clicked.connect(self.toggle_playback)
        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 0)
        self._seek_slider.sliderMoved.connect(self._video_player.seek)

        self._controls = QWidget()
        self._controls.setObjectName("viewerControls")
        controls_layout = QHBoxLayout(self._controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addWidget(self._play_pause_button)
        controls_layout.addWidget(self._seek_slider)
        self._controls.setVisible(False)

        vertical_stack(self, (self._stack, self._controls))

        self._current_path: Path | None = None
        self._controls_suppressed = False
        # Play/pause is one global mode, not per-video: once any video is
        # played, every video that follows starts playing, until one is
        # paused. Off when the app opens.
        self._autoplay = False

    def set_controls_suppressed(self, suppressed: bool) -> None:
        """Hide the video controls (focus and full-screen modes)."""
        self._controls_suppressed = suppressed
        # Collapsed to nothing rather than hidden: a hidden widget's
        # shortcuts are disabled, and Space must keep playing/pausing.
        self._controls.setMaximumHeight(0 if suppressed else _QWIDGETSIZE_MAX)

    def set_play_pause_shortcut(self, binding: str) -> None:
        """Rebind the play/pause button's own key, in Qt's portable key-
        sequence format. An empty string leaves it with no shortcut at
        all, which is what an unbound shortcut means everywhere else."""
        self._play_pause_button.setShortcut(
            QKeySequence(binding, QKeySequence.SequenceFormat.PortableText)
            if binding
            else QKeySequence()
        )

    def show_media(self, path: Path) -> None:
        self._current_path = path
        if path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            self._show_video(path)
        else:
            self._show_image(path)

    def clear(self) -> None:
        self._current_path = None
        self._video_player.stop()
        self._image_view.clear()
        self._controls.setVisible(False)
        self._stack.setCurrentWidget(self._empty_label)

    def _show_image(self, path: Path) -> None:
        self._video_player.stop()
        self._controls.setVisible(False)
        if self._try_show_animation(path):
            return
        # Whatever was animating belongs to the previous file; the still
        # that replaces it arrives asynchronously below.
        self._image_view.stop_movie()
        pool = self._worker_pool()
        if pool is None:
            # No pool available (e.g. a standalone MediaViewer with no
            # session behind it) -- fall back to the old synchronous decode
            # rather than silently doing nothing.
            outcome = load_image(path)
            if isinstance(outcome, ImageLoadError):
                self.load_error.emit(outcome.reason)
                self._stack.setCurrentWidget(self._empty_label)
                return
            self._image_view.set_image(outcome)
            self._stack.setCurrentWidget(self._image_view)
            return

        self._current_request_id = self._image_loader.begin_request()
        future = pool.submit(self._image_loader.load, self._current_request_id, path)
        watcher = FutureWatcher(future, self)
        self._watchers.append(watcher)
        watcher.finished.connect(lambda result: self._on_image_loaded(watcher, result))

    def _try_show_animation(self, path: Path) -> bool:
        """Play `path` as an animation if it is one (a multi-frame GIF).

        Done on the GUI thread, bypassing the decode cache: `QMovie` decodes
        frame by frame as it plays, which is the point -- a cached
        single `QImage` can only ever be the first frame."""
        if path.suffix.lower() not in _ANIMATED_EXTENSIONS:
            return False
        reader = QImageReader(str(path))
        if not reader.supportsAnimation() or reader.imageCount() < 2:
            return False
        movie = QMovie(str(path))
        if not movie.isValid():
            return False
        # Invalidates any in-flight still decode, so it can't land on top.
        self._current_request_id = self._image_loader.begin_request()
        movie.jumpToFrame(0)
        self._image_view.set_movie(movie)
        self._stack.setCurrentWidget(self._image_view)
        return True

    def _on_image_loaded(self, watcher: FutureWatcher, result: ImageLoadResult | None) -> None:
        if watcher in self._watchers:
            self._watchers.remove(watcher)
        if result is None:
            # A newer navigation superseded this request before it finished
            # -- whatever's now current already has its own load in flight.
            return
        if result.error is not None:
            self.load_error.emit(result.error)
            self._stack.setCurrentWidget(self._empty_label)
            return
        assert result.image is not None
        self._image_view.set_image(result.image)
        self._stack.setCurrentWidget(self._image_view)

    def preload(self, path: Path) -> None:
        """Warm the decode cache for a likely-next item (e.g. the neighbor
        of whatever's currently shown), so paging onto it later is a cache
        hit instead of a fresh decode.
        """
        if path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            return
        pool = self._worker_pool()
        if pool is None:
            return
        pool.submit(self._image_loader.preload, self._current_request_id, path)

    def _show_video(self, path: Path) -> None:
        self._image_view.clear()
        self._controls.setVisible(True)
        self._video_player.load(path)
        if self._autoplay:
            self._video_player.play()
        self._stack.setCurrentWidget(self._video_widget)

    def toggle_playback(self) -> None:
        if self._video_player.playback_state == QMediaPlayer.PlaybackState.PlayingState:
            self._autoplay = False
            self._video_player.pause()
        else:
            self._autoplay = True
            self._video_player.play()

    def _on_position_changed(self, position: int) -> None:
        if not self._seek_slider.isSliderDown():
            self._seek_slider.setValue(position)

    def _on_duration_changed(self, duration: int) -> None:
        self._seek_slider.setRange(0, duration)

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_pause_button.setText("Pause" if is_playing else "Play")

    @property
    def autoplay(self) -> bool:
        return self._autoplay

    @property
    def play_pause_button(self) -> QPushButton:
        return self._play_pause_button

    @property
    def image_view(self) -> ImageView:
        return self._image_view

    @property
    def video_player(self) -> VideoPlayer:
        return self._video_player

    @property
    def current_path(self) -> Path | None:
        return self._current_path

    @property
    def is_showing_video(self) -> bool:
        return self._stack.currentWidget() is self._video_widget

    @property
    def is_showing_image(self) -> bool:
        return self._stack.currentWidget() is self._image_view
