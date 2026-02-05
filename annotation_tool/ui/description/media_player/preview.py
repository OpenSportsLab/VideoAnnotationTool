import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel, 
    QStyleOptionSlider, QStyle
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

class ClickableSlider(QSlider):
    """A custom QSlider that jumps to the click position immediately."""
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            val = self._pixel_pos_to_value(event.pos())
            self.setValue(val)
            self.sliderMoved.emit(val)

    def _pixel_pos_to_value(self, pos):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        gr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
        sr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)

        if self.orientation() == Qt.Orientation.Horizontal:
            slider_length = sr.width()
            slider_min = gr.x()
            slider_max = gr.right() - slider_length + 1
            pos_x = pos.x()
        else:
            slider_length = sr.height()
            slider_min = gr.y()
            slider_max = gr.bottom() - slider_length + 1
            pos_x = pos.y()
            
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), pos_x - slider_min,
                                              slider_max - slider_min, opt.upsideDown)

class DescriptionMediaPreview(QWidget):
    """
    Video Player for Description Mode.
    Refactored to align with Classification's robust playback logic.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 1. Player Setup
        self.player = QMediaPlayer()
        # [FIX 1] Enable Infinite Loops (Matches Classification)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        
        self.video_widget = QVideoWidget()
        self.player.setVideoOutput(self.video_widget)
        
        # 2. Controls (Slider & Label)
        self.slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setEnabled(False) 
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setFixedWidth(120)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.time_label.setStyleSheet("color: #888; font-weight: bold;")
        
        # 3. Layout
        self.v_layout = QVBoxLayout(self)
        self.v_layout.setContentsMargins(0, 0, 0, 0)
        self.v_layout.setSpacing(5)
        
        self.v_layout.addWidget(self.video_widget, 1) 
        
        h_controls = QHBoxLayout()
        h_controls.setContentsMargins(5, 0, 5, 5)
        h_controls.addWidget(self.slider)
        h_controls.addWidget(self.time_label)
        self.v_layout.addLayout(h_controls)

        # 4. Connections
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.errorOccurred.connect(self._on_error)
        
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderPressed.connect(self.player.pause) 
        self.slider.sliderReleased.connect(self.player.play) 

        self._duration_ms = 0

    def load_video(self, path):
        """Loads the video from the given path."""
        # Ensure we have a valid path string
        url = QUrl.fromLocalFile(path) if path else QUrl()
        self.player.setSource(url)
        
        # [FIX 2] Explicitly call play() immediately after setting source.
        # This, combined with the Manager's delayed play, ensures the video surface attaches correctly.
        if path:
            self.player.play()

    def _on_duration_changed(self, duration):
        self._duration_ms = duration
        if duration > 0:
            self.slider.setRange(0, duration)
            self.slider.setEnabled(True)
            self.slider.setValue(0)
            self._update_time_label(0, duration)
        else:
            self.slider.setEnabled(False)

    def _on_position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self._update_time_label(position, self._duration_ms)

    def _on_slider_moved(self, position):
        self.player.setPosition(position)
        self._update_time_label(position, self._duration_ms)

    def _update_time_label(self, current_ms, total_ms):
        def fmt(ms):
            s = (ms // 1000) % 60
            m = (ms // 60000) % 60
            return f"{m:02}:{s:02}"
        self.time_label.setText(f"{fmt(current_ms)} / {fmt(total_ms)}")

    def _on_error(self):
        err_msg = self.player.errorString()
        print(f"Video Player Error: {err_msg}")