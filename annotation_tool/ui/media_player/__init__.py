import datetime as _datetime
import os

from PyQt6 import uic
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from utils import format_utc_datetime, parse_utc_datetime, resource_path


class AnnotationSlider(QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.markers = []

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.markers or self.maximum() <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        opt = QStyleOptionSlider()
        self.initStyleOption(opt)

        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )

        available_width = groove.width()
        x_offset = groove.x()

        for marker in self.markers:
            start_ms = marker.get("start_ms", 0)
            ratio = start_ms / self.maximum()
            x_pos = x_offset + int(available_width * ratio)

            color = marker.get("color", QColor("red"))
            painter.setPen(QPen(color, 2))
            painter.drawLine(x_pos, groove.top() - 2, x_pos, groove.bottom() + 2)

        painter.setPen(QPen(QColor("#FF3333"), 1))
        painter.setBrush(QColor("#FF3333"))
        painter.drawRoundedRect(handle_rect, 4, 4)


class FramePreviewLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_pixmap = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def clear_frame(self):
        self._source_pixmap = None
        self.clear()

    def set_frame_pixmap(self, pixmap: QPixmap):
        self._source_pixmap = QPixmap(pixmap) if pixmap and not pixmap.isNull() else None
        self._refresh_scaled_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_scaled_pixmap()

    def _refresh_scaled_pixmap(self):
        if self._source_pixmap is None or self._source_pixmap.isNull():
            self.clear()
            return

        if self.width() <= 0 or self.height() <= 0:
            super().setPixmap(self._source_pixmap)
            return

        scaled = self._source_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        super().setPixmap(scaled)


class MediaViewerPane(QFrame):
    """One independently rendered media surface inside the synchronized grid."""

    focusRequested = pyqtSignal(str)
    muteToggleRequested = pyqtSignal(str)
    syncRequested = pyqtSignal(str)
    goToStartRequested = pyqtSignal(str)
    goToEndRequested = pyqtSignal(str)
    utcStartSetRequested = pyqtSignal(str, str)
    utcStartRemoveRequested = pyqtSignal(str)

    def __init__(self, source_key: str = "", parent=None):
        super().__init__(parent)
        self.source_key = str(source_key or "")
        self._sync_available = False
        self._sync_unavailable_reason = "Synchronization is unavailable."
        self._navigation_available = False
        self._sync_mode_active = False
        self._explicit_utc_present = False
        self._explicit_utc_text = ""
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("class", "media_viewer_pane")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(280, 180)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        header = QHBoxLayout()
        self.title_label = QLabel("Media")
        self.timing_label = QLabel("Relative")
        self.timing_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.btn_mute = QPushButton("", self)
        self.btn_mute.setFixedSize(24, 24)
        self._icon_volume = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self._icon_muted = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
        self.btn_mute.setIcon(self._icon_volume)
        self.btn_mute.setToolTip("Mute this feed")
        self.btn_mute.clicked.connect(lambda: self.muteToggleRequested.emit(self.source_key))
        header.addWidget(self.title_label, 1)
        header.addWidget(self.timing_label)
        header.addWidget(self.btn_mute)
        layout.addLayout(header)

        self.surface = QWidget(self)
        self.surface_layout = QVBoxLayout(self.surface)
        self.surface_layout.setContentsMargins(0, 0, 0, 0)
        self.video_widget = QVideoWidget(self.surface)
        self.video_widget.setProperty("class", "video_preview_widget")
        self.frame_widget = FramePreviewLabel(self.surface)
        self.frame_widget.setProperty("class", "video_preview_widget")
        self.status_label = QLabel("", self.surface)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        for widget in (self.video_widget, self.frame_widget, self.status_label):
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.surface_layout.addWidget(widget)
        self.frame_widget.hide()
        layout.addWidget(self.surface, 1)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(1.0)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)

    def configure(self, source: dict, *, focused: bool = False):
        path = str(source.get("path") or "")
        source_type = str(source.get("type") or "unknown")
        self.source_key = path
        self._explicit_utc_present = "UTC_time_start" in source
        self._explicit_utc_text = str(source.get("UTC_time_start") or "")
        self.title_label.setText(f"{source_type} · {os.path.basename(path) or path}")
        self.set_focused(focused)
        self.show_status("Loading…")

    def set_timing_status(self, text: str, tooltip: str = ""):
        self.timing_label.setText(str(text or "Relative"))
        self.timing_label.setToolTip(str(tooltip or ""))

    def set_focused(self, focused: bool):
        self.setProperty("focused", bool(focused))
        self.style().unpolish(self)
        self.style().polish(self)

    def set_syncing(self, syncing: bool):
        self.setProperty("syncing", bool(syncing))
        self.style().unpolish(self)
        self.style().polish(self)

    def set_sync_available(self, available: bool, reason: str = ""):
        self._sync_available = bool(available)
        self._sync_unavailable_reason = str(reason or "Synchronization is unavailable.")

    def set_navigation_available(self, available: bool):
        self._navigation_available = bool(available)

    def set_sync_mode_active(self, active: bool):
        self._sync_mode_active = bool(active)

    def set_feed_muted(self, muted: bool):
        self.btn_mute.setIcon(self._icon_muted if muted else self._icon_volume)
        self.btn_mute.setToolTip("Unmute this feed" if muted else "Mute this feed")

    def show_status(self, text: str):
        self.video_widget.hide()
        self.frame_widget.hide()
        self.status_label.setText(str(text or ""))
        self.status_label.show()

    def show_video_surface(self):
        self.status_label.hide()
        self.frame_widget.hide()
        self.video_widget.show()

    def show_frame_surface(self):
        self.status_label.hide()
        self.video_widget.hide()
        self.frame_widget.show()

    def clear_preview(self):
        self.frame_widget.clear_frame()
        self.show_video_surface()
        self.video_widget.update()

    def set_frame_image(self, image):
        if image is None or image.isNull():
            self.clear_preview()
            return
        self.frame_widget.set_frame_pixmap(QPixmap.fromImage(image))
        self.show_frame_surface()

    def mousePressEvent(self, event):
        self.focusRequested.emit(self.source_key)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        go_to_start_action = menu.addAction("Go to start")
        go_to_start_action.setEnabled(
            self._navigation_available and not self._sync_mode_active
        )
        go_to_end_action = menu.addAction("Go to end")
        go_to_end_action.setEnabled(
            self._navigation_available and not self._sync_mode_active
        )
        if not self._navigation_available:
            go_to_start_action.setToolTip("This input is not playable.")
            go_to_end_action.setToolTip("This input is not playable.")
        elif self._sync_mode_active:
            navigation_tooltip = "Finish synchronization before navigating the shared timeline."
            go_to_start_action.setToolTip(navigation_tooltip)
            go_to_end_action.setToolTip(navigation_tooltip)
        menu.addSeparator()
        action = menu.addAction("Synchronize this modality")
        action.setEnabled(self._sync_available)
        if not self._sync_available:
            action.setStatusTip(self._sync_unavailable_reason)
            action.setToolTip(self._sync_unavailable_reason)
        menu.addSeparator()
        set_utc_action = None
        correct_utc_action = None
        remove_utc_action = None
        if self._explicit_utc_present:
            correct_utc_action = menu.addAction("Correct UTC start…")
            remove_utc_action = menu.addAction("Remove UTC start")
            correct_utc_action.setEnabled(not self._sync_mode_active)
            remove_utc_action.setEnabled(not self._sync_mode_active)
        else:
            set_utc_action = menu.addAction("Set UTC start…")
            set_utc_action.setEnabled(bool(self.source_key) and not self._sync_mode_active)
        selected_action = menu.exec(event.globalPos())
        if selected_action is go_to_start_action:
            self.goToStartRequested.emit(self.source_key)
        elif selected_action is go_to_end_action:
            self.goToEndRequested.emit(self.source_key)
        elif selected_action is action:
            self.syncRequested.emit(self.source_key)
        elif (
            set_utc_action is not None and selected_action is set_utc_action
        ) or (
            correct_utc_action is not None and selected_action is correct_utc_action
        ):
            self._prompt_utc_start()
        elif remove_utc_action is not None and selected_action is remove_utc_action:
            self._confirm_remove_utc_start()

    def _prompt_utc_start(self):
        initial = format_utc_datetime(self._explicit_utc_text) or self._explicit_utc_text
        value, accepted = QInputDialog.getText(
            self,
            "UTC Start Time",
            "UTC time at modality position 00:00.000:",
            text=initial,
        )
        if not accepted:
            return
        normalized = format_utc_datetime(value)
        if normalized is None:
            QMessageBox.warning(
                self,
                "Invalid UTC Time",
                "Enter an ISO-compatible timestamp, optionally with Z or a timezone offset.",
            )
            return
        self.utcStartSetRequested.emit(self.source_key, normalized)

    def _confirm_remove_utc_start(self):
        answer = QMessageBox.question(
            self,
            "Remove UTC Start",
            "Remove the explicit UTC start time for this modality?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.utcStartRemoveRequested.emit(self.source_key)


class MediaCenterPanel(QWidget):
    """
    Unified center panel for all annotation modes.
    Backed by Qt Designer .ui and exposes direct playback/timeline API.
    """

    # Playback control signals
    seekRelativeRequested = pyqtSignal(int)
    stopRequested = pyqtSignal()
    playPauseRequested = pyqtSignal()
    muteToggleRequested = pyqtSignal()
    playbackRateRequested = pyqtSignal(float)
    paneFocusRequested = pyqtSignal(str)
    paneMuteToggleRequested = pyqtSignal(str)
    paneSyncRequested = pyqtSignal(str)
    paneGoToStartRequested = pyqtSignal(str)
    paneGoToEndRequested = pyqtSignal(str)
    paneUtcStartSetRequested = pyqtSignal(str, str)
    paneUtcStartRemoveRequested = pyqtSignal(str)
    syncFrameStepRequested = pyqtSignal(int)
    syncApplyRequested = pyqtSignal()
    syncCancelRequested = pyqtSignal()

    # Timeline/media signals
    seekRequested = pyqtSignal(int)
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    stateChanged = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(os.path.join("ui", "media_player", "media_center_panel.ui"))
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load MediaCenterPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        self._setup_media_player()
        self._setup_sync_bar()
        self._setup_timeline()
        self._setup_controls()

        # Internal timeline state
        self.duration = 0
        self.is_dragging = False
        self.user_is_scrolling = False
        self.zoom_level = 1.0
        self.auto_scroll_active = True
        self._utc_origin = None
        self._sync_active = False
        self._sync_timeline_text = ""

    def _setup_media_player(self):
        self.viewer_scroll = QScrollArea(self.video_container)
        self.viewer_scroll.setWidgetResizable(True)
        self.viewer_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.viewer_host = QWidget(self.viewer_scroll)
        self.viewer_grid = QGridLayout(self.viewer_host)
        self.viewer_grid.setContentsMargins(0, 0, 0, 0)
        self.viewer_grid.setSpacing(5)
        self.viewer_scroll.setWidget(self.viewer_host)
        self.videoLayout.addWidget(self.viewer_scroll)
        self._viewer_panes = [self._create_viewer_pane("")]
        self.viewer_grid.addWidget(self._viewer_panes[0], 0, 0)
        self._sync_primary_aliases()

    def _create_viewer_pane(self, source_key: str):
        pane = MediaViewerPane(source_key, self.viewer_host)
        pane.focusRequested.connect(self.paneFocusRequested)
        pane.muteToggleRequested.connect(self.paneMuteToggleRequested)
        pane.syncRequested.connect(self.paneSyncRequested)
        pane.goToStartRequested.connect(self.paneGoToStartRequested)
        pane.goToEndRequested.connect(self.paneGoToEndRequested)
        pane.utcStartSetRequested.connect(self.paneUtcStartSetRequested)
        pane.utcStartRemoveRequested.connect(self.paneUtcStartRemoveRequested)
        return pane

    def _setup_sync_bar(self):
        self.sync_bar = QFrame(self)
        self.sync_bar.setProperty("class", "media_sync_bar")
        layout = QHBoxLayout(self.sync_bar)
        layout.setContentsMargins(6, 4, 6, 4)
        self.sync_status_label = QLabel("Synchronization mode", self.sync_bar)
        self.btn_sync_prev_frame = QPushButton("◀ Frame", self.sync_bar)
        self.btn_sync_next_frame = QPushButton("Frame ▶", self.sync_bar)
        self.btn_sync_apply = QPushButton("Apply", self.sync_bar)
        self.btn_sync_cancel = QPushButton("Cancel", self.sync_bar)
        layout.addWidget(self.sync_status_label, 1)
        layout.addWidget(self.btn_sync_prev_frame)
        layout.addWidget(self.btn_sync_next_frame)
        layout.addWidget(self.btn_sync_apply)
        layout.addWidget(self.btn_sync_cancel)
        self.btn_sync_prev_frame.clicked.connect(lambda: self.syncFrameStepRequested.emit(-1))
        self.btn_sync_next_frame.clicked.connect(lambda: self.syncFrameStepRequested.emit(1))
        self.btn_sync_apply.clicked.connect(self.syncApplyRequested)
        self.btn_sync_cancel.clicked.connect(self.syncCancelRequested)
        self.sync_bar.hide()
        self.mainLayout.insertWidget(1, self.sync_bar)

    def _sync_primary_aliases(self):
        pane = self._viewer_panes[0]
        self.video_widget = pane.video_widget
        self.frame_widget = pane.frame_widget
        self.player = pane.player
        self.audio = pane.audio

    def configure_viewers(self, sources: list[dict], focused_path: str = ""):
        sources = list(sources or []) or [{"path": "", "type": "media"}]
        while len(self._viewer_panes) < len(sources):
            self._viewer_panes.append(self._create_viewer_pane(""))
        while len(self._viewer_panes) > len(sources):
            pane = self._viewer_panes.pop()
            self.viewer_grid.removeWidget(pane)
            pane.player.stop()
            pane.deleteLater()

        focused_key = os.path.normcase(os.path.normpath(focused_path)) if focused_path else ""
        for index, (pane, source) in enumerate(zip(self._viewer_panes, sources)):
            path = str(source.get("path") or "")
            is_focused = bool(focused_key and os.path.normcase(os.path.normpath(path)) == focused_key)
            if not focused_key:
                is_focused = index == 0
            pane.configure(source, focused=is_focused)
            self.viewer_grid.addWidget(pane, index // 2, index % 2)
        self._sync_primary_aliases()
        return list(self._viewer_panes)

    def reset_viewers(self):
        self.configure_viewers([{"path": "", "type": "media"}], "")
        pane = self._viewer_panes[0]
        pane.source_key = ""
        pane.title_label.setText("Media")
        pane.set_timing_status("Relative")
        pane.set_sync_available(False)
        pane.set_syncing(False)
        self.clear_preview()
        self._sync_primary_aliases()

    def focus_viewer(self, focused_path: str):
        focused_key = os.path.normcase(os.path.normpath(focused_path)) if focused_path else ""
        for pane in self._viewer_panes:
            pane.set_focused(
                bool(focused_key and os.path.normcase(os.path.normpath(pane.source_key)) == focused_key)
            )

    def set_sync_availability(self, availability: dict[str, tuple[bool, str]]):
        for pane in self._viewer_panes:
            available, reason = availability.get(pane.source_key, (False, "Synchronization is unavailable."))
            pane.set_sync_available(available, reason)

    def set_navigation_availability(self, availability: dict[str, bool]):
        for pane in self._viewer_panes:
            pane.set_navigation_available(bool(availability.get(pane.source_key, False)))

    def set_sync_mode(self, active: bool, selected_path: str = ""):
        self._sync_active = bool(active)
        if not active:
            self._sync_timeline_text = ""
        self.sync_bar.setVisible(bool(active))
        selected_key = os.path.normcase(os.path.normpath(selected_path)) if selected_path else ""
        for pane in self._viewer_panes:
            pane_key = os.path.normcase(os.path.normpath(pane.source_key)) if pane.source_key else ""
            pane.set_syncing(bool(active and pane_key == selected_key))
            pane.set_sync_mode_active(active)

    def update_sync_status(self, anchor_text: str, local_ms: int, duration_ms: int, proposed_text: str):
        text = (
            f"Anchor {anchor_text} UTC  ·  Local {self._format_ms(local_ms)} / "
            f"{self._format_ms(duration_ms)}  ·  Proposed start {proposed_text} UTC"
        )
        self._sync_timeline_text = text
        self.sync_status_label.setText(text)
        self.time_label.setText(text)

    @staticmethod
    def _format_ms(ms: int):
        value = max(0, int(ms))
        seconds = value // 1000
        return f"{seconds // 60:02}:{seconds % 60:02}.{value % 1000:03}"

    def set_utc_origin(self, origin):
        self._utc_origin = origin

    def _setup_timeline(self):
        self.scroll_area: QScrollArea

        self.slider = AnnotationSlider(Qt.Orientation.Horizontal)
        self.slider.setProperty("class", "timeline_slider")
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)

        self.scroll_area.setWidget(self.slider)
        self.scroll_bar = self.scroll_area.horizontalScrollBar()
        self.scroll_bar.sliderPressed.connect(self._on_user_scroll_start)
        self.scroll_bar.sliderReleased.connect(self._on_user_scroll_end)

        self.btn_zoom_out.clicked.connect(lambda: self._change_zoom(-1))
        self.btn_zoom_in.clicked.connect(lambda: self._change_zoom(1))

    def _setup_controls(self):
        self.btn_seek_back_5.clicked.connect(lambda: self.seekRelativeRequested.emit(-5000))
        self.btn_seek_back_1.clicked.connect(lambda: self.seekRelativeRequested.emit(-1000))
        self.btn_play_pause.clicked.connect(self.playPauseRequested.emit)
        self.btn_seek_fwd_1.clicked.connect(lambda: self.seekRelativeRequested.emit(1000))
        self.btn_seek_fwd_5.clicked.connect(lambda: self.seekRelativeRequested.emit(5000))
        self._icon_volume = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self._icon_muted = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolumeMuted)
        self.btn_mute.setText("")
        self.btn_mute.setIcon(self._icon_volume)
        self.btn_mute.setToolTip("Mute")
        self.btn_mute.setAccessibleName("Mute")
        self.btn_mute.clicked.connect(self.muteToggleRequested.emit)

        self.btn_speed_025.clicked.connect(lambda: self.playbackRateRequested.emit(0.25))
        self.btn_speed_050.clicked.connect(lambda: self.playbackRateRequested.emit(0.5))
        self.btn_speed_100.clicked.connect(lambda: self.playbackRateRequested.emit(1.0))
        self.btn_speed_200.clicked.connect(lambda: self.playbackRateRequested.emit(2.0))
        self.btn_speed_400.clicked.connect(lambda: self.playbackRateRequested.emit(4.0))

    # ------------------------------------------------------------------
    # Public media API
    # ------------------------------------------------------------------
    def load_video(self, path):
        """Load media source and keep player stopped (controller decides when to play)."""
        self.player.stop()
        self.player.setSource(QUrl())
        self.show_video_surface()

        if path:
            self.player.setSource(QUrl.fromLocalFile(path))

    def play(self):
        self.player.play()

    def pause(self):
        self.player.pause()

    def stop(self):
        self.player.stop()

    def toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self.player.setPosition(0)
            self.player.play()

    def set_position(self, ms):
        self.player.setPosition(ms)

    def set_playback_rate(self, rate):
        self.player.setPlaybackRate(rate)

    def set_mute_button_state(self, is_muted: bool):
        if is_muted:
            self.btn_mute.setText("")
            self.btn_mute.setIcon(self._icon_muted)
            self.btn_mute.setToolTip("Unmute")
            self.btn_mute.setAccessibleName("Unmute")
        else:
            self.btn_mute.setText("")
            self.btn_mute.setIcon(self._icon_volume)
            self.btn_mute.setToolTip("Mute")
            self.btn_mute.setAccessibleName("Mute")

    def set_duration(self, ms):
        self.duration = ms
        self.slider.setRange(0, ms)
        self._update_label(self.slider.value())

    def show_video_surface(self):
        self.frame_widget.hide()
        self.video_widget.show()

    def show_frame_surface(self):
        self.video_widget.hide()
        self.frame_widget.show()

    def clear_preview(self):
        for pane in self._viewer_panes:
            pane.clear_preview()
            pane.video_widget.repaint()

    def set_frame_image(self, image):
        if image is None or image.isNull():
            self.clear_preview()
            return
        self.frame_widget.set_frame_pixmap(QPixmap.fromImage(image))
        self.show_frame_surface()

    def set_markers(self, markers):
        self.slider.markers = markers
        self.slider.update()

    # ------------------------------------------------------------------
    # Player/timeline synchronization
    # ------------------------------------------------------------------
    def on_media_position_changed(self, ms):
        self._set_timeline_position(ms)
        self.positionChanged.emit(ms)

    def on_media_duration_changed(self, ms):
        self.set_duration(ms)
        self.durationChanged.emit(ms)

    def _set_timeline_position(self, ms):
        if not self.is_dragging:
            self.slider.setValue(ms)
            self._update_label(ms)
            self._auto_scroll_to_playhead(ms)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_slider_width()

    def _change_zoom(self, direction):
        old_level = self.zoom_level
        if direction > 0:
            self.zoom_level = min(self.zoom_level * 1.5, 20.0)
        else:
            self.zoom_level = max(self.zoom_level / 1.5, 1.0)

        if abs(self.zoom_level - 1.0) < 0.05:
            self.zoom_level = 1.0

        if old_level != self.zoom_level:
            center_ratio = self._get_current_center_ratio()
            self._update_slider_width()
            self._restore_center_ratio(center_ratio)

    def _update_slider_width(self):
        viewport_width = self.scroll_area.viewport().width()
        if self.zoom_level <= 1.0:
            self.scroll_area.setWidgetResizable(True)
            self.slider.setMinimumWidth(0)
            self.slider.setMaximumWidth(16777215)
        else:
            self.scroll_area.setWidgetResizable(False)
            new_width = int(viewport_width * self.zoom_level)
            self.slider.setMinimumWidth(new_width)
            self.slider.setMaximumWidth(new_width)

    def _on_user_scroll_start(self):
        self.user_is_scrolling = True
        self.auto_scroll_active = False

    def _on_user_scroll_end(self):
        self.user_is_scrolling = False
        self._check_and_restore_auto_follow()

    def _check_and_restore_auto_follow(self):
        current_ms = self.slider.value()
        if self.duration <= 0 or self.slider.width() <= 0:
            return

        ratio = current_ms / self.duration
        target_x = int(ratio * self.slider.width())

        viewport_w = self.scroll_area.viewport().width()
        current_scroll = self.scroll_area.horizontalScrollBar().value()

        if current_scroll <= target_x <= current_scroll + viewport_w:
            self.auto_scroll_active = True

    def _auto_scroll_to_playhead(self, current_ms):
        if self.zoom_level <= 1.0 or self.duration <= 0:
            return
        if self.user_is_scrolling or not self.auto_scroll_active:
            return

        ratio = current_ms / self.duration
        slider_width = self.slider.width()
        target_x = int(ratio * slider_width)

        viewport_w = self.scroll_area.viewport().width()
        current_scroll = self.scroll_area.horizontalScrollBar().value()

        is_visible = current_scroll <= target_x <= current_scroll + viewport_w

        if not is_visible:
            center_x = target_x - (viewport_w // 2)
            self.scroll_area.horizontalScrollBar().setValue(center_x)

    def _get_current_center_ratio(self):
        if self.slider.width() <= 0:
            return 0.5

        scroll = self.scroll_area.horizontalScrollBar().value()
        viewport = self.scroll_area.viewport().width()
        center_pixel = scroll + (viewport / 2)
        return center_pixel / self.slider.width()

    def _restore_center_ratio(self, ratio):
        new_width = self.slider.width()
        new_center_pixel = int(new_width * ratio)
        viewport = self.scroll_area.viewport().width()
        new_scroll = new_center_pixel - (viewport // 2)
        self.scroll_area.horizontalScrollBar().setValue(new_scroll)

    def _update_label(self, current_ms):
        def fmt(ms):
            s = ms // 1000
            m = s // 60
            return f"{m:02}:{s % 60:02}.{ms % 1000:03}"

        if self._sync_active and self._sync_timeline_text:
            self.time_label.setText(self._sync_timeline_text)
            return
        label = f"{fmt(current_ms)} / {fmt(self.duration)}"
        if isinstance(self._utc_origin, _datetime.datetime):
            current_utc = self._utc_origin + _datetime.timedelta(milliseconds=max(0, int(current_ms)))
            label = f"{label}  ·  {current_utc.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC"
        self.time_label.setText(label)

    def _on_slider_pressed(self):
        self.is_dragging = True
        self.auto_scroll_active = True

    def _on_slider_moved(self, val):
        self._update_label(val)

    def _on_slider_released(self):
        self.is_dragging = False
        self.seekRequested.emit(self.slider.value())

    def _on_error(self):
        print(f"Media Error: {self.player.errorString()}")
