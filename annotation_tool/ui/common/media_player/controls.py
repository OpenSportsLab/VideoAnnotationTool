from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal

class PlaybackControlBar(QWidget):
    seekRelativeRequested = pyqtSignal(int)
    stopRequested = pyqtSignal()
    playPauseRequested = pyqtSignal()
    nextPrevClipRequested = pyqtSignal(int)
    nextPrevAnnotRequested = pyqtSignal(int)
    playbackRateRequested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        
        # Row 1: Navigation
        r1 = QHBoxLayout()
        btns_r1 = [
            ("Prev Clip", lambda: self.nextPrevClipRequested.emit(-1)),
            ("<< 5s", lambda: self.seekRelativeRequested.emit(-5000)),
            ("<< 1s", lambda: self.seekRelativeRequested.emit(-1000)),
            ("Play/Pause", lambda: self.playPauseRequested.emit()),
            ("1s >>", lambda: self.seekRelativeRequested.emit(1000)),
            ("5s >>", lambda: self.seekRelativeRequested.emit(5000)),
            ("Next Clip", lambda: self.nextPrevClipRequested.emit(1))
        ]
        for txt, func in btns_r1:
            b = QPushButton(txt)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(func)
            r1.addWidget(b)
        layout.addLayout(r1)
        
        # Row 2: Speed & Event Jump
        r2 = QHBoxLayout()
        
        btn_prev_ann = QPushButton("Prev Event")
        btn_prev_ann.clicked.connect(lambda: self.nextPrevAnnotRequested.emit(-1))
        r2.addWidget(btn_prev_ann)
        
        speeds = [0.25, 0.5, 1.0, 2.0, 4.0]
        for s in speeds:
            b = QPushButton(f"{s}x")
            b.clicked.connect(lambda _, rate=s: self.playbackRateRequested.emit(rate))
            r2.addWidget(b)
            
        btn_next_ann = QPushButton("Next Event")
        btn_next_ann.clicked.connect(lambda: self.nextPrevAnnotRequested.emit(1))
        r2.addWidget(btn_next_ann)
        
        layout.addLayout(r2)