from __future__ import annotations

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtMultimedia import QMediaPlayer

from .base import BaseMediaBackend


class VideoMediaBackend(BaseMediaBackend):
    backend_type = "video"

    def __init__(self, controller):
        super().__init__(controller)
        self._frame_received = False

        self.play_timer = QTimer(controller)
        self.play_timer.setSingleShot(True)
        self.play_timer.setInterval(150)
        self.play_timer.timeout.connect(self._execute_play)

        self.watchdog_timer = QTimer(controller)
        self.watchdog_timer.setSingleShot(True)
        self.watchdog_timer.setInterval(1500)
        self.watchdog_timer.timeout.connect(self._check_for_black_screen)

    def load_source(self, source: dict, auto_play: bool) -> bool:
        if not self.controller._is_video_media_path(source["path"]):
            return False

        self.stop()
        self._current_source = source
        self._playback_rate = 1.0
        self.controller._show_video_surface()
        self.player.setSource(QUrl.fromLocalFile(source["path"]))
        if auto_play:
            self.play_timer.start()
        return True

    def play(self):
        self._frame_received = False
        self.player.play()
        self.watchdog_timer.start()

    def pause(self):
        self.player.pause()

    def stop(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
        if self.watchdog_timer.isActive():
            self.watchdog_timer.stop()
        self._frame_received = False
        super().stop()

    def set_looping(self, enable: bool):
        self.player.setLoops(
            QMediaPlayer.Loops.Infinite if enable else QMediaPlayer.Loops.Once
        )

    def set_position(self, position_ms: int):
        self.player.setPosition(max(0, int(position_ms)))

    def set_playback_rate(self, rate: float):
        super().set_playback_rate(rate)
        self.player.setPlaybackRate(self._playback_rate)

    def on_player_error(self, error: QMediaPlayer.Error, error_string: str):
        if error == QMediaPlayer.Error.NoError:
            return
        print(f"[Media Error] Code: {error}, Message: {error_string}")
        self.controller._trigger_video_decode_error(
            f"Player Error Code {error}: {error_string}"
        )

    def on_player_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.controller._trigger_video_decode_error(
                "Status Error: Invalid media or completely unsupported video format."
            )
        elif status == QMediaPlayer.MediaStatus.LoadedMedia and not self.player.hasVideo():
            self.controller._trigger_video_decode_error(
                "Status Error: The file has no decodable video stream."
            )

    def on_player_playback_state_changed(self, state: QMediaPlayer.PlaybackState):
        self.controller.playbackStateChanged.emit(
            state == QMediaPlayer.PlaybackState.PlayingState
        )

    def on_player_position_changed(self, position: int):
        self.controller.positionChanged.emit(max(0, int(position)))

    def on_player_duration_changed(self, duration: int):
        self.controller.durationChanged.emit(max(0, int(duration)))

    def on_video_frame_rendered(self, *_args):
        self._frame_received = True

    def _execute_play(self):
        self._frame_received = False
        self.player.play()
        self.watchdog_timer.start()

    def _check_for_black_screen(self):
        is_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        is_loaded = self.player.mediaStatus() in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }

        if is_playing and is_loaded and self.player.hasVideo() and not self._frame_received:
            self.controller._trigger_video_decode_error(
                "Watchdog Timeout: The hardware video decoder crashed silently "
                "and failed to render any frames within 1.5 seconds."
            )
