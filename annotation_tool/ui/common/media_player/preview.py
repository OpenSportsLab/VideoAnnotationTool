from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import Qt, pyqtSignal, QUrl

class MediaPreviewWidget(QWidget):
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)
    stateChanged = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        
        self.video_widget = QVideoWidget()
        self.video_widget.setProperty("class", "video_preview_widget")
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        
        # [Fix] Max volume ensures audio sink keeps the clock running
        self.audio.setVolume(1.0) 
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)
        
        layout.addWidget(self.video_widget)
        
        self.player.positionChanged.connect(self.positionChanged.emit)
        self.player.durationChanged.connect(self.durationChanged.emit)
        self.player.playbackStateChanged.connect(self.stateChanged.emit)
        self.player.errorOccurred.connect(self._on_error)

    def load_video(self, path):
        """
        Loads the video source BUT DOES NOT PLAY.
        Playback is handled by the Controller via QTimer to prevent macOS rendering freeze.
        """
        # 1. Reset pipeline
        self.player.stop()
        self.player.setSource(QUrl()) 
        
        # 2. Force widget visibility before loading
        if not self.video_widget.isVisible():
            self.video_widget.show()
        
        # 3. Load
        self.player.setSource(QUrl.fromLocalFile(path))
        
        # [CRITICAL CHANGE] REMOVED self.player.play()
        # We leave the player in StoppedState. The Manager will trigger play() 
        # after a short delay (200ms) to ensure the window handle is valid.

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
            # Auto-restart if at end
            if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self.player.setPosition(0)
            self.player.play()

    def set_position(self, ms): 
        self.player.setPosition(ms)

    def set_playback_rate(self, rate): 
        self.player.setPlaybackRate(rate)
    
    def _on_error(self):
        print(f"Media Error: {self.player.errorString()}")