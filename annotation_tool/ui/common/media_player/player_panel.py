from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import pyqtSignal, QUrl

# [CHANGED] Import from common
from ui.common.video_surface import VideoSurface

class MediaPreviewWidget(QWidget):
    """
    Wrapper widget for the Localization media player.
    It delegates rendering to the shared VideoSurface.
    """
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    stateChanged = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        
        # [Refactor] Instantiate the Shared VideoSurface
        self.surface = VideoSurface()
        layout.addWidget(self.surface)
        
        # [Compatibility] Expose internal components for Localization Manager
        self.player = self.surface.player
        self.audio = self.surface.audio_output
        self.video_widget = self.surface.video_widget
        
        # Forward signals
        self.player.positionChanged.connect(self.positionChanged.emit)
        self.player.durationChanged.connect(self.durationChanged.emit)
        self.player.playbackStateChanged.connect(self.stateChanged.emit)
        self.player.errorOccurred.connect(self._on_error)

    def load_video(self, path):
        """Loads source via shared surface but does not auto-play."""
        # Note: Localization Manager handles the delayed play() call
        self.surface.load_source(path)
        
        # Ensure visibility for rendering
        if not self.video_widget.isVisible():
            self.video_widget.show()

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
    
    def _on_error(self):
        print(f"Media Error: {self.player.errorString()}")