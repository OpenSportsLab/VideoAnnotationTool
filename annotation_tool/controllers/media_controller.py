import mimetypes
import os
import datetime as _datetime

from PyQt6.QtCore import QElapsedTimer, QMimeDatabase, QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer

from controllers.media import (
    FramesNpyMediaBackend,
    PlayerCentroidsH5MediaBackend,
    PlayerJointsH5MediaBackend,
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

try:
    import h5py
except Exception:  # pragma: no cover - exercised via runtime guard
    h5py = None


class _SingleMediaController(QObject):
    """
    Public playback facade for media routing and runtime state.

    Format-specific playback lives in internal backend classes:
    - Qt multimedia video playback for standard video files.
    - Timer-driven NumPy frame-stack playback for `frames_npy` inputs.
    - Timer-driven pitch rendering for `tracking_parquet` inputs.
    - Timer-driven skeleton rendering for `player_joints_h5` inputs.
    - Timer-driven centroid rendering for `player_centroids_h5` inputs.
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
        ".h5",
        ".hdf5",
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
    _RASTER_FRAME_CACHE_LIMIT = 128

    _BACKEND_VIDEO = "video"
    _BACKEND_FRAMES_NPY = "frames_npy"
    _BACKEND_TRACKING_PARQUET = "tracking_parquet"
    _BACKEND_PLAYER_JOINTS_H5 = "player_joints_h5"
    _BACKEND_PLAYER_CENTROIDS_H5 = "player_centroids_h5"

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

    def __init__(self, player: QMediaPlayer, media_panel=None, error_handler=None):
        super().__init__()
        self.player = player
        self.media_panel = media_panel
        self.video_widget = getattr(media_panel, "video_widget", None)
        self._error_handler = error_handler

        self._current_backend = None
        self._current_source = None
        self._active_backend = None
        self._backend_by_type = {
            self._BACKEND_VIDEO: VideoMediaBackend(self),
            self._BACKEND_FRAMES_NPY: FramesNpyMediaBackend(self),
            self._BACKEND_TRACKING_PARQUET: TrackingParquetMediaBackend(self),
            self._BACKEND_PLAYER_JOINTS_H5: PlayerJointsH5MediaBackend(self),
            self._BACKEND_PLAYER_CENTROIDS_H5: PlayerCentroidsH5MediaBackend(self),
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
        if extension in {".h5", ".hdf5"}:
            return self._BACKEND_PLAYER_JOINTS_H5
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
        if "UTC_time_start" in raw_source:
            normalized["UTC_time_start"] = raw_source.get("UTC_time_start")
        if source_type in {self._BACKEND_PLAYER_JOINTS_H5, self._BACKEND_PLAYER_CENTROIDS_H5}:
            ball_path = str(raw_source.get("ball_path") or "").strip()
            if ball_path:
                normalized["ball_path"] = os.path.normpath(ball_path)
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
            self._BACKEND_PLAYER_JOINTS_H5,
            self._BACKEND_PLAYER_CENTROIDS_H5,
        }

    def _source_key(self, source: dict) -> tuple[str, ...]:
        if not isinstance(source, dict):
            return ("", "")
        utc_start_key = (
            "UTC_time_start",
            str(source.get("UTC_time_start")),
        ) if "UTC_time_start" in source else ("UTC_time_start_absent", "")
        if source.get("type") in {self._BACKEND_PLAYER_JOINTS_H5, self._BACKEND_PLAYER_CENTROIDS_H5}:
            return (
                self._fs_path_key(source.get("path")),
                str(source.get("type") or ""),
                self._fs_path_key(source.get("ball_path")),
                *utc_start_key,
            )
        return (
            self._fs_path_key(source.get("path")),
            str(source.get("type") or ""),
            *utc_start_key,
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
        if self._error_handler is not None:
            self._error_handler(title, text, error_details)
            return

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

    def _trigger_player_joints_h5_load_error(self, title: str, summary: str, error_details: str):
        self._trigger_error_dialog(
            error_details,
            title=title,
            text=f"<b>{summary}</b>",
            informative_text=(
                "Expected an HDF5 file with flat equal-length datasets, a "
                "`timestamp_utc` column, and joint coordinate columns named "
                "`<joint>_x`, `<joint>_y`, and optionally `<joint>_z`."
            ),
        )

    def _trigger_player_centroids_h5_load_error(self, title: str, summary: str, error_details: str):
        self._trigger_error_dialog(
            error_details,
            title=title,
            text=f"<b>{summary}</b>",
            informative_text=(
                "Expected an HDF5 file with flat equal-length datasets, a "
                "`timestamp_utc` column, and player centroid columns `x` and `y`."
            ),
        )

    def _get_numpy_module(self):
        return np

    def _get_pandas_module(self):
        return pd

    def _get_pyarrow_module(self):
        return pyarrow

    def _get_h5py_module(self):
        return h5py

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

    def timeline_origin_utc(self):
        clip = getattr(self._active_backend, "_clip", None)
        origin = getattr(clip, "origin_utc", None)
        return origin if isinstance(origin, _datetime.datetime) else None

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


class MediaController(QObject):
    """Sample-level playback coordinator for one or more synchronized inputs."""

    playbackStateChanged = pyqtSignal(bool)
    muteStateChanged = pyqtSignal(bool)
    positionChanged = pyqtSignal(int)
    durationChanged = pyqtSignal(int)

    @property
    def _RASTER_FRAME_CACHE_LIMIT(self):
        return self._single._RASTER_FRAME_CACHE_LIMIT

    @_RASTER_FRAME_CACHE_LIMIT.setter
    def _RASTER_FRAME_CACHE_LIMIT(self, value):
        self._single._RASTER_FRAME_CACHE_LIMIT = value

    @staticmethod
    def _parse_utc_time_start(value):
        if isinstance(value, _datetime.datetime):
            parsed = value
        else:
            text = str(value or "").strip()
            if not text:
                return None
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            try:
                parsed = _datetime.datetime.fromisoformat(text)
            except (TypeError, ValueError):
                return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(_datetime.timezone.utc).replace(tzinfo=None)
        return parsed

    def __init__(self, player: QMediaPlayer, media_panel=None):
        super().__init__()
        self.player = player
        self.media_panel = media_panel
        self._single = _SingleMediaController(player, media_panel)
        self._group_active = False
        self._sessions = []
        self._group_key = ()
        self._focused_path = ""
        self._global_origin_utc = None
        self._group_duration_ms = 0
        self._group_position_ms = 0
        self._anchor_position_ms = 0
        self._playback_rate = 1.0
        self._group_playing = False
        self._pending_group_autoplay = False
        self._globally_muted = False
        self._feed_muted = {}
        self._clock = QElapsedTimer()
        self._master_timer = QTimer(self)
        self._master_timer.setInterval(30)
        self._master_timer.timeout.connect(self._advance_group)
        self._drift_tick = 0

        self._single.positionChanged.connect(
            lambda value: self.positionChanged.emit(value) if not self._group_active else None
        )
        self._single.durationChanged.connect(
            lambda value: self.durationChanged.emit(value) if not self._group_active else None
        )
        self._single.playbackStateChanged.connect(
            lambda value: self.playbackStateChanged.emit(value) if not self._group_active else None
        )
        self._single.muteStateChanged.connect(
            lambda value: self.muteStateChanged.emit(value) if not self._group_active else None
        )
        if media_panel is not None:
            media_panel.destroyed.connect(self._handle_media_panel_destroyed)
            if hasattr(media_panel, "paneFocusRequested"):
                media_panel.paneFocusRequested.connect(self.focus_source)
            if hasattr(media_panel, "paneMuteToggleRequested"):
                media_panel.paneMuteToggleRequested.connect(self.toggle_feed_mute)

    def _handle_media_panel_destroyed(self):
        self._master_timer.stop()
        self._group_playing = False
        self._pending_group_autoplay = False
        self._sessions = []

    def __getattr__(self, name):
        single = self.__dict__.get("_single")
        if single is not None:
            return getattr(single, name)
        raise AttributeError(name)

    def load_and_play(self, source, auto_play: bool = True):
        """Load one source directly; retained as the canonical single-source API."""
        if self._group_active:
            self._stop_group(clear_state=True)
        self._single.media_panel = self.media_panel
        self._single.video_widget = getattr(self.media_panel, "video_widget", None)
        self._single._error_handler = None
        error_override = self.__dict__.get("_trigger_error_dialog")
        if error_override is not None:
            self._single._trigger_error_dialog = error_override
        self._single.load_and_play(source, auto_play=auto_play)

    def route_media_group(self, sources, focused_path: str = "", ensure_playback: bool = False):
        normalized = []
        for source in list(sources or []):
            item = self._single._normalize_media_source(source)
            if item is not None:
                normalized.append(item)
        if not normalized:
            self.stop()
            return

        group_key = tuple(self._single._source_key(source) for source in normalized)
        if self._group_active and group_key == self._group_key:
            self.focus_source(focused_path or normalized[0]["path"])
            if ensure_playback and not self.is_playing():
                if self._all_sessions_ready():
                    self.play()
                else:
                    self._pending_group_autoplay = True
            return

        self._stop_group(clear_state=True)
        self._single.stop()
        self._group_active = True
        self._pending_group_autoplay = bool(ensure_playback)
        self._group_key = group_key
        self._focused_path = focused_path or normalized[0]["path"]
        panes = (
            self.media_panel.configure_viewers(normalized, self._focused_path)
            if self.media_panel is not None and hasattr(self.media_panel, "configure_viewers")
            else [self.media_panel]
        )

        for index, source in enumerate(normalized):
            pane = panes[index] if index < len(panes) else self.media_panel
            if not self._single._is_supported_media_source(source):
                if pane is not None and hasattr(pane, "show_status"):
                    pane.show_status(f"Unsupported media type: {source.get('type', 'unknown')}")
                self._sessions.append(self._session_record(source, pane, None))
                continue

            if index == 0:
                session = self._single
                session.media_panel = pane
                session.video_widget = getattr(pane, "video_widget", None)
            else:
                session = _SingleMediaController(pane.player, pane)
            record = self._session_record(source, pane, session)
            self._sessions.append(record)
            session._error_handler = self._pane_error_handler(pane, record)
            session.durationChanged.connect(lambda value, rec=record: self._on_session_duration(rec, value))
            session.load_and_play(source, auto_play=False)
            record["valid"] = session._active_backend is not None
            if record["utc_start_present"]:
                record["origin_utc"] = self._parse_utc_time_start(source.get("UTC_time_start"))
                record["utc_start_invalid"] = record["origin_utc"] is None
            else:
                record["origin_utc"] = session.timeline_origin_utc()
            record["duration_ms"] = self._session_duration(session)
            if not record["valid"] and pane is not None and hasattr(pane, "show_status"):
                pane.show_status("Unable to load this input")

        self._recalculate_group_timeline()
        self.set_position(0)
        if ensure_playback and self._all_sessions_ready():
            self._pending_group_autoplay = False
            self.play()

    def route_media_selection(self, source, ensure_playback: bool = False):
        self.route_media_group([source], str(source.get("path") if isinstance(source, dict) else source), ensure_playback)

    def _session_record(self, source, pane, session):
        return {
            "source": source,
            "pane": pane,
            "controller": session,
            "origin_utc": None,
            "offset_ms": 0,
            "duration_ms": 0,
            "valid": False,
            "utc_start_present": "UTC_time_start" in source,
            "utc_start_invalid": False,
        }

    def _pane_error_handler(self, pane, record):
        def handle(_title, summary, details):
            record["valid"] = False
            record["duration_ms"] = 0
            if pane is not None and hasattr(pane, "show_status"):
                pane.show_status(f"{summary}\n{details}")
            if self._group_active:
                self._recalculate_group_timeline()
                if self._pending_group_autoplay and self._all_sessions_ready():
                    self._pending_group_autoplay = False
                    self.play()
        return handle

    @staticmethod
    def _session_duration(session):
        if session is None or session._active_backend is None:
            return 0
        return max(0, int(session._active_backend.duration_ms()))

    def _on_session_duration(self, record, duration):
        record["duration_ms"] = max(0, int(duration))
        if self._group_active:
            self._recalculate_group_timeline()
            if self._pending_group_autoplay and self._all_sessions_ready():
                self._pending_group_autoplay = False
                self.play()

    def _all_sessions_ready(self):
        valid_records = [record for record in self._sessions if record["valid"]]
        if not valid_records:
            return False
        for record in valid_records:
            session = record["controller"]
            if session is not None and session._current_backend == session._BACKEND_VIDEO:
                if record["duration_ms"] <= 0:
                    return False
        return True

    def _recalculate_group_timeline(self):
        utc_origins = [
            record["origin_utc"]
            for record in self._sessions
            if record["valid"] and isinstance(record["origin_utc"], _datetime.datetime)
        ]
        self._global_origin_utc = min(utc_origins) if utc_origins else None
        duration = 0
        for record in self._sessions:
            origin = record["origin_utc"]
            if self._global_origin_utc is not None and isinstance(origin, _datetime.datetime):
                record["offset_ms"] = max(
                    0,
                    int(round((origin - self._global_origin_utc).total_seconds() * 1000.0)),
                )
                timing = f"UTC +{record['offset_ms'] / 1000.0:.3f}s"
            else:
                record["offset_ms"] = 0
                timing = (
                    "Relative ⚠ invalid UTC_time_start"
                    if record["utc_start_invalid"]
                    else "Relative"
                )
            pane = record["pane"]
            if pane is not None and hasattr(pane, "set_timing_status"):
                tooltip = (
                    "UTC_time_start could not be parsed; this input is aligned as relative media."
                    if record["utc_start_invalid"]
                    else ""
                )
                pane.set_timing_status(timing, tooltip)
            if record["valid"]:
                duration = max(duration, record["offset_ms"] + record["duration_ms"])
        changed = duration != self._group_duration_ms
        self._group_duration_ms = duration
        if self.media_panel is not None and hasattr(self.media_panel, "set_utc_origin"):
            self.media_panel.set_utc_origin(self._global_origin_utc)
        if changed:
            self.durationChanged.emit(duration)

    def focus_source(self, path: str):
        self._focused_path = str(path or "")
        if self.media_panel is not None and hasattr(self.media_panel, "focus_viewer"):
            self.media_panel.focus_viewer(self._focused_path)

    def toggle_feed_mute(self, path: str):
        key = self._single._fs_path_key(path)
        self._feed_muted[key] = not bool(self._feed_muted.get(key, False))
        self._apply_audio_state()

    def _apply_audio_state(self):
        records = self._sessions if self._group_active else []
        if not records:
            output = self._single.player.audioOutput()
            if output is not None:
                output.setMuted(self._globally_muted)
            return
        for record in records:
            session = record["controller"]
            pane = record["pane"]
            if session is None:
                continue
            feed_muted = bool(self._feed_muted.get(self._single._fs_path_key(record["source"].get("path")), False))
            output = session.player.audioOutput()
            if output is not None:
                output.setMuted(self._globally_muted or feed_muted)
            if pane is not None and hasattr(pane, "set_feed_muted"):
                pane.set_feed_muted(feed_muted)

    def is_muted(self) -> bool:
        return bool(self._globally_muted)

    def set_muted(self, is_muted: bool):
        target = bool(is_muted)
        if target == self._globally_muted:
            return
        self._globally_muted = target
        self._apply_audio_state()
        self.muteStateChanged.emit(target)

    def toggle_mute(self):
        self.set_muted(not self.is_muted())

    def current_source_path(self) -> str:
        if self._group_active:
            return self._focused_path or str(self._sessions[0]["source"].get("path") or "")
        return self._single.current_source_path()

    def current_position_ms(self) -> int:
        if not self._group_active:
            return self._single.current_position_ms()
        if self._group_playing and self._clock.isValid():
            value = self._anchor_position_ms + int(self._clock.elapsed() * self._playback_rate)
            return max(0, min(value, self._group_duration_ms))
        return max(0, int(self._group_position_ms))

    def is_playing(self) -> bool:
        return self._group_playing if self._group_active else self._single.is_playing()

    def toggle_play_pause(self):
        self.pause() if self.is_playing() else self.play()

    def play(self):
        if not self._group_active:
            self._single.play()
            return
        if self._group_duration_ms <= 0:
            return
        if self._group_position_ms >= self._group_duration_ms:
            self._group_position_ms = 0
        self._anchor_position_ms = self._group_position_ms
        self._clock.restart()
        self._group_playing = True
        self._start_video_sessions()
        self._master_timer.start()
        self.playbackStateChanged.emit(True)

    def pause(self):
        if not self._group_active:
            self._single.pause()
            return
        if not self._group_playing:
            return
        self._group_position_ms = self.current_position_ms()
        self._group_playing = False
        self._pending_group_autoplay = False
        self._master_timer.stop()
        for record in self._sessions:
            session = record["controller"]
            if session is not None and session._current_backend == session._BACKEND_VIDEO:
                session.pause()
        self.playbackStateChanged.emit(False)

    def stop(self):
        if self._group_active:
            self._stop_group(clear_state=True)
            return
        self._single.stop()

    def _stop_group(self, *, clear_state: bool):
        if self._master_timer.isActive():
            self._master_timer.stop()
        for record in self._sessions:
            session = record.get("controller")
            if session is not None:
                session.stop()
                if session is not self._single:
                    session.deleteLater()
        had_group = self._group_active
        self._sessions = []
        self._group_active = False
        self._group_playing = False
        self._group_position_ms = 0
        self._anchor_position_ms = 0
        self._group_duration_ms = 0
        self._global_origin_utc = None
        if clear_state:
            self._group_key = ()
        if self.media_panel is not None and hasattr(self.media_panel, "set_utc_origin"):
            self.media_panel.set_utc_origin(None)
        if had_group:
            self.positionChanged.emit(0)
            self.durationChanged.emit(0)
            self.playbackStateChanged.emit(False)

    def set_position(self, position):
        if not self._group_active:
            self._single.set_position(position)
            return
        target = max(0, min(int(position), self._group_duration_ms))
        self._group_position_ms = target
        self._anchor_position_ms = target
        if self._group_playing:
            self._clock.restart()
        self._render_group_position(target, force_video_seek=True)
        self.positionChanged.emit(target)

    def seek_relative(self, delta_ms: int):
        self.set_position(self.current_position_ms() + int(delta_ms))

    def set_playback_rate(self, rate: float):
        try:
            safe_rate = float(rate)
        except Exception:
            safe_rate = 1.0
        if safe_rate <= 0:
            safe_rate = 1.0
        if not self._group_active:
            self._single.set_playback_rate(safe_rate)
            return
        self._group_position_ms = self.current_position_ms()
        self._anchor_position_ms = self._group_position_ms
        self._playback_rate = safe_rate
        if self._group_playing:
            self._clock.restart()
        for record in self._sessions:
            session = record["controller"]
            if session is not None:
                session.set_playback_rate(safe_rate)

    def set_looping(self, enable: bool):
        records = self._sessions if self._group_active else [{"controller": self._single}]
        for record in records:
            session = record["controller"]
            if session is not None:
                session.set_looping(enable)

    def _advance_group(self):
        if not self._group_playing:
            return
        position = self.current_position_ms()
        if position >= self._group_duration_ms:
            self._group_position_ms = self._group_duration_ms
            self._render_group_position(self._group_position_ms, force_video_seek=True)
            self._group_playing = False
            self._master_timer.stop()
            self.playbackStateChanged.emit(False)
            self.positionChanged.emit(self._group_position_ms)
            return
        self._group_position_ms = position
        self._drift_tick = (self._drift_tick + 1) % 8
        self._render_group_position(position, force_video_seek=self._drift_tick == 0)
        self.positionChanged.emit(position)

    def _render_group_position(self, global_position: int, *, force_video_seek: bool):
        for record in self._sessions:
            if not record["valid"]:
                continue
            local = int(global_position) - int(record["offset_ms"])
            pane = record["pane"]
            session = record["controller"]
            if local < 0 or local > record["duration_ms"]:
                if session._current_backend == session._BACKEND_VIDEO:
                    session.pause()
                if pane is not None and hasattr(pane, "show_status"):
                    pane.show_status("Not available at this UTC time")
                continue
            if session._current_backend == session._BACKEND_VIDEO:
                if pane is not None and hasattr(pane, "show_video_surface"):
                    pane.show_video_surface()
                drift = abs(session.current_position_ms() - local)
                fps = float(record["source"].get("fps") or 0.0)
                threshold = max(50, int(round(1000.0 / fps)) if fps > 0 else 50)
                if force_video_seek and drift > threshold:
                    session.set_position(local)
                if self._group_playing and not session.is_playing():
                    session.play()
            else:
                session.set_position(local)

    def _start_video_sessions(self):
        for record in self._sessions:
            session = record["controller"]
            if not record["valid"] or session is None:
                continue
            local = self._group_position_ms - record["offset_ms"]
            if session._current_backend == session._BACKEND_VIDEO and 0 <= local <= record["duration_ms"]:
                session.set_position(local)
                session.play()
        self._apply_audio_state()
