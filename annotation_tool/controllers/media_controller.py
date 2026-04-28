import json
import math
import mimetypes
import os
import statistics
from bisect import bisect_left, bisect_right

from PyQt6.QtCore import QElapsedTimer, QMimeDatabase, QObject, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtMultimedia import QMediaPlayer

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
    Unified playback controller for media routing and runtime state.

    Supported backends:
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

        self._frame_received = False
        self._current_backend = None
        self._current_source = None
        self._playback_rate = 1.0

        self._frame_data = None
        self._frame_count = 0
        self._frame_fps = self._FRAME_DEFAULT_FPS
        self._frame_time_axis_ms = []
        self._frame_hold_ms = int(round(1000.0 / self._FRAME_DEFAULT_FPS))
        self._frame_duration_ms = 0
        self._frame_position_ms = 0
        self._frame_anchor_position_ms = 0
        self._frame_last_rendered_index = -1
        self._frame_last_emitted_position_ms = -1
        self._frame_playing = False
        self._frame_image_cache = {}
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

    def _is_raster_backend(self) -> bool:
        return self._current_backend in {
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

    @staticmethod
    def _coerce_finite_float(value):
        try:
            number = float(value)
        except Exception:
            return None
        if not math.isfinite(number):
            return None
        return number

    def _build_uniform_frame_timing(self, frame_count: int, fps: float):
        safe_fps = self._coerce_source_fps(fps, self._FRAME_DEFAULT_FPS)
        if frame_count <= 0:
            hold_ms = max(1, int(round(1000.0 / safe_fps)))
            return [], 0, hold_ms

        frame_interval_ms = 1000.0 / safe_fps
        axis = [int(round(index * frame_interval_ms)) for index in range(frame_count)]
        hold_ms = max(1, int(round(frame_interval_ms)))
        duration_ms = int(round(frame_count * frame_interval_ms))
        return axis, duration_ms, hold_ms

    def _build_timestamp_frame_timing(self, values, fallback_fps: float):
        raw_values = list(values) if values is not None else []
        if len(raw_values) < 2:
            return self._build_uniform_frame_timing(len(raw_values), fallback_fps)

        known = []
        for index, value in enumerate(raw_values):
            finite_value = self._coerce_finite_float(value)
            if finite_value is not None:
                known.append((index, finite_value))

        if len(known) < 2:
            return self._build_uniform_frame_timing(len(raw_values), fallback_fps)

        positive_diffs = []
        for (_prev_idx, prev_value), (_next_idx, next_value) in zip(known, known[1:]):
            diff = next_value - prev_value
            if diff > 0:
                positive_diffs.append(diff)

        if not positive_diffs:
            return self._build_uniform_frame_timing(len(raw_values), fallback_fps)

        median_delta = statistics.median(positive_diffs)
        if (
            not math.isfinite(median_delta)
            or median_delta <= 0
            or median_delta > self._TIMESTAMP_MAX_STEP_MS
        ):
            return self._build_uniform_frame_timing(len(raw_values), fallback_fps)

        frame_count = len(raw_values)
        filled = [0.0] * frame_count
        for index, value in known:
            filled[index] = value

        first_known_idx, first_known_value = known[0]
        last_known_idx, last_known_value = known[-1]

        for index in range(first_known_idx - 1, -1, -1):
            filled[index] = filled[index + 1] - median_delta

        for (left_idx, left_value), (right_idx, right_value) in zip(known, known[1:]):
            span = right_idx - left_idx
            if span <= 1:
                continue
            for offset in range(1, span):
                ratio = offset / span
                filled[left_idx + offset] = left_value + ((right_value - left_value) * ratio)

        for index in range(last_known_idx + 1, frame_count):
            filled[index] = filled[index - 1] + median_delta

        origin = filled[0]
        axis = []
        previous_ms = 0
        for value in filled:
            ms = max(0, int(round(value - origin)))
            if ms < previous_ms:
                ms = previous_ms
            axis.append(ms)
            previous_ms = ms

        hold_ms = max(1, int(round(median_delta)))
        duration_ms = axis[-1] + hold_ms if axis else 0
        return axis, duration_ms, hold_ms

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

    def _frame_axis_value_for_index(self, frame_index: int) -> int:
        if not self._frame_time_axis_ms:
            return 0
        clamped_index = max(0, min(frame_index, len(self._frame_time_axis_ms) - 1))
        return int(self._frame_time_axis_ms[clamped_index])

    def _frame_index_for_position(self, position_ms: int, prefer_nearest: bool = False) -> int:
        if self._frame_count <= 0 or not self._frame_time_axis_ms:
            return 0

        target = max(0, int(position_ms))
        if target >= self._frame_duration_ms:
            return self._frame_count - 1

        if prefer_nearest:
            insertion_idx = bisect_left(self._frame_time_axis_ms, target)
            if insertion_idx <= 0:
                return 0
            if insertion_idx >= self._frame_count:
                return self._frame_count - 1

            prev_time = self._frame_time_axis_ms[insertion_idx - 1]
            next_time = self._frame_time_axis_ms[insertion_idx]
            if abs(next_time - target) < abs(target - prev_time):
                return insertion_idx
            return insertion_idx - 1

        return max(0, min(self._frame_count - 1, bisect_right(self._frame_time_axis_ms, target) - 1))

    def _frame_image_from_array_index(self, frame_index: int) -> QImage:
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

    @staticmethod
    def _is_nullish_tracking_cell(value) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip().lower() in {"", "none", "null", "nan"}
        if isinstance(value, (list, dict, tuple)):
            return False
        try:
            return bool(pd is not None and pd.isna(value))
        except Exception:
            return False

    def _tracking_column_is_available(self, dataframe, column_name: str) -> bool:
        if column_name not in dataframe.columns:
            return False
        for value in dataframe[column_name].tolist():
            if not self._is_nullish_tracking_cell(value):
                return True
        return False

    def _choose_tracking_column(self, dataframe, raw_name: str, smoothed_name: str):
        if self._tracking_column_is_available(dataframe, raw_name):
            return raw_name
        if self._tracking_column_is_available(dataframe, smoothed_name):
            return smoothed_name
        return None

    def _decode_tracking_payload(self, payload):
        if isinstance(payload, (list, dict)):
            return payload
        if self._is_nullish_tracking_cell(payload):
            return None
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except Exception:
                return None
        return None

    def _parse_tracking_players(self, payload):
        decoded = self._decode_tracking_payload(payload)
        if isinstance(decoded, dict):
            decoded = [decoded]
        if not isinstance(decoded, list):
            return []

        players = []
        for item in decoded:
            if not isinstance(item, dict):
                continue
            x = self._coerce_finite_float(item.get("x"))
            y = self._coerce_finite_float(item.get("y"))
            if x is None or y is None:
                continue

            player = {"x": x, "y": y}
            jersey_num = item.get("jerseyNum")
            if jersey_num not in (None, ""):
                jersey_text = str(jersey_num).strip()
                if jersey_text and jersey_text.lower() not in {"nan", "none", "null"}:
                    player["jerseyNum"] = jersey_text
            players.append(player)
        return players

    def _parse_tracking_ball(self, payload):
        decoded = self._decode_tracking_payload(payload)
        candidates = []
        if isinstance(decoded, dict):
            candidates = [decoded]
        elif isinstance(decoded, list):
            candidates = list(decoded)
        else:
            return None

        for item in candidates:
            if not isinstance(item, dict):
                continue
            x = self._coerce_finite_float(item.get("x"))
            y = self._coerce_finite_float(item.get("y"))
            if x is None or y is None:
                continue

            ball = {"x": x, "y": y}
            z = self._coerce_finite_float(item.get("z"))
            if z is not None:
                ball["z"] = z
            return ball
        return None

    def _tracking_pitch_layout(self, image_width: int, image_height: int):
        world_width = self._TRACKING_PITCH_LENGTH + (2 * self._TRACKING_PITCH_PADDING)
        world_height = self._TRACKING_PITCH_WIDTH + (2 * self._TRACKING_PITCH_PADDING)
        scale = min(image_width / world_width, image_height / world_height)
        content_width = world_width * scale
        content_height = world_height * scale
        origin_x = (image_width - content_width) / 2.0
        origin_y = (image_height - content_height) / 2.0
        return {
            "scale": scale,
            "origin_x": origin_x,
            "origin_y": origin_y,
            "world_height": world_height,
        }

    def _tracking_world_to_canvas(self, x: float, y: float, layout: dict):
        scale = layout["scale"]
        origin_x = layout["origin_x"]
        origin_y = layout["origin_y"]
        world_height = layout["world_height"]
        px = origin_x + ((x + self._TRACKING_PITCH_PADDING) * scale)
        py = origin_y + ((world_height - (y + self._TRACKING_PITCH_PADDING)) * scale)
        return px, py

    def _tracking_rect(self, x: float, y: float, width: float, height: float, layout: dict) -> QRectF:
        left, top = self._tracking_world_to_canvas(x, y + height, layout)
        right, bottom = self._tracking_world_to_canvas(x + width, y, layout)
        return QRectF(left, top, right - left, bottom - top)

    def _draw_tracking_pitch(self, painter: QPainter, layout: dict):
        field_light = QColor(self._TRACKING_FIELD_LIGHT)
        field_dark = QColor(self._TRACKING_FIELD_DARK)
        line_color = QColor("white")
        line_width = max(2.0, layout["scale"] * 0.18)

        image_width = int((self._TRACKING_PITCH_LENGTH + (2 * self._TRACKING_PITCH_PADDING)) * layout["scale"])
        image_height = int((self._TRACKING_PITCH_WIDTH + (2 * self._TRACKING_PITCH_PADDING)) * layout["scale"])
        painter.fillRect(
            QRectF(layout["origin_x"], layout["origin_y"], image_width, image_height),
            field_light,
        )

        stripe_width = self._TRACKING_PITCH_LENGTH / 20.0
        for stripe_index in range(20):
            stripe_rect = self._tracking_rect(
                stripe_index * stripe_width,
                0.0,
                stripe_width,
                self._TRACKING_PITCH_WIDTH,
                layout,
            )
            painter.fillRect(
                stripe_rect,
                field_light if stripe_index % 2 == 0 else field_dark,
            )

        pen = QPen(line_color)
        pen.setWidthF(line_width)
        painter.setPen(pen)

        outer_rect = self._tracking_rect(
            0.0,
            0.0,
            self._TRACKING_PITCH_LENGTH,
            self._TRACKING_PITCH_WIDTH,
            layout,
        )
        painter.drawRect(outer_rect)

        x_mid = self._TRACKING_PITCH_LENGTH / 2.0
        y_mid = self._TRACKING_PITCH_WIDTH / 2.0
        x1, y1 = self._tracking_world_to_canvas(x_mid, 0.0, layout)
        x2, y2 = self._tracking_world_to_canvas(x_mid, self._TRACKING_PITCH_WIDTH, layout)
        painter.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))

        center_x, center_y = self._tracking_world_to_canvas(x_mid, y_mid, layout)
        center_radius = 9.15 * layout["scale"]
        painter.drawEllipse(
            QRectF(
                center_x - center_radius,
                center_y - center_radius,
                center_radius * 2,
                center_radius * 2,
            )
        )
        painter.setBrush(line_color)
        painter.drawEllipse(QRectF(center_x - 3, center_y - 3, 6, 6))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for x_start in (0.0, self._TRACKING_PITCH_LENGTH - 16.5):
            painter.drawRect(
                self._tracking_rect(
                    x_start,
                    y_mid - 20.15,
                    16.5,
                    40.3,
                    layout,
                )
            )

        for x_start in (0.0, self._TRACKING_PITCH_LENGTH - 5.5):
            painter.drawRect(
                self._tracking_rect(
                    x_start,
                    y_mid - 8.5,
                    5.5,
                    17.0,
                    layout,
                )
            )

        for penalty_x in (11.0, self._TRACKING_PITCH_LENGTH - 11.0):
            dot_x, dot_y = self._tracking_world_to_canvas(penalty_x, y_mid, layout)
            painter.setBrush(line_color)
            painter.drawEllipse(QRectF(dot_x - 3, dot_y - 3, 6, 6))
            painter.setBrush(Qt.BrushStyle.NoBrush)

        left_arc_rect = self._tracking_rect(11.0 - 9.15, y_mid - 9.15, 18.3, 18.3, layout)
        right_arc_rect = self._tracking_rect(
            self._TRACKING_PITCH_LENGTH - 11.0 - 9.15,
            y_mid - 9.15,
            18.3,
            18.3,
            layout,
        )
        painter.drawArc(left_arc_rect, 308 * 16, 104 * 16)
        painter.drawArc(right_arc_rect, 127 * 16, 106 * 16)

        goal_pen = QPen(line_color)
        goal_pen.setWidthF(line_width + 2.0)
        painter.setPen(goal_pen)
        goal_left_top = self._tracking_world_to_canvas(0.0, y_mid + 3.66, layout)
        goal_left_bottom = self._tracking_world_to_canvas(0.0, y_mid - 3.66, layout)
        goal_right_top = self._tracking_world_to_canvas(self._TRACKING_PITCH_LENGTH, y_mid + 3.66, layout)
        goal_right_bottom = self._tracking_world_to_canvas(
            self._TRACKING_PITCH_LENGTH,
            y_mid - 3.66,
            layout,
        )
        painter.drawLine(
            int(round(goal_left_top[0])),
            int(round(goal_left_top[1])),
            int(round(goal_left_bottom[0])),
            int(round(goal_left_bottom[1])),
        )
        painter.drawLine(
            int(round(goal_right_top[0])),
            int(round(goal_right_top[1])),
            int(round(goal_right_bottom[0])),
            int(round(goal_right_bottom[1])),
        )

        painter.setPen(pen)
        for x, y, start_angle, span_angle in (
            (0.0, 0.0, 0, 90),
            (0.0, self._TRACKING_PITCH_WIDTH, 270, 90),
            (self._TRACKING_PITCH_LENGTH, 0.0, 90, 90),
            (self._TRACKING_PITCH_LENGTH, self._TRACKING_PITCH_WIDTH, 180, 90),
        ):
            arc_rect = self._tracking_rect(x - 0.9, y - 0.9, 1.8, 1.8, layout)
            painter.drawArc(arc_rect, start_angle * 16, span_angle * 16)

    def _tracking_pitch_coordinates(self, raw_x: float, raw_y: float):
        pitch_x = raw_x + (self._TRACKING_PITCH_LENGTH / 2.0)
        pitch_y = raw_y + (self._TRACKING_PITCH_WIDTH / 2.0)
        pitch_x = max(-1.0, min(self._TRACKING_PITCH_LENGTH + 1.0, pitch_x))
        pitch_y = max(-1.0, min(self._TRACKING_PITCH_WIDTH + 1.0, pitch_y))
        return pitch_x, pitch_y

    def _draw_tracking_players(self, painter: QPainter, players, layout: dict, fill_hex: str):
        fill_color = QColor(fill_hex)
        outline_pen = QPen(QColor("black"))
        outline_pen.setWidthF(max(0.8, layout["scale"] * 0.08))
        painter.setPen(outline_pen)
        painter.setBrush(fill_color)

        radius = max(6.0, layout["scale"] * 1.0)
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(max(7.0, radius * 0.75))
        painter.setFont(font)

        for player in players:
            pitch_x, pitch_y = self._tracking_pitch_coordinates(player["x"], player["y"])
            canvas_x, canvas_y = self._tracking_world_to_canvas(pitch_x, pitch_y, layout)
            painter.drawEllipse(QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2))

            jersey_num = str(player.get("jerseyNum") or "").strip()
            if not jersey_num:
                continue
            painter.setPen(QColor("white"))
            painter.drawText(
                QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2),
                Qt.AlignmentFlag.AlignCenter,
                jersey_num,
            )
            painter.setPen(outline_pen)

    def _draw_tracking_ball(self, painter: QPainter, ball, layout: dict):
        if not isinstance(ball, dict):
            return
        pitch_x, pitch_y = self._tracking_pitch_coordinates(ball["x"], ball["y"])
        canvas_x, canvas_y = self._tracking_world_to_canvas(pitch_x, pitch_y, layout)

        outline_pen = QPen(QColor("black"))
        outline_pen.setWidthF(max(0.8, layout["scale"] * 0.06))
        painter.setPen(outline_pen)
        painter.setBrush(QColor(self._TRACKING_BALL_COLOR))
        radius = max(4.0, layout["scale"] * 0.6)
        painter.drawEllipse(QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2))

    def _draw_tracking_overlay(self, painter: QPainter, frame_index: int):
        frame_time_ms = self._frame_axis_value_for_index(frame_index)
        overlay_text = f"Frame {frame_index + 1}/{self._frame_count}  {frame_time_ms / 1000.0:.2f}s"

        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(overlay_text)
        text_height = metrics.height()

        padding_x = 10
        padding_y = 6
        rect = QRectF(
            16,
            16,
            text_width + (padding_x * 2),
            text_height + (padding_y * 2),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor("white"))
        painter.drawText(
            rect.adjusted(padding_x, padding_y, -padding_x, -padding_y),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            overlay_text,
        )

    def _tracking_frame_image(self, frame_index: int) -> QImage:
        image = QImage(
            self._TRACKING_IMAGE_WIDTH,
            self._TRACKING_IMAGE_HEIGHT,
            QImage.Format.Format_ARGB32,
        )
        image.fill(QColor(self._TRACKING_FIELD_LIGHT))

        frame_payload = {}
        if isinstance(self._frame_data, list) and 0 <= frame_index < len(self._frame_data):
            frame_payload = self._frame_data[frame_index]

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        layout = self._tracking_pitch_layout(image.width(), image.height())
        self._draw_tracking_pitch(painter, layout)
        self._draw_tracking_players(
            painter,
            list(frame_payload.get("home", [])),
            layout,
            self._TRACKING_HOME_COLOR,
        )
        self._draw_tracking_players(
            painter,
            list(frame_payload.get("away", [])),
            layout,
            self._TRACKING_AWAY_COLOR,
        )
        self._draw_tracking_ball(painter, frame_payload.get("ball"), layout)
        self._draw_tracking_overlay(painter, frame_index)
        painter.end()
        return image

    def _frame_image_for_index(self, frame_index: int) -> QImage:
        cached = self._frame_image_cache.get(frame_index)
        if cached is not None:
            return cached

        if self._current_backend == self._BACKEND_FRAMES_NPY:
            image = self._frame_image_from_array_index(frame_index)
        elif self._current_backend == self._BACKEND_TRACKING_PARQUET:
            image = self._tracking_frame_image(frame_index)
        else:
            return QImage()

        self._frame_image_cache[frame_index] = image
        return image

    def _configure_raster_source(
        self,
        source: dict,
        frame_data,
        *,
        frame_count: int,
        time_axis_ms,
        duration_ms: int,
        hold_ms: int,
        fallback_fps: float,
        auto_play: bool,
    ):
        self._current_backend = str(source.get("type") or "")
        self._current_source = source
        self._playback_rate = 1.0
        self._frame_data = frame_data
        self._frame_count = int(frame_count)
        self._frame_fps = self._coerce_source_fps(fallback_fps, self._FRAME_DEFAULT_FPS)
        self._frame_time_axis_ms = [max(0, int(value)) for value in list(time_axis_ms or [])]
        self._frame_hold_ms = max(1, int(hold_ms or 1))
        self._frame_duration_ms = max(0, int(duration_ms))
        if self._frame_count and self._frame_time_axis_ms:
            minimum_duration = self._frame_time_axis_ms[-1] + self._frame_hold_ms
            if self._frame_duration_ms < minimum_duration:
                self._frame_duration_ms = minimum_duration
        self._frame_position_ms = 0
        self._frame_anchor_position_ms = 0
        self._frame_last_rendered_index = -1
        self._frame_last_emitted_position_ms = -1
        self._frame_playing = False
        self._frame_image_cache = {}

        self.durationChanged.emit(self._frame_duration_ms)
        self._set_frame_position(0, emit_position=True, snap_to_frame=True)
        if auto_play:
            self.play()

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

        time_axis_ms, duration_ms, hold_ms = self._build_uniform_frame_timing(
            int(frame_stack.shape[0]),
            self._coerce_source_fps(source.get("fps"), self._FRAME_DEFAULT_FPS),
        )
        self._configure_raster_source(
            source,
            frame_stack,
            frame_count=int(frame_stack.shape[0]),
            time_axis_ms=time_axis_ms,
            duration_ms=duration_ms,
            hold_ms=hold_ms,
            fallback_fps=source.get("fps"),
            auto_play=auto_play,
        )

    def _load_tracking_source(self, source: dict, auto_play: bool):
        if pd is None or pyarrow is None:
            self._trigger_tracking_load_error(
                "Tracking Dependency Missing",
                "Unable to load `tracking_parquet` input",
                "Both `pandas` and `pyarrow` must be installed in the current runtime.",
            )
            return

        source_path = source["path"]
        if not os.path.isfile(source_path):
            self._trigger_tracking_load_error(
                "Media Load Error",
                "Tracking parquet file not found",
                source_path,
            )
            return

        try:
            dataframe = pd.read_parquet(source_path)
        except ImportError as exc:
            self._trigger_tracking_load_error(
                "Tracking Dependency Missing",
                "Unable to read `tracking_parquet` input",
                str(exc),
            )
            return
        except Exception as exc:
            self._trigger_tracking_load_error(
                "Media Load Error",
                "Unable to read tracking parquet",
                str(exc),
            )
            return

        if dataframe is None or getattr(dataframe, "empty", True):
            self._trigger_tracking_load_error(
                "Media Load Error",
                "Tracking parquet contains no frames",
                source_path,
            )
            return

        home_column = self._choose_tracking_column(dataframe, "homePlayers", "homePlayersSmoothed")
        away_column = self._choose_tracking_column(dataframe, "awayPlayers", "awayPlayersSmoothed")
        ball_column = self._choose_tracking_column(dataframe, "balls", "ballsSmoothed")
        if not home_column or not away_column or not ball_column:
            self._trigger_tracking_load_error(
                "Unsupported Tracking Schema",
                "Unsupported `tracking_parquet` payload",
                f"Available columns: {list(dataframe.columns)}",
            )
            return

        frame_payloads = []
        for row in dataframe.to_dict(orient="records"):
            frame_payloads.append(
                {
                    "home": self._parse_tracking_players(row.get(home_column)),
                    "away": self._parse_tracking_players(row.get(away_column)),
                    "ball": self._parse_tracking_ball(row.get(ball_column)),
                }
            )

        fallback_fps = self._coerce_source_fps(source.get("fps"), self._FRAME_DEFAULT_FPS)
        time_axis_ms, duration_ms, hold_ms = self._build_timestamp_frame_timing(
            dataframe.get("videoTimeMs"),
            fallback_fps,
        )
        self._configure_raster_source(
            source,
            frame_payloads,
            frame_count=len(frame_payloads),
            time_axis_ms=time_axis_ms,
            duration_ms=duration_ms,
            hold_ms=hold_ms,
            fallback_fps=fallback_fps,
            auto_play=auto_play,
        )

    def _execute_play(self):
        if self._current_backend != self._BACKEND_VIDEO:
            return
        self._frame_received = False
        self.player.play()
        self.watchdog_timer.start()

    def _set_frame_position(self, position_ms: int, *, emit_position: bool, snap_to_frame: bool = False):
        if self._frame_data is None:
            return

        clamped = max(0, min(int(position_ms), self._frame_duration_ms))
        if snap_to_frame and self._frame_count > 0:
            clamped = self._frame_axis_value_for_index(
                self._frame_index_for_position(clamped, prefer_nearest=True)
            )
        self._frame_position_ms = clamped

        frame_index = self._frame_index_for_position(clamped)
        if frame_index != self._frame_last_rendered_index:
            self._show_frame_image(self._frame_image_for_index(frame_index))
            self._frame_last_rendered_index = frame_index

        if emit_position and clamped != self._frame_last_emitted_position_ms:
            self.positionChanged.emit(clamped)
            self._frame_last_emitted_position_ms = clamped

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

        if normalized_source["type"] == self._BACKEND_TRACKING_PARQUET:
            self._load_tracking_source(normalized_source, auto_play)
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
        if self._is_raster_backend():
            if self._frame_playing and self._frame_clock.isValid():
                next_position = self._frame_anchor_position_ms + int(
                    self._frame_clock.elapsed() * self._playback_rate
                )
                return max(0, min(next_position, self._frame_duration_ms))
            return max(0, int(self._frame_position_ms))
        return max(0, int(self.player.position()))

    def is_playing(self) -> bool:
        if self._is_raster_backend():
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
        if self._is_raster_backend():
            if self._frame_data is None:
                return
            if self._frame_position_ms >= self._frame_duration_ms and self._frame_duration_ms > 0:
                self._set_frame_position(0, emit_position=True, snap_to_frame=True)
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
        if self._is_raster_backend():
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
        self._frame_time_axis_ms = []
        self._frame_hold_ms = int(round(1000.0 / self._FRAME_DEFAULT_FPS))
        self._frame_duration_ms = 0
        self._frame_position_ms = 0
        self._frame_anchor_position_ms = 0
        self._frame_last_rendered_index = -1
        self._frame_last_emitted_position_ms = -1
        self._frame_received = False
        self._frame_image_cache = {}

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
        if self._is_raster_backend():
            self._set_frame_position(target, emit_position=True, snap_to_frame=True)
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
        if self._is_raster_backend():
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

        duration = self._frame_duration_ms if self._is_raster_backend() else self.player.duration()
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
