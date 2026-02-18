from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton
)
from PyQt6.QtCore import Qt

class PlaybackControlBar(QWidget):
    """
    Navigation buttons for Classification Mode.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        
        self.prev_action = QPushButton("<< Prev Action")
        self.prev_clip = QPushButton("< Prev Clip")
        self.play_btn = QPushButton("Play / Pause")
        self.next_clip = QPushButton("Next Clip >")
        self.next_action = QPushButton("Next Action >>")
        
        btns = [
            self.prev_action, self.prev_clip, self.play_btn, 
            self.next_clip, self.next_action
        ]
        
        for b in btns:
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.layout.addWidget(b)
