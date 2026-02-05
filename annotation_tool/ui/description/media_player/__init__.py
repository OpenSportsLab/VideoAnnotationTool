from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtMultimedia import QMediaPlayer

from .preview import DescriptionMediaPreview
from .controls import DescriptionNavToolbar

class DescriptionMediaPlayer(QWidget):
    """
    Center Panel for Description Mode.
    Combines DescriptionMediaPreview and DescriptionNavToolbar.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. Video Player
        self.preview = DescriptionMediaPreview()
        self.layout.addWidget(self.preview, 1) # Stretch factor 1
        
        # 2. Controls
        self.controls = DescriptionNavToolbar()
        self.layout.addWidget(self.controls)
        
        # Expose widgets for Controller access
        self.player = self.preview.player
        self.prev_action = self.controls.prev_action
        self.prev_clip = self.controls.prev_clip
        self.play_btn = self.controls.play_btn
        self.next_clip = self.controls.next_clip
        self.next_action = self.controls.next_action

    def load_video(self, path):
        self.preview.load_video(path)

    def toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()