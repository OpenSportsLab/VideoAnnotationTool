from PyQt6.QtCore import QUrl, QTimer, QObject
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QWidget

class MediaController(QObject):
    """
    A unified controller for managing video playback logic across all modes.
    Now includes a 'Watchdog' mechanism to catch silent hardware decoder failures 
    (e.g., AV1 video fails, but Audio keeps playing causing a zombie black screen).
    """
    def __init__(self, player: QMediaPlayer, video_widget: QWidget = None):
        super().__init__()
        self.player = player
        self.video_widget = video_widget
        
        # 1. Initialize all member variables and timers FIRST
        self._frame_received = False
        
        # 2. Setup Play Timer
        self.play_timer = QTimer()
        self.play_timer.setSingleShot(True)
        self.play_timer.setInterval(150)
        self.play_timer.timeout.connect(self._execute_play)

        # 3. [NEW] Setup Watchdog Timer to catch silent Black Screens
        self.watchdog_timer = QTimer()
        self.watchdog_timer.setSingleShot(True)
        self.watchdog_timer.setInterval(1500) # Check 1.5 seconds after play starts
        self.watchdog_timer.timeout.connect(self._check_for_black_screen)
        
        # 3. Connect external player and video signals
        self.player.errorOccurred.connect(self._handle_media_error)
        self.player.mediaStatusChanged.connect(self._handle_media_status) # [NEW] Added status check
        
        if self.video_widget and hasattr(self.video_widget, 'videoSink'):
            sink = self.video_widget.videoSink()
            if sink:
                # Every time a pixel frame is actually rendered, this triggers
                sink.videoFrameChanged.connect(self._on_frame_rendered)

    def _on_frame_rendered(self, *args):
        """Marks that the GPU successfully decoded and drew at least one frame."""
        self._frame_received = True

    def _trigger_error_dialog(self, error_details: str):
        """Stops playback immediately and blocks the UI with an error dialog."""
        self.stop() # Force kill playback
        
        try:
            from ui.common.dialogs import MediaErrorDialog
            error_dialog = MediaErrorDialog(error_details, parent=self.video_widget)
            error_dialog.exec() # Block UI thread
        except ImportError as e:
            print(f"Failed to import MediaErrorDialog: {e}")

    def _check_for_black_screen(self):
        """
        The Ultimate Catch: Watchdog timer triggered.
        """
        is_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        is_loaded = self.player.mediaStatus() in [QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia]
        
        if is_playing and is_loaded and self.player.hasVideo() and not self._frame_received:
            # Pass a concise technical reason instead of a long paragraph
            self._trigger_error_dialog("Watchdog Timeout: The hardware video decoder crashed silently and failed to render any frames within 1.5 seconds.")

    def _handle_media_status(self, status: QMediaPlayer.MediaStatus):
        """
        Catches silent failures from MediaStatus.
        """
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._trigger_error_dialog("Status Error: Invalid Media or completely unsupported file format.")
            
        elif status == QMediaPlayer.MediaStatus.LoadedMedia:
            if not self.player.hasVideo():
                self._trigger_error_dialog("Status Error: The file has no decodable video stream (e.g., missing AV1 hardware decoder).")

    def _handle_media_error(self, error: QMediaPlayer.Error, error_string: str):
        """
        Catches standard MediaFoundation/AVFoundation load errors.
        """
        if error != QMediaPlayer.Error.NoError:
            print(f"[Media Error] Code: {error}, Message: {error_string}")
            self._trigger_error_dialog(f"Player Error Code {error}: {error_string}")

    def load_and_play(self, file_path: str, auto_play: bool = True):
        self.stop() 

        if not file_path:
            return

        self.player.setSource(QUrl.fromLocalFile(file_path))

        if auto_play:
            self.play_timer.start()

    def _execute_play(self):
        """Starts playback and launches the Watchdog."""
        self._frame_received = False # Reset the frame flag
        self.player.play()
        self.watchdog_timer.start()  # Unleash the watchdog

    def toggle_play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self._frame_received = False
            self.player.play()
            self.watchdog_timer.start()

    def stop(self):
        """Stops playback and cancels all timers."""
        if self.play_timer.isActive():
            self.play_timer.stop()
        if self.watchdog_timer.isActive():
            self.watchdog_timer.stop()
            
        self.player.stop()
        self.player.setSource(QUrl())
        
        if self.video_widget:
            self.video_widget.update()
            self.video_widget.repaint()

    def set_looping(self, enable: bool):
        if enable:
            self.player.setLoops(QMediaPlayer.Loops.Infinite)
        else:
            self.player.setLoops(QMediaPlayer.Loops.Once)

    def set_position(self, position):
        self.player.setPosition(position)