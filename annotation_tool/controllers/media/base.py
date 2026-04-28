from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtMultimedia import QMediaPlayer

if TYPE_CHECKING:
    from controllers.media_controller import MediaController


class BaseMediaBackend:
    """Internal backend contract for MediaController playback implementations."""

    backend_type = ""

    def __init__(self, controller: "MediaController"):
        self.controller = controller
        self.player = controller.player
        self.media_panel = controller.media_panel
        self._current_source = None
        self._playback_rate = 1.0

    def load_source(self, source: dict, auto_play: bool) -> bool:
        raise NotImplementedError

    def play(self):
        return None

    def pause(self):
        return None

    def stop(self):
        self._current_source = None
        self._playback_rate = 1.0

    def set_looping(self, enable: bool):
        return None

    def set_position(self, position_ms: int):
        return None

    def set_playback_rate(self, rate: float):
        self._playback_rate = self._coerce_playback_rate(rate)

    def current_position_ms(self) -> int:
        return max(0, int(self.player.position()))

    def duration_ms(self) -> int:
        return max(0, int(self.player.duration()))

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def current_source_path(self) -> str:
        if isinstance(self._current_source, dict):
            source_path = str(self._current_source.get("path") or "")
            if source_path:
                return source_path
        return ""

    def on_player_error(self, error: QMediaPlayer.Error, error_string: str):
        return None

    def on_player_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        return None

    def on_player_playback_state_changed(self, state: QMediaPlayer.PlaybackState):
        return None

    def on_player_position_changed(self, position: int):
        return None

    def on_player_duration_changed(self, duration: int):
        return None

    def on_video_frame_rendered(self, *_args):
        return None

    @staticmethod
    def _coerce_playback_rate(rate: float) -> float:
        try:
            safe_rate = float(rate)
        except Exception:
            safe_rate = 1.0
        if safe_rate <= 0:
            safe_rate = 1.0
        return safe_rate
