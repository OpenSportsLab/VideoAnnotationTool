from __future__ import annotations

import json
import os

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen

from .raster_backend import BaseRasterMediaBackend, RasterClip


class TrackingParquetMediaBackend(BaseRasterMediaBackend):
    backend_type = "tracking_parquet"

    def build_clip(self, source: dict) -> RasterClip | None:
        pandas_module = self.controller._get_pandas_module()
        pyarrow_module = self.controller._get_pyarrow_module()
        if pandas_module is None or pyarrow_module is None:
            self.controller._trigger_tracking_load_error(
                "Tracking Dependency Missing",
                "Unable to load `tracking_parquet` input",
                "Both `pandas` and `pyarrow` must be installed in the current runtime.",
            )
            return None

        source_path = source["path"]
        if not os.path.isfile(source_path):
            self.controller._trigger_tracking_load_error(
                "Media Load Error",
                "Tracking parquet file not found",
                source_path,
            )
            return None

        try:
            dataframe = pandas_module.read_parquet(source_path)
        except ImportError as exc:
            self.controller._trigger_tracking_load_error(
                "Tracking Dependency Missing",
                "Unable to read `tracking_parquet` input",
                str(exc),
            )
            return None
        except Exception as exc:
            self.controller._trigger_tracking_load_error(
                "Media Load Error",
                "Unable to read tracking parquet",
                str(exc),
            )
            return None

        if dataframe is None or getattr(dataframe, "empty", True):
            self.controller._trigger_tracking_load_error(
                "Media Load Error",
                "Tracking parquet contains no frames",
                source_path,
            )
            return None

        home_column = self._choose_tracking_column(dataframe, "homePlayers", "homePlayersSmoothed")
        away_column = self._choose_tracking_column(dataframe, "awayPlayers", "awayPlayersSmoothed")
        ball_column = self._choose_tracking_column(dataframe, "balls", "ballsSmoothed")
        if not home_column or not away_column or not ball_column:
            self.controller._trigger_tracking_load_error(
                "Unsupported Tracking Schema",
                "Unsupported `tracking_parquet` payload",
                f"Available columns: {list(dataframe.columns)}",
            )
            return None

        frame_payloads = []
        for row in dataframe.to_dict(orient="records"):
            frame_payloads.append(
                {
                    "home": self._parse_tracking_players(row.get(home_column)),
                    "away": self._parse_tracking_players(row.get(away_column)),
                    "ball": self._parse_tracking_ball(row.get(ball_column)),
                }
            )

        fallback_fps = self.controller._coerce_source_fps(
            source.get("fps"),
            self.controller._FRAME_DEFAULT_FPS,
        )
        timestamp_values = dataframe.get("videoTimeMs")
        if timestamp_values is None:
            time_axis_ms, duration_ms, hold_ms = self._build_uniform_frame_timing(
                len(frame_payloads),
                fallback_fps,
            )
        else:
            time_axis_ms, duration_ms, hold_ms = self._build_timestamp_frame_timing(
                timestamp_values,
                fallback_fps,
            )
        return RasterClip(
            frame_source=frame_payloads,
            frame_count=len(frame_payloads),
            time_axis_ms=[max(0, int(value)) for value in list(time_axis_ms or [])],
            hold_ms=max(1, int(hold_ms or 1)),
            duration_ms=max(0, int(duration_ms)),
            fallback_fps=fallback_fps,
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
        self._draw_tracking_players(
            painter,
            list(frame_payload.get("home", [])),
            layout,
            self.controller._TRACKING_HOME_COLOR,
        )
        self._draw_tracking_players(
            painter,
            list(frame_payload.get("away", [])),
            layout,
            self.controller._TRACKING_AWAY_COLOR,
        )
        self._draw_tracking_ball(painter, frame_payload.get("ball"), layout)
        self._draw_tracking_overlay(painter, frame_index)
        painter.end()
        return image

    def _is_nullish_tracking_cell(self, value) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip().lower() in {"", "none", "null", "nan"}
        if isinstance(value, (list, dict, tuple)):
            return False
        pandas_module = self.controller._get_pandas_module()
        if pandas_module is not None:
            try:
                return bool(pandas_module.isna(value))
            except Exception:
                pass
        try:
            return bool(value != value)
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
        world_width = self.controller._TRACKING_PITCH_LENGTH + (2 * self.controller._TRACKING_PITCH_PADDING)
        world_height = self.controller._TRACKING_PITCH_WIDTH + (2 * self.controller._TRACKING_PITCH_PADDING)
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
        px = origin_x + ((x + self.controller._TRACKING_PITCH_PADDING) * scale)
        py = origin_y + ((world_height - (y + self.controller._TRACKING_PITCH_PADDING)) * scale)
        return px, py

    def _tracking_rect(self, x: float, y: float, width: float, height: float, layout: dict) -> QRectF:
        left, top = self._tracking_world_to_canvas(x, y + height, layout)
        right, bottom = self._tracking_world_to_canvas(x + width, y, layout)
        return QRectF(left, top, right - left, bottom - top)

    def _draw_tracking_pitch(self, painter: QPainter, layout: dict):
        field_light = QColor(self.controller._TRACKING_FIELD_LIGHT)
        field_dark = QColor(self.controller._TRACKING_FIELD_DARK)
        line_color = QColor("white")
        line_width = max(2.0, layout["scale"] * 0.18)

        image_width = int(
            (
                self.controller._TRACKING_PITCH_LENGTH
                + (2 * self.controller._TRACKING_PITCH_PADDING)
            )
            * layout["scale"]
        )
        image_height = int(
            (
                self.controller._TRACKING_PITCH_WIDTH
                + (2 * self.controller._TRACKING_PITCH_PADDING)
            )
            * layout["scale"]
        )
        painter.fillRect(
            QRectF(layout["origin_x"], layout["origin_y"], image_width, image_height),
            field_light,
        )

        stripe_width = self.controller._TRACKING_PITCH_LENGTH / 20.0
        for stripe_index in range(20):
            stripe_rect = self._tracking_rect(
                stripe_index * stripe_width,
                0.0,
                stripe_width,
                self.controller._TRACKING_PITCH_WIDTH,
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
            self.controller._TRACKING_PITCH_LENGTH,
            self.controller._TRACKING_PITCH_WIDTH,
            layout,
        )
        painter.drawRect(outer_rect)

        x_mid = self.controller._TRACKING_PITCH_LENGTH / 2.0
        y_mid = self.controller._TRACKING_PITCH_WIDTH / 2.0
        x1, y1 = self._tracking_world_to_canvas(x_mid, 0.0, layout)
        x2, y2 = self._tracking_world_to_canvas(x_mid, self.controller._TRACKING_PITCH_WIDTH, layout)
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

        for x_start in (0.0, self.controller._TRACKING_PITCH_LENGTH - 16.5):
            painter.drawRect(
                self._tracking_rect(
                    x_start,
                    y_mid - 20.15,
                    16.5,
                    40.3,
                    layout,
                )
            )

        for x_start in (0.0, self.controller._TRACKING_PITCH_LENGTH - 5.5):
            painter.drawRect(
                self._tracking_rect(
                    x_start,
                    y_mid - 8.5,
                    5.5,
                    17.0,
                    layout,
                )
            )

        for penalty_x in (11.0, self.controller._TRACKING_PITCH_LENGTH - 11.0):
            dot_x, dot_y = self._tracking_world_to_canvas(penalty_x, y_mid, layout)
            painter.setBrush(line_color)
            painter.drawEllipse(QRectF(dot_x - 3, dot_y - 3, 6, 6))
            painter.setBrush(Qt.BrushStyle.NoBrush)

        left_arc_rect = self._tracking_rect(11.0 - 9.15, y_mid - 9.15, 18.3, 18.3, layout)
        right_arc_rect = self._tracking_rect(
            self.controller._TRACKING_PITCH_LENGTH - 11.0 - 9.15,
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
        goal_right_top = self._tracking_world_to_canvas(self.controller._TRACKING_PITCH_LENGTH, y_mid + 3.66, layout)
        goal_right_bottom = self._tracking_world_to_canvas(
            self.controller._TRACKING_PITCH_LENGTH,
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
            (0.0, self.controller._TRACKING_PITCH_WIDTH, 270, 90),
            (self.controller._TRACKING_PITCH_LENGTH, 0.0, 90, 90),
            (
                self.controller._TRACKING_PITCH_LENGTH,
                self.controller._TRACKING_PITCH_WIDTH,
                180,
                90,
            ),
        ):
            arc_rect = self._tracking_rect(x - 0.9, y - 0.9, 1.8, 1.8, layout)
            painter.drawArc(arc_rect, start_angle * 16, span_angle * 16)

    def _tracking_pitch_coordinates(self, raw_x: float, raw_y: float):
        pitch_x = raw_x + (self.controller._TRACKING_PITCH_LENGTH / 2.0)
        pitch_y = raw_y + (self.controller._TRACKING_PITCH_WIDTH / 2.0)
        pitch_x = max(-1.0, min(self.controller._TRACKING_PITCH_LENGTH + 1.0, pitch_x))
        pitch_y = max(-1.0, min(self.controller._TRACKING_PITCH_WIDTH + 1.0, pitch_y))
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
        painter.setBrush(QColor(self.controller._TRACKING_BALL_COLOR))
        radius = max(4.0, layout["scale"] * 0.6)
        painter.drawEllipse(QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2))

    def _draw_tracking_overlay(self, painter: QPainter, frame_index: int):
        frame_time_ms = self._frame_axis_value_for_index(frame_index)
        overlay_text = f"Frame {frame_index + 1}/{self.frame_count}  {frame_time_ms / 1000.0:.2f}s"

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
