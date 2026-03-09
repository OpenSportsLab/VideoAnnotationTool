from PyQt6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import QUrl

class VideoSurface(QWidget):
    """
    A shared, standalone widget dedicated to rendering video content.
    It encapsulates the QMediaPlayer, QAudioOutput, and QVideoWidget.
    
    Used by Classification, Localization, and Description modes to ensure
    consistent rendering behavior.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 1. Layout setup
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # 2. Player Components
        self.player = QMediaPlayer()
        
        self.audio_output = QAudioOutput()
        # [CRITICAL] Ensure volume is UP. This fixes the "no sound" issue in other modes.
        self.audio_output.setVolume(1.0) 
        self.player.setAudioOutput(self.audio_output)
        
        self.video_widget = QVideoWidget()
        self.video_widget.setProperty("class", "video_preview_widget")
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.player.setVideoOutput(self.video_widget)
        
        # 3. Add video widget to layout
        self.layout.addWidget(self.video_widget)

        

    def load_source(self, path):
        """
        Loads the video source. 
        Note: The playing logic (delay, auto-play) is handled by MediaController.
        """
        # Reset source to clear buffer
        self.player.stop()
        self.player.setSource(QUrl())
        
        if path:
            url = QUrl.fromLocalFile(path)
            self.player.setSource(url)