from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from .raster_backend import BaseRasterMediaBackend


class PitchMediaBackend(BaseRasterMediaBackend):
    """Shared pitch renderer for tracking formats; independent of storage."""

    @property
    def pitch_length(self):
        reader = getattr(self._clip.frame_source, "reader", None) if self._clip else None
        return reader.pitch_length_m if reader else self.controller._TRACKING_PITCH_LENGTH

    @property
    def pitch_width(self):
        reader = getattr(self._clip.frame_source, "reader", None) if self._clip else None
        return reader.pitch_width_m if reader else self.controller._TRACKING_PITCH_WIDTH

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

    def _tracking_pitch_layout(self, image_width: int, image_height: int):
        world_width = self.pitch_length + (2 * self.controller._TRACKING_PITCH_PADDING)
        world_height = self.pitch_width + (2 * self.controller._TRACKING_PITCH_PADDING)
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
                self.pitch_length
                + (2 * self.controller._TRACKING_PITCH_PADDING)
            )
            * layout["scale"]
        )
        image_height = int(
            (
                self.pitch_width
                + (2 * self.controller._TRACKING_PITCH_PADDING)
            )
            * layout["scale"]
        )
        painter.fillRect(
            QRectF(layout["origin_x"], layout["origin_y"], image_width, image_height),
            field_light,
        )

        stripe_width = self.pitch_length / 20.0
        for stripe_index in range(20):
            stripe_rect = self._tracking_rect(
                stripe_index * stripe_width,
                0.0,
                stripe_width,
                self.pitch_width,
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
            self.pitch_length,
            self.pitch_width,
            layout,
        )
        painter.drawRect(outer_rect)

        x_mid = self.pitch_length / 2.0
        y_mid = self.pitch_width / 2.0
        x1, y1 = self._tracking_world_to_canvas(x_mid, 0.0, layout)
        x2, y2 = self._tracking_world_to_canvas(x_mid, self.pitch_width, layout)
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

        for x_start in (0.0, self.pitch_length - 16.5):
            painter.drawRect(
                self._tracking_rect(
                    x_start,
                    y_mid - 20.15,
                    16.5,
                    40.3,
                    layout,
                )
            )

        for x_start in (0.0, self.pitch_length - 5.5):
            painter.drawRect(
                self._tracking_rect(
                    x_start,
                    y_mid - 8.5,
                    5.5,
                    17.0,
                    layout,
                )
            )

        for penalty_x in (11.0, self.pitch_length - 11.0):
            dot_x, dot_y = self._tracking_world_to_canvas(penalty_x, y_mid, layout)
            painter.setBrush(line_color)
            painter.drawEllipse(QRectF(dot_x - 3, dot_y - 3, 6, 6))
            painter.setBrush(Qt.BrushStyle.NoBrush)

        left_arc_rect = self._tracking_rect(11.0 - 9.15, y_mid - 9.15, 18.3, 18.3, layout)
        right_arc_rect = self._tracking_rect(
            self.pitch_length - 11.0 - 9.15,
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
        goal_right_top = self._tracking_world_to_canvas(self.pitch_length, y_mid + 3.66, layout)
        goal_right_bottom = self._tracking_world_to_canvas(
            self.pitch_length,
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
            (0.0, self.pitch_width, 270, 90),
            (self.pitch_length, 0.0, 90, 90),
            (
                self.pitch_length,
                self.pitch_width,
                180,
                90,
            ),
        ):
            arc_rect = self._tracking_rect(x - 0.9, y - 0.9, 1.8, 1.8, layout)
            painter.drawArc(arc_rect, start_angle * 16, span_angle * 16)

    def _tracking_pitch_coordinates(self, raw_x: float, raw_y: float):
        pitch_x = raw_x + (self.pitch_length / 2.0)
        pitch_y = raw_y + (self.pitch_width / 2.0)
        pitch_x = max(-1.0, min(self.pitch_length + 1.0, pitch_x))
        pitch_y = max(-1.0, min(self.pitch_width + 1.0, pitch_y))
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
