import mimetypes
import os

from PyQt6.QtCore import QMimeDatabase, QObject, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer

from controllers.media import (
    FramesNpyMediaBackend,
    TrackingParquetMediaBackend,
    VideoMediaBackend,
)

try:
    import numpy as np
except Exception:  # pragma: no cover - exercised via runtime guard
    np = None

try:
    import pandas as pd
except Exception:  # pragma: no cover - exercised via runtime guard
    pd = None

try:
    import pyarrow
except Exception:  # pragma: no cover - exercised via runtime guard
    pyarrow = None


class MediaController(QObject):
    """
    Public playback facade for media routing and runtime state.

    Format-specific playback lives in internal backend classes:
    - Qt multimedia video playback for standard video files.
    - Timer-driven NumPy frame-stack playback for `frames_npy` inputs.
    - Timer-driven pitch rendering for `tracking_parquet` inputs.
    """

    playbackStateChanged = pyqtSignal(bool)
    muteStateChanged = pyqtSignal(bool)
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)

    _VIDEO_EXTENSIONS = {
        ".mp4",
        ".avi",
        ".mov",
        ".mkv",
        ".webm",
        ".m4v",
        ".wmv",
        ".mpeg",
        ".mpg",
        ".m2ts",
        ".mts",
        ".ts",
        ".flv",
        ".3gp",
        ".ogv",
        ".mxf",
    }
    _NON_VIDEO_EXTENSIONS = {
        ".txt",
        ".md",
        ".json",
        ".jsonl",
        ".csv",
        ".tsv",
        ".xml",
        ".yaml",
        ".yml",
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".gif",
        ".webp",
        ".tif",
        ".tiff",
        ".mp3",
        ".wav",
        ".flac",
        ".aac",
        ".ogg",
        ".m4a",
        ".npy",
        ".parquet",
    }
    _NON_VIDEO_MIME_PREFIXES = ("image/", "text/", "audio/")
    _NON_VIDEO_MIME_TYPES = {
        "application/json",
        "application/xml",
        "application/pdf",
        "application/vnd.apache.parquet",
    }
    _VIDEO_CODEC_INFO = (
        "Your system cannot decode this video's format (e.g., AV1, DivX, or Xvid). "
        "The audio might play, but the video hardware decoder has failed.\n\n"
        "To fix this, please transcode your file to a standard H.264 MP4 format. "
        "Run the following command in your terminal:\n\n"
        "ffmpeg -i input.mp4 -vcodec libx264 -acodec aac output.mp4"
    )
    _FRAME_DEFAULT_FPS = 2.0
    _FRAME_TIMER_INTERVAL_MS = 30
    _TIMESTAMP_MAX_STEP_MS = 60000.0

    _BACKEND_VIDEO = "video"
    _BACKEND_FRAMES_NPY = "frames_npy"
    _BACKEND_TRACKING_PARQUET = "tracking_parquet"

    _TRACKING_IMAGE_WIDTH = 960
    _TRACKING_IMAGE_HEIGHT = 640
    _TRACKING_PITCH_LENGTH = 105.0
    _TRACKING_PITCH_WIDTH = 68.0
    _TRACKING_PITCH_PADDING = 2.0
    _TRACKING_FIELD_LIGHT = "#6da942"
    _TRACKING_FIELD_DARK = "#507d2a"
    _TRACKING_HOME_COLOR = "#CC0000"
    _TRACKING_AWAY_COLOR = "#0066CC"
    _TRACKING_BALL_COLOR = "#800080"

    def __init__(self, player: QMediaPlayer, media_panel=None):
        super().__init__()
        self.player = player
        self.media_panel = media_panel
        self.video_widget = getattr(media_panel, "video_widget", None)

        self._current_backend = None
        self._current_source = None
        self._active_backend = None
        self._backend_by_type = {
            self._BACKEND_VIDEO: VideoMediaBackend(self),
            self._BACKEND_FRAMES_NPY: FramesNpyMediaBackend(self),
            self._BACKEND_TRACKING_PARQUET: TrackingParquetMediaBackend(self),
        }

        self.player.errorOccurred.connect(self._handle_player_error)
        self.player.mediaStatusChanged.connect(self._handle_player_media_status_changed)
        self.player.playbackStateChanged.connect(self._handle_player_playback_state_changed)
        self.player.positionChanged.connect(self._handle_player_position_changed)
        self.player.durationChanged.connect(self._handle_player_duration_changed)

        if self.video_widget and hasattr(self.video_widget, "videoSink"):
            sink = self.video_widget.videoSink()
            if sink:
                sink.videoFrameChanged.connect(self._handle_video_frame_rendered)

    def _canonical_input_type(self, raw_type: str, path: str = "") -> str:
        clean = str(raw_type or "").strip().lower()
        if clean == "frame_npy":
            return self._BACKEND_FRAMES_NPY
        if clean:
            return clean
        return self._infer_media_type_from_path(path)

    def _coerce_source_fps(self, value, default: float) -> float:
        try:
            fps = float(value)
        except Exception:
            fps = default
        if fps <= 0:
            return default
        return fps

    def _infer_media_type_from_path(self, path: str) -> str:
        _, extension = os.path.splitext(str(path or ""))
        extension = extension.lower()
        if extension == ".npy":
            return self._BACKEND_FRAMES_NPY
        if extension == ".parquet":
            return self._BACKEND_TRACKING_PARQUET
        if extension in self._NON_VIDEO_EXTENSIONS:
            return "unknown"
        return self._BACKEND_VIDEO

    def _normalize_media_source(self, source):
        if isinstance(source, dict):
            raw_source = dict(source)
        elif isinstance(source, str):
            raw_source = {"path": source}
        else:
            return None

        path = str(raw_source.get("path") or "").strip()
        if not path:
            return None

        source_type = self._canonical_input_type(raw_source.get("type"), path)
        normalized = {
            "path": os.path.normpath(path),
            "type": source_type,
        }
        if source_type in {self._BACKEND_FRAMES_NPY, self._BACKEND_TRACKING_PARQUET}:
            normalized["fps"] = self._coerce_source_fps(
                raw_source.get("fps"),
                self._FRAME_DEFAULT_FPS,
            )
        elif raw_source.get("fps") not in (None, ""):
            try:
                fps = float(raw_source.get("fps"))
            except Exception:
                fps = None
            if fps and fps > 0:
                normalized["fps"] = fps
        return normalized

    def _is_supported_media_source(self, source: dict) -> bool:
        return source.get("type") in {
            self._BACKEND_VIDEO,
            self._BACKEND_FRAMES_NPY,
            self._BACKEND_TRACKING_PARQUET,
        }

    def _source_key(self, source: dict) -> tuple[str, str]:
        if not isinstance(source, dict):
            return ("", "")
        return (
            self._fs_path_key(source.get("path")),
            str(source.get("type") or ""),
        )

    def _fallback_current_source(self):
        current_path = self.current_source_path()
        if not current_path:
            return None
        return self._normalize_media_source(current_path)

    def _backend_for_type(self, source_type: str):
        return self._backend_by_type.get(str(source_type or ""))

    def _show_video_surface(self):
        if self.media_panel and hasattr(self.media_panel, "show_video_surface"):
            self.media_panel.show_video_surface()

    def _show_frame_image(self, image):
        if self.media_panel and hasattr(self.media_panel, "set_frame_image"):
            self.media_panel.set_frame_image(image)

    def _clear_preview(self):
        if self.media_panel and hasattr(self.media_panel, "clear_preview"):
            self.media_panel.clear_preview()
        elif self.video_widget:
            self.video_widget.update()
            self.video_widget.repaint()

    def _trigger_error_dialog(
        self,
        error_details: str,
        *,
        title: str = "Media Playback Error",
        text: str = "Unable to load media.",
        informative_text: str = "",
    ):
        self.stop()

        try:
            from ui.dialogs import MediaErrorDialog

            parent = self.video_widget or getattr(self.media_panel, "frame_widget", None)
            error_dialog = MediaErrorDialog(
                error_details,
                parent=parent,
                title=title,
                text=text,
                informative_text=informative_text,
            )
            error_dialog.exec()
        except ImportError as exc:
            print(f"Failed to import MediaErrorDialog: {exc}")

    def _trigger_video_decode_error(self, error_details: str):
        self._trigger_error_dialog(
            error_details,
            title="Video Decoding Error",
            text="<b>Unsupported Video Codec Detected</b>",
            informative_text=self._VIDEO_CODEC_INFO,
        )

    def _trigger_frame_load_error(self, title: str, summary: str, error_details: str):
        self._trigger_error_dialog(
            error_details,
            title=title,
            text=f"<b>{summary}</b>",
            informative_text=(
                "Expected a `.npy` file containing uint8 frame stacks shaped "
                "`(N, H, W, 3)` or `(N, H, W, 4)`."
            ),
        )

    def _trigger_tracking_load_error(self, title: str, summary: str, error_details: str):
        self._trigger_error_dialog(
            error_details,
            title=title,
            text=f"<b>{summary}</b>",
            informative_text=(
                "Expected a Parquet file with PFF-style tracking columns "
                "`homePlayers`, `awayPlayers`, and `balls`, with optional "
                "`*Smoothed` fallbacks."
            ),
        )

    def _get_numpy_module(self):
        return np

    def _get_pandas_module(self):
        return pd

    def _get_pyarrow_module(self):
        return pyarrow

    def _handle_player_error(self, error: QMediaPlayer.Error, error_string: str):
        if self._active_backend is None:
            return
        self._active_backend.on_player_error(error, error_string)

    def _handle_player_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        if self._active_backend is None:
            return
        self._active_backend.on_player_media_status_changed(status)

    def _handle_player_playback_state_changed(self, state: QMediaPlayer.PlaybackState):
        if self._active_backend is None:
            return
        self._active_backend.on_player_playback_state_changed(state)

    def _handle_player_position_changed(self, position: int):
        if self._active_backend is None:
            return
        self._active_backend.on_player_position_changed(position)

    def _handle_player_duration_changed(self, duration: int):
        if self._active_backend is None:
            return
        self._active_backend.on_player_duration_changed(duration)

    def _handle_video_frame_rendered(self, *args):
        if self._active_backend is None:
            return
        self._active_backend.on_video_frame_rendered(*args)

    def load_and_play(self, source, auto_play: bool = True):
        normalized_source = self._normalize_media_source(source)
        self.stop()

        if not normalized_source or not self._is_supported_media_source(normalized_source):
            return

        backend = self._backend_for_type(normalized_source.get("type"))
        if backend is None:
            return

        self._active_backend = backend
        self._current_backend = normalized_source["type"]
        if backend.load_source(normalized_source, auto_play):
            self._current_source = normalized_source
            return

        self._active_backend = None
        self._current_backend = None
        self._current_source = None

    def current_source_path(self) -> str:
        if self._active_backend is not None:
            source_path = self._active_backend.current_source_path()
            if source_path:
                return source_path

        if isinstance(self._current_source, dict):
            source_path = str(self._current_source.get("path") or "")
            if source_path:
                return source_path

        try:
            current_source = self.player.source()
            if current_source.isValid() and current_source.isLocalFile():
                return current_source.toLocalFile()
        except Exception:
            return ""
        return ""

    def current_position_ms(self) -> int:
        if self._active_backend is not None:
            return self._active_backend.current_position_ms()
        return max(0, int(self.player.position()))

    def is_playing(self) -> bool:
        if self._active_backend is not None:
            return self._active_backend.is_playing()
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def route_media_selection(self, target_source, ensure_playback: bool = False):
        normalized_source = self._normalize_media_source(target_source)
        if not normalized_source or not self._is_supported_media_source(normalized_source):
            self.stop()
            return

        current_source = self._current_source or self._fallback_current_source()
        same_source = self._source_key(current_source) == self._source_key(normalized_source)
        should_load_and_play = (not same_source) or (ensure_playback and not self.is_playing())
        if should_load_and_play:
            if normalized_source["type"] == self._BACKEND_VIDEO:
                self.load_and_play(normalized_source["path"])
            else:
                self.load_and_play(normalized_source)

    def is_muted(self) -> bool:
        audio_output = self.player.audioOutput()
        if audio_output is None:
            return False
        return bool(audio_output.isMuted())

    def set_muted(self, is_muted: bool):
        audio_output = self.player.audioOutput()
        if audio_output is None:
            return
        target = bool(is_muted)
        if bool(audio_output.isMuted()) == target:
            return
        audio_output.setMuted(target)
        self.muteStateChanged.emit(target)

    def toggle_mute(self):
        self.set_muted(not self.is_muted())

    def toggle_play_pause(self):
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def play(self):
        if self._active_backend is not None:
            self._active_backend.play()
            return
        self.player.play()

    def pause(self):
        if self._active_backend is not None:
            self._active_backend.pause()
            return
        self.player.pause()

    def stop(self):
        had_source = bool(self._current_source) or bool(self.current_source_path())

        if self._active_backend is not None:
            self._active_backend.stop()

        self._active_backend = None
        self._current_backend = None
        self._current_source = None

        self.player.stop()
        self.player.setSource(QUrl())
        self._clear_preview()

        if had_source:
            self.positionChanged.emit(0)
            self.durationChanged.emit(0)
            self.playbackStateChanged.emit(False)

    def set_looping(self, enable: bool):
        if self._current_backend != self._BACKEND_VIDEO or self._active_backend is None:
            return
        self._active_backend.set_looping(enable)

    def set_position(self, position):
        if self._active_backend is not None:
            self._active_backend.set_position(max(0, int(position)))
            return
        self.player.setPosition(max(0, int(position)))

    def set_playback_rate(self, rate: float):
        if self._active_backend is not None:
            self._active_backend.set_playback_rate(rate)
            return

        try:
            safe_rate = float(rate)
        except Exception:
            safe_rate = 1.0
        if safe_rate <= 0:
            safe_rate = 1.0
        self.player.setPlaybackRate(safe_rate)

    def seek_relative(self, delta_ms: int):
        current = self.current_position_ms()
        target = current + int(delta_ms)

        if target < 0:
            target = 0

        if self._active_backend is not None:
            duration = self._active_backend.duration_ms()
        else:
            duration = self.player.duration()
        if duration > 0 and target > duration:
            target = duration

        self.set_position(target)

    def _fs_path_key(self, path: str) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.normpath(str(path)))

    def _is_video_media_path(self, file_path: str) -> bool:
        if not file_path:
            return False

        normalized_path = os.path.normpath(str(file_path))

        if os.path.isfile(normalized_path):
            try:
                mime = QMimeDatabase().mimeTypeForFile(
                    normalized_path,
                    QMimeDatabase.MatchMode.MatchDefault,
                )
                mime_name = str(mime.name() or "")
                if mime_name.startswith("video/"):
                    return True
                if (
                    mime_name.startswith(self._NON_VIDEO_MIME_PREFIXES)
                    or mime_name in self._NON_VIDEO_MIME_TYPES
                ):
                    return False
            except Exception:
                pass

        guessed_mime, _ = mimetypes.guess_type(normalized_path)
        if isinstance(guessed_mime, str):
            if guessed_mime.startswith("video/"):
                return True
            if (
                guessed_mime.startswith(self._NON_VIDEO_MIME_PREFIXES)
                or guessed_mime in self._NON_VIDEO_MIME_TYPES
            ):
                return False

        _, extension = os.path.splitext(normalized_path)
        extension = extension.lower()
        if extension in self._VIDEO_EXTENSIONS:
            return True
        if extension in self._NON_VIDEO_EXTENSIONS:
            return False

        return True
