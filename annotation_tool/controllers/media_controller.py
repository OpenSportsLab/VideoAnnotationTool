import mimetypes
import os

from PyQt6.QtCore import QElapsedTimer, QMimeDatabase, QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtMultimedia import QMediaPlayer

try:
    import numpy as np
except Exception:  # pragma: no cover - exercised via runtime guard
    np = None


class MediaController(QObject):
    """
    Unified playback controller for media routing and runtime state.

    Supported backends:
    - Qt multimedia video playback for standard video files.
    - Timer-driven NumPy frame-stack playback for `frames_npy` inputs.
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
    }
    _NON_VIDEO_MIME_PREFIXES = ("image/", "text/", "audio/")
    _NON_VIDEO_MIME_TYPES = {
        "application/json",
        "application/xml",
        "application/pdf",
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
    _BACKEND_VIDEO = "video"
    _BACKEND_FRAMES_NPY = "frames_npy"

    def __init__(self, player: QMediaPlayer, media_panel=None):
        super().__init__()
        self.player = player
        self.media_panel = media_panel
        self.video_widget = getattr(media_panel, "video_widget", None)

        self._frame_received = False
        self._current_backend = None
        self._current_source = None
        self._playback_rate = 1.0

        self._frame_data = None
        self._frame_count = 0
        self._frame_fps = self._FRAME_DEFAULT_FPS
        self._frame_duration_ms = 0
        self._frame_position_ms = 0
        self._frame_anchor_position_ms = 0
        self._frame_last_rendered_index = -1
        self._frame_last_emitted_position_ms = -1
        self._frame_playing = False
        self._frame_clock = QElapsedTimer()

        self.play_timer = QTimer(self)
        self.play_timer.setSingleShot(True)
        self.play_timer.setInterval(150)
        self.play_timer.timeout.connect(self._execute_play)

        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.setSingleShot(True)
        self.watchdog_timer.setInterval(1500)
        self.watchdog_timer.timeout.connect(self._check_for_black_screen)

        self.frame_timer = QTimer(self)
        self.frame_timer.setInterval(self._FRAME_TIMER_INTERVAL_MS)
        self.frame_timer.timeout.connect(self._advance_frame_playback)

        self.player.errorOccurred.connect(self._handle_media_error)
        self.player.mediaStatusChanged.connect(self._handle_media_status)
        self.player.playbackStateChanged.connect(self._on_player_playback_state_changed)
        self.player.positionChanged.connect(self._on_player_position_changed)
        self.player.durationChanged.connect(self._on_player_duration_changed)

        if self.video_widget and hasattr(self.video_widget, "videoSink"):
            sink = self.video_widget.videoSink()
            if sink:
                sink.videoFrameChanged.connect(self._on_frame_rendered)

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
        if source_type == self._BACKEND_FRAMES_NPY:
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
        return source.get("type") in {self._BACKEND_VIDEO, self._BACKEND_FRAMES_NPY}

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

    def _show_video_surface(self):
        if self.media_panel and hasattr(self.media_panel, "show_video_surface"):
            self.media_panel.show_video_surface()

    def _show_frame_image(self, image: QImage):
        if self.media_panel and hasattr(self.media_panel, "set_frame_image"):
            self.media_panel.set_frame_image(image)

    def _clear_preview(self):
        if self.media_panel and hasattr(self.media_panel, "clear_preview"):
            self.media_panel.clear_preview()
        elif self.video_widget:
            self.video_widget.update()
            self.video_widget.repaint()

    def _on_player_playback_state_changed(self, state):
        if self._current_backend != self._BACKEND_VIDEO:
            return
        self.playbackStateChanged.emit(state == QMediaPlayer.PlaybackState.PlayingState)

    def _on_player_position_changed(self, position: int):
        if self._current_backend != self._BACKEND_VIDEO:
            return
        self.positionChanged.emit(max(0, int(position)))

    def _on_player_duration_changed(self, duration: int):
        if self._current_backend != self._BACKEND_VIDEO:
            return
        self.durationChanged.emit(max(0, int(duration)))

    def _on_frame_rendered(self, *_args):
        self._frame_received = True

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

    def _check_for_black_screen(self):
        if self._current_backend != self._BACKEND_VIDEO:
            return

        is_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        is_loaded = self.player.mediaStatus() in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }

        if is_playing and is_loaded and self.player.hasVideo() and not self._frame_received:
            self._trigger_video_decode_error(
                "Watchdog Timeout: The hardware video decoder crashed silently "
                "and failed to render any frames within 1.5 seconds."
            )

    def _handle_media_status(self, status: QMediaPlayer.MediaStatus):
        if self._current_backend != self._BACKEND_VIDEO:
            return

        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._trigger_video_decode_error(
                "Status Error: Invalid media or completely unsupported video format."
            )
        elif status == QMediaPlayer.MediaStatus.LoadedMedia and not self.player.hasVideo():
            self._trigger_video_decode_error(
                "Status Error: The file has no decodable video stream."
            )

    def _handle_media_error(self, error: QMediaPlayer.Error, error_string: str):
        if self._current_backend != self._BACKEND_VIDEO:
            return
        if error != QMediaPlayer.Error.NoError:
            print(f"[Media Error] Code: {error}, Message: {error_string}")
            self._trigger_video_decode_error(f"Player Error Code {error}: {error_string}")

    def _validate_frame_stack(self, frame_stack) -> str:
        if frame_stack is None:
            return "The frame stack could not be loaded."
        if getattr(frame_stack, "dtype", None) != np.uint8:
            return f"Expected dtype uint8 but received {getattr(frame_stack, 'dtype', None)}."
        if getattr(frame_stack, "ndim", None) != 4:
            return f"Expected a 4D array but received ndim={getattr(frame_stack, 'ndim', None)}."
        if frame_stack.shape[0] <= 0:
            return "The frame stack contains no frames."
        if frame_stack.shape[-1] not in (3, 4):
            return f"Expected 3 or 4 channels per frame but received shape {frame_stack.shape}."
        return ""

    def _frame_index_for_position(self, position_ms: int) -> int:
        if self._frame_count <= 0:
            return 0
        if position_ms >= self._frame_duration_ms:
            return self._frame_count - 1
        frame_interval_ms = 1000.0 / self._frame_fps
        return max(0, min(self._frame_count - 1, int(position_ms / frame_interval_ms)))

    def _frame_image_for_index(self, frame_index: int) -> QImage:
        frame = self._frame_data[frame_index]
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)

        height, width, channels = frame.shape
        image_format = (
            QImage.Format.Format_RGBA8888
            if channels == 4
            else QImage.Format.Format_RGB888
        )
        return QImage(
            frame.data,
            width,
            height,
            frame.strides[0],
            image_format,
        ).copy()

    def _set_frame_position(self, position_ms: int, *, emit_position: bool):
        if self._frame_data is None:
            return

        clamped = max(0, min(int(position_ms), self._frame_duration_ms))
        self._frame_position_ms = clamped
        frame_index = self._frame_index_for_position(clamped)
        if frame_index != self._frame_last_rendered_index:
            self._show_frame_image(self._frame_image_for_index(frame_index))
            self._frame_last_rendered_index = frame_index

        if emit_position and clamped != self._frame_last_emitted_position_ms:
            self.positionChanged.emit(clamped)
            self._frame_last_emitted_position_ms = clamped

    def _load_frame_stack_source(self, source: dict, auto_play: bool):
        if np is None:
            self._trigger_frame_load_error(
                "NumPy Dependency Missing",
                "Unable to load `frames_npy` input",
                "NumPy is not installed in the current runtime.",
            )
            return

        source_path = source["path"]
        if not os.path.isfile(source_path):
            self._trigger_frame_load_error(
                "Media Load Error",
                "Frame stack file not found",
                source_path,
            )
            return

        try:
            frame_stack = np.load(source_path, mmap_mode="r")
        except Exception as exc:
            self._trigger_frame_load_error(
                "Media Load Error",
                "Unable to read frame stack",
                str(exc),
            )
            return

        validation_error = self._validate_frame_stack(frame_stack)
        if validation_error:
            self._trigger_frame_load_error(
                "Invalid Frame Stack",
                "Unsupported `frames_npy` payload",
                validation_error,
            )
            return

        self._current_backend = self._BACKEND_FRAMES_NPY
        self._current_source = source
        self._playback_rate = 1.0
        self._frame_data = frame_stack
        self._frame_count = int(frame_stack.shape[0])
        self._frame_fps = self._coerce_source_fps(
            source.get("fps"),
            self._FRAME_DEFAULT_FPS,
        )
        self._frame_duration_ms = int(round((self._frame_count / self._frame_fps) * 1000))
        self._frame_position_ms = 0
        self._frame_anchor_position_ms = 0
        self._frame_last_rendered_index = -1
        self._frame_last_emitted_position_ms = -1
        self._frame_playing = False

        self.durationChanged.emit(self._frame_duration_ms)
        self._set_frame_position(0, emit_position=True)
        if auto_play:
            self.play()

    def _execute_play(self):
        if self._current_backend != self._BACKEND_VIDEO:
            return
        self._frame_received = False
        self.player.play()
        self.watchdog_timer.start()

    def _advance_frame_playback(self):
        if not self._frame_playing:
            return

        next_position = self._frame_anchor_position_ms + int(
            self._frame_clock.elapsed() * self._playback_rate
        )
        if next_position >= self._frame_duration_ms:
            self._set_frame_position(self._frame_duration_ms, emit_position=True)
            self.frame_timer.stop()
            self._frame_playing = False
            self.playbackStateChanged.emit(False)
            return

        self._set_frame_position(next_position, emit_position=True)

    def load_and_play(self, source, auto_play: bool = True):
        normalized_source = self._normalize_media_source(source)
        self.stop()

        if not normalized_source or not self._is_supported_media_source(normalized_source):
            return

        if normalized_source["type"] == self._BACKEND_FRAMES_NPY:
            self._load_frame_stack_source(normalized_source, auto_play)
            return

        if not self._is_video_media_path(normalized_source["path"]):
            return

        self._current_backend = self._BACKEND_VIDEO
        self._current_source = normalized_source
        self._playback_rate = 1.0
        self._show_video_surface()
        self.player.setSource(QUrl.fromLocalFile(normalized_source["path"]))
        if auto_play:
            self.play_timer.start()

    def current_source_path(self) -> str:
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
        if self._current_backend == self._BACKEND_FRAMES_NPY:
            if self._frame_playing and self._frame_clock.isValid():
                next_position = self._frame_anchor_position_ms + int(
                    self._frame_clock.elapsed() * self._playback_rate
                )
                return max(0, min(next_position, self._frame_duration_ms))
            return max(0, int(self._frame_position_ms))
        return max(0, int(self.player.position()))

    def is_playing(self) -> bool:
        if self._current_backend == self._BACKEND_FRAMES_NPY:
            return bool(self._frame_playing)
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
        if self._current_backend == self._BACKEND_FRAMES_NPY:
            if self._frame_data is None:
                return
            if self._frame_position_ms >= self._frame_duration_ms and self._frame_duration_ms > 0:
                self._set_frame_position(0, emit_position=True)
            self._frame_anchor_position_ms = self._frame_position_ms
            self._frame_clock.restart()
            self._frame_playing = True
            if not self.frame_timer.isActive():
                self.frame_timer.start()
            self.playbackStateChanged.emit(True)
            return

        if self._current_backend == self._BACKEND_VIDEO:
            self._frame_received = False
            self.player.play()
            self.watchdog_timer.start()
            return

        self.player.play()

    def pause(self):
        if self._current_backend == self._BACKEND_FRAMES_NPY:
            if not self._frame_playing:
                return
            self._frame_playing = False
            self.frame_timer.stop()
            self._set_frame_position(self.current_position_ms(), emit_position=True)
            self.playbackStateChanged.emit(False)
            return

        self.player.pause()

    def stop(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
        if self.watchdog_timer.isActive():
            self.watchdog_timer.stop()
        if self.frame_timer.isActive():
            self.frame_timer.stop()

        had_source = bool(self._current_source) or bool(self.current_source_path())
        self._frame_playing = False
        self._frame_data = None
        self._frame_count = 0
        self._frame_fps = self._FRAME_DEFAULT_FPS
        self._frame_duration_ms = 0
        self._frame_position_ms = 0
        self._frame_anchor_position_ms = 0
        self._frame_last_rendered_index = -1
        self._frame_last_emitted_position_ms = -1
        self._frame_received = False

        self._current_backend = None
        self._current_source = None
        self._playback_rate = 1.0

        self.player.stop()
        self.player.setSource(QUrl())
        self._clear_preview()

        if had_source:
            self.positionChanged.emit(0)
            self.durationChanged.emit(0)
            self.playbackStateChanged.emit(False)

    def set_looping(self, enable: bool):
        if self._current_backend == self._BACKEND_VIDEO:
            self.player.setLoops(
                QMediaPlayer.Loops.Infinite if enable else QMediaPlayer.Loops.Once
            )

    def set_position(self, position):
        target = max(0, int(position))
        if self._current_backend == self._BACKEND_FRAMES_NPY:
            self._set_frame_position(target, emit_position=True)
            if self._frame_playing:
                self._frame_anchor_position_ms = self._frame_position_ms
                self._frame_clock.restart()
            return
        self.player.setPosition(target)

    def set_playback_rate(self, rate: float):
        try:
            safe_rate = float(rate)
        except Exception:
            safe_rate = 1.0
        if safe_rate <= 0:
            safe_rate = 1.0

        self._playback_rate = safe_rate
        if self._current_backend == self._BACKEND_FRAMES_NPY:
            if self._frame_playing:
                self._frame_anchor_position_ms = self.current_position_ms()
                self._frame_clock.restart()
            return
        self.player.setPlaybackRate(safe_rate)

    def seek_relative(self, delta_ms: int):
        current = self.current_position_ms()
        target = current + int(delta_ms)

        if target < 0:
            target = 0

        duration = (
            self._frame_duration_ms
            if self._current_backend == self._BACKEND_FRAMES_NPY
            else self.player.duration()
        )
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
        if extension in self._NON_VIDEO_EXTENSIONS or extension == ".npy":
            return False

        return True
