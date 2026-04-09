import os

from PyQt6 import uic
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QScrollArea, QSizePolicy, QSlider, QStyle, QStyleOptionSlider, QWidget

from utils import resource_path


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
        self._setup_timeline()
        self._setup_controls()

        # Internal timeline state
        self.duration = 0
        self.is_dragging = False
        self.user_is_scrolling = False
        self.zoom_level = 1.0
        self.auto_scroll_active = True

        # Timeline seek should drive player seeking by default
        self.seekRequested.connect(self.set_position)

    def _setup_media_player(self):
        self.video_widget = QVideoWidget(self.video_container)
        self.video_widget.setProperty("class", "video_preview_widget")
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.videoLayout.addWidget(self.video_widget)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(1.0)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)

        self.player.positionChanged.connect(self._on_player_position_changed)
        self.player.durationChanged.connect(self._on_player_duration_changed)
        self.player.playbackStateChanged.connect(self.stateChanged.emit)
        self.player.errorOccurred.connect(self._on_error)

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

        if not self.video_widget.isVisible():
            self.video_widget.show()

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
        self.btn_mute.setText("Unmute" if is_muted else "Mute")

    def set_duration(self, ms):
        self.duration = ms
        self.slider.setRange(0, ms)
        self._update_label(self.slider.value())

    def set_markers(self, markers):
        self.slider.markers = markers
        self.slider.update()

    # ------------------------------------------------------------------
    # Player/timeline synchronization
    # ------------------------------------------------------------------
    def _on_player_position_changed(self, ms):
        self._set_timeline_position(ms)
        self.positionChanged.emit(ms)

    def _on_player_duration_changed(self, ms):
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

        self.time_label.setText(f"{fmt(current_ms)} / {fmt(self.duration)}")

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
