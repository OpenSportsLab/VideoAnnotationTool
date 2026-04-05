from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel, QPushButton,
    QStyle, QStyleOptionSlider, QScrollArea, QScrollBar
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen

class AnnotationSlider(QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.markers = []

    def paintEvent(self, event):
        # 1. Call system draw
        super().paintEvent(event)
        
        if not self.markers or self.maximum() <= 0: return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        
        groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
        handle_rect = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)
        
        available_width = groove.width()
        x_offset = groove.x()
        
        # 2. Draw markers
        for m in self.markers:
            start_ms = m.get('start_ms', 0)
            ratio = start_ms / self.maximum()
            x = x_offset + int(available_width * ratio)
            
            c = m.get('color', QColor('red'))
            painter.setPen(QPen(c, 2))
            painter.drawLine(x, groove.top() - 2, x, groove.bottom() + 2)

        # 3. Redraw handle on top
        painter.setPen(QPen(QColor("#FF3333"), 1))
        painter.setBrush(QColor("#FF3333"))
        painter.drawRoundedRect(handle_rect, 4, 4)


class TimelineWidget(QWidget):
    seekRequested = pyqtSignal(int)
    markerClicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setFixedHeight(60)
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(2) 
        main_layout.setContentsMargins(0, 5, 0, 5)
        
        # 1. Time Label
        self.time_label = QLabel("00:00.000 / 00:00.000")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setProperty("class", "timeline_time_lbl")
        main_layout.addWidget(self.time_label)
        
        # 2. Timeline Row
        timeline_row = QHBoxLayout()
        timeline_row.setSpacing(5)
        timeline_row.setContentsMargins(5, 0, 5, 0)
        timeline_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Zoom Out
        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.setFixedSize(24, 24)
        self.btn_zoom_out.setProperty("class", "timeline_zoom_btn")
        self.btn_zoom_out.clicked.connect(lambda: self._change_zoom(-1))
        timeline_row.addWidget(self.btn_zoom_out)

        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.setFixedHeight(30)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setProperty("class", "timeline_scroll_area")
        

        self.scroll_bar = self.scroll_area.horizontalScrollBar()
        self.scroll_bar.sliderPressed.connect(self._on_user_scroll_start)
        self.scroll_bar.sliderReleased.connect(self._on_user_scroll_end)

        self.slider = AnnotationSlider(Qt.Orientation.Horizontal)
        self.slider.setProperty("class", "timeline_slider")
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)
        
        self.scroll_area.setWidget(self.slider)
        timeline_row.addWidget(self.scroll_area)
        
        # Zoom In
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedSize(24, 24)
        self.btn_zoom_in.setProperty("class", "timeline_zoom_btn")
        self.btn_zoom_in.clicked.connect(lambda: self._change_zoom(1))
        timeline_row.addWidget(self.btn_zoom_in)
        
        main_layout.addLayout(timeline_row)
        
        # State
        self.duration = 0
        self.is_dragging = False 
        self.user_is_scrolling = False 
        self.zoom_level = 1.0
        self.auto_scroll_active = True
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_slider_width()

    def set_duration(self, ms):
        self.duration = ms
        self.slider.setRange(0, ms)
        self._update_label(self.slider.value())

    def set_position(self, ms):
        if not self.is_dragging:
            self.slider.setValue(ms)
            self._update_label(ms)
            self._auto_scroll_to_playhead(ms)

    def set_markers(self, markers):
        self.slider.markers = markers
        self.slider.update()
        
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
        if self.duration <= 0 or self.slider.width() <= 0: return

        ratio = current_ms / self.duration
        target_x = int(ratio * self.slider.width())
        
        viewport_w = self.scroll_area.viewport().width()
        current_scroll = self.scroll_area.horizontalScrollBar().value()
        
        if current_scroll <= target_x <= current_scroll + viewport_w:
            self.auto_scroll_active = True

    def _auto_scroll_to_playhead(self, current_ms):
        if self.zoom_level <= 1.0 or self.duration <= 0: return
        if self.user_is_scrolling or not self.auto_scroll_active: return

        ratio = current_ms / self.duration
        slider_width = self.slider.width()
        target_x = int(ratio * slider_width)
        
        viewport_w = self.scroll_area.viewport().width()
        current_scroll = self.scroll_area.horizontalScrollBar().value()
        
        is_visible = (current_scroll <= target_x <= current_scroll + viewport_w)
        
        if not is_visible:
            center_x = target_x - (viewport_w // 2)
            self.scroll_area.horizontalScrollBar().setValue(center_x)

    def _get_current_center_ratio(self):
        if self.slider.width() <= 0: return 0.5
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
            return f"{m:02}:{s%60:02}.{ms%1000:03}"
        self.time_label.setText(f"{fmt(current_ms)} / {fmt(self.duration)}")

    def _on_slider_pressed(self): 
        self.is_dragging = True
        self.auto_scroll_active = True
        
    def _on_slider_moved(self, val): self._update_label(val)
    def _on_slider_released(self):
        self.is_dragging = False
        self.seekRequested.emit(self.slider.value())