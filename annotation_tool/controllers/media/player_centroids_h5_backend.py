from __future__ import annotations

import os

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen

from .player_joints_h5_backend import _H5BallFrameSource, PlayerJointsH5MediaBackend
from .raster_backend import RasterClip


class _H5PlayerCentroidsFrameSource:
    def __init__(
        self,
        h5_file,
        datasets: dict,
        frame_groups: list,
        backend,
        ball_source: _H5BallFrameSource | None = None,
    ):
        self._h5_file = h5_file
        self._datasets = datasets
        self._frame_groups = frame_groups
        self._backend = backend
        self._ball_source = ball_source

    def __len__(self):
        return len(self._frame_groups)

    def __getitem__(self, frame_index: int) -> dict:
        group = self._frame_groups[frame_index]
        payload = self._backend._frame_payload_for_row_range(
            self._datasets,
            group.start_row,
            group.stop_row,
            group.timestamp,
        )
        if self._ball_source is not None:
            ball = self._ball_source.ball_for_timestamp(group.timestamp)
            if ball is not None:
                payload["ball"] = ball
        return payload

    def close(self):
        if self._ball_source is not None:
            self._ball_source.close()
        try:
            self._h5_file.close()
        except Exception:
            pass


class PlayerCentroidsH5MediaBackend(PlayerJointsH5MediaBackend):
    backend_type = "player_centroids_h5"

    _CENTROID_REQUIRED_COLUMNS = ("timestamp_utc", "x", "y")
    _CENTROID_MARKER_RADIUS_MIN = 6.0
    _CENTROID_MARKER_RADIUS_SCALE = 1.0

    def build_clip(self, source: dict) -> RasterClip | None:
        h5py_module = self.controller._get_h5py_module()
        if h5py_module is None:
            self.controller._trigger_player_centroids_h5_load_error(
                "H5 Dependency Missing",
                "Unable to load `player_centroids_h5` input",
                "h5py must be installed in the current runtime.",
            )
            return None

        source_path = source["path"]
        if not os.path.isfile(source_path):
            self.controller._trigger_player_centroids_h5_load_error(
                "Media Load Error",
                "H5 file not found",
                source_path,
            )
            return None

        h5_file = None
        try:
            h5_file = h5py_module.File(source_path, "r")
            datasets = self._read_flat_datasets(h5_file)
        except Exception as exc:
            if h5_file is not None:
                h5_file.close()
            self.controller._trigger_player_centroids_h5_load_error(
                "Media Load Error",
                "Unable to read H5 centroid file",
                str(exc),
            )
            return None

        validation_error = self._validate_centroid_datasets(datasets)
        if validation_error:
            h5_file.close()
            self.controller._trigger_player_centroids_h5_load_error(
                "Unsupported H5 Schema",
                "Unsupported `player_centroids_h5` payload",
                validation_error,
            )
            return None

        frame_groups, timing_error = self._build_frame_groups(datasets[self._TIME_COLUMN])
        if timing_error:
            h5_file.close()
            self.controller._trigger_player_centroids_h5_load_error(
                "Unsupported H5 Schema",
                "Unsupported `player_centroids_h5` timing",
                timing_error,
            )
            return None

        if not frame_groups:
            h5_file.close()
            self.controller._trigger_player_centroids_h5_load_error(
                "Media Load Error",
                "H5 centroid file contains no frames",
                source_path,
            )
            return None

        origin = frame_groups[0].timestamp
        time_axis_ms = [
            max(0, int(round((group.timestamp - origin).total_seconds() * 1000.0)))
            for group in frame_groups
        ]
        hold_ms = self._median_frame_delta_ms(time_axis_ms)
        duration_ms = time_axis_ms[-1] + hold_ms if time_axis_ms else 0
        ball_source = self._open_ball_source(source.get("ball_path"), h5py_module, hold_ms)
        frame_source = _H5PlayerCentroidsFrameSource(
            h5_file,
            datasets,
            frame_groups,
            self,
            ball_source,
        )
        return RasterClip(
            frame_source=frame_source,
            frame_count=len(frame_groups),
            time_axis_ms=time_axis_ms,
            hold_ms=hold_ms,
            duration_ms=duration_ms,
            fallback_fps=0.0,
            origin_utc=origin,
        )

    def render_frame_image(self, frame_index: int, frame_payload) -> QImage:
        image = QImage(
            self.controller._TRACKING_IMAGE_WIDTH,
            self.controller._TRACKING_IMAGE_HEIGHT,
            QImage.Format.Format_ARGB32,
        )
        image.fill(QColor(self.controller._TRACKING_FIELD_LIGHT))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        layout = self._tracking_pitch_layout(image.width(), image.height())
        self._draw_tracking_pitch(painter, layout)
        for player in list(frame_payload.get("players", [])):
            self._draw_centroid_player(painter, player, layout)
        self._draw_centroid_ball(painter, frame_payload.get("ball"), layout)
        self._draw_h5_overlay(painter, frame_index, frame_payload)
        painter.end()
        return image

    def _validate_centroid_datasets(self, datasets: dict) -> str:
        validation_error = self._validate_datasets(datasets)
        if validation_error:
            return validation_error
        missing_columns = [column for column in self._CENTROID_REQUIRED_COLUMNS if column not in datasets]
        if missing_columns:
            return f"Missing required centroid H5 columns: {missing_columns}"
        return ""

    def _frame_payload_for_row_range(
        self,
        datasets: dict,
        start_row: int,
        stop_row: int,
        timestamp,
    ) -> dict:
        row_count = max(0, int(stop_row) - int(start_row))
        column_slices = {}
        for column_name in ("x", "y", "is_home", "jersey_number", "role_name", "player_id", "team_id"):
            if column_name in datasets:
                column_slices[column_name] = datasets[column_name][start_row:stop_row]

        players = []
        for row_offset in range(row_count):
            player = self._centroid_player_payload_for_offset(column_slices, row_offset)
            if player is not None:
                players.append(player)
        return {"players": players, "timestamp_utc": timestamp}

    def _centroid_player_payload_for_offset(self, column_slices: dict, row_offset: int):
        x = self._coerce_valid_centroid_float(column_slices["x"][row_offset])
        y = self._coerce_valid_centroid_float(column_slices["y"][row_offset])
        if x is None or y is None:
            return None
        return {
            "x": x,
            "y": y,
            "is_home": self._coerce_int_value(self._slice_value(column_slices.get("is_home"), row_offset)),
            "jersey_number": self._clean_label_value(self._slice_value(column_slices.get("jersey_number"), row_offset)),
            "role_name": self._clean_label_value(self._slice_value(column_slices.get("role_name"), row_offset)),
            "player_id": self._clean_label_value(self._slice_value(column_slices.get("player_id"), row_offset)),
            "team_id": self._clean_label_value(self._slice_value(column_slices.get("team_id"), row_offset)),
        }

    def _draw_centroid_player(self, painter: QPainter, player: dict, layout: dict):
        x = self._coerce_valid_centroid_float(player.get("x"))
        y = self._coerce_valid_centroid_float(player.get("y"))
        if x is None or y is None:
            return

        pitch_x, pitch_y = self._tracking_pitch_coordinates(x, y)
        canvas_x, canvas_y = self._tracking_world_to_canvas(pitch_x, pitch_y, layout)
        fill_color = self._color_for_person(player)
        outline_pen = QPen(QColor("black"))
        outline_pen.setWidthF(max(0.8, layout["scale"] * 0.08))
        painter.setPen(outline_pen)
        painter.setBrush(fill_color)
        radius = max(
            self._CENTROID_MARKER_RADIUS_MIN,
            float(layout.get("scale", 0.0)) * self._CENTROID_MARKER_RADIUS_SCALE,
        )
        painter.drawEllipse(QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2))

        label = player.get("jersey_number") or player.get("role_name") or player.get("player_id")
        if not label:
            return
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(max(7.0, radius * 0.75))
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(
            QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2),
            Qt.AlignmentFlag.AlignCenter,
            str(label)[:4],
        )

    def _draw_centroid_ball(self, painter: QPainter, ball: dict | None, layout: dict):
        if not isinstance(ball, dict):
            return
        x = self._coerce_valid_ball_float(ball.get("x"))
        y = self._coerce_valid_ball_float(ball.get("y"))
        if x is None or y is None:
            return

        pitch_x, pitch_y = self._tracking_pitch_coordinates(x, y)
        canvas_x, canvas_y = self._tracking_world_to_canvas(pitch_x, pitch_y, layout)
        radius = max(4.0, float(layout.get("scale", 0.0)) * 0.6)
        outline_pen = QPen(QColor("#20242A"))
        outline_pen.setWidthF(max(1.0, radius * 0.24))
        painter.setPen(outline_pen)
        painter.setBrush(QColor("#F8F8F2"))
        painter.drawEllipse(QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2))

    @classmethod
    def _coerce_valid_centroid_float(cls, value):
        number = cls._coerce_finite_float(value)
        if number is None:
            return None
        if number == -1.0:
            return None
        return number
