from __future__ import annotations

import datetime as _datetime
import math
import os
from bisect import bisect_right
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF

from .raster_backend import RasterClip
from .tracking_parquet_backend import TrackingParquetMediaBackend


@dataclass
class _H5FrameGroup:
    timestamp: _datetime.datetime
    start_row: int
    stop_row: int


class _H5BallFrameSource:
    def __init__(self, h5_file, datasets: dict, timestamp_rows: list[tuple[_datetime.datetime, int]], tolerance_ms: int, backend):
        self._h5_file = h5_file
        self._datasets = datasets
        self._timestamp_rows = timestamp_rows
        self._timestamps = [timestamp for timestamp, _row_index in timestamp_rows]
        self._tolerance = _datetime.timedelta(milliseconds=max(1, int(tolerance_ms)))
        self._backend = backend

    def ball_for_timestamp(self, timestamp: _datetime.datetime):
        row_lookup_index = bisect_right(self._timestamps, timestamp) - 1
        if row_lookup_index < 0:
            return None
        ball_timestamp, row_index = self._timestamp_rows[row_lookup_index]
        if timestamp - ball_timestamp > self._tolerance:
            return None
        x = self._backend._coerce_valid_ball_float(self._datasets["x"][row_index])
        y = self._backend._coerce_valid_ball_float(self._datasets["y"][row_index])
        z = self._backend._coerce_valid_ball_float(self._datasets["z"][row_index])
        if x is None or y is None or z is None:
            return None
        return {"x": x, "y": y, "z": z, "timestamp_utc": ball_timestamp}

    def close(self):
        try:
            self._h5_file.close()
        except Exception:
            pass


class _H5PlayerJointsFrameSource:
    def __init__(
        self,
        h5_file,
        datasets: dict,
        joint_names: list[str],
        frame_groups: list[_H5FrameGroup],
        backend,
        ball_source: _H5BallFrameSource | None = None,
    ):
        self._h5_file = h5_file
        self._datasets = datasets
        self._joint_names = joint_names
        self._frame_groups = frame_groups
        self._backend = backend
        self._ball_source = ball_source

    def __len__(self):
        return len(self._frame_groups)

    def __getitem__(self, frame_index: int) -> dict:
        group = self._frame_groups[frame_index]
        payload = self._backend._frame_payload_for_row_range(
            self._datasets,
            self._joint_names,
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


class PlayerJointsH5MediaBackend(TrackingParquetMediaBackend):
    backend_type = "player_joints_h5"

    _TIME_COLUMN = "timestamp_utc"
    _TIMESTAMP_CHUNK_ROWS = 100000
    _SCENE_MARGIN = 42.0
    _SCENE_Z_SCALE = 1.00
    _SCENE_Z_MAX = 2.4
    _GOAL_WIDTH = 7.32
    _GOAL_HEIGHT = 2.44
    _GOAL_DEPTH = 2.0
    _JOINT_MARKER_RADIUS_MIN = 1.0
    _JOINT_MARKER_RADIUS_SCALE = 0.18
    _BALL_MARKER_RADIUS_MIN = 3.0
    _BALL_MARKER_RADIUS_SCALE = 0.24
    _BALL_TIMING_TOLERANCE_FACTOR = 1.5
    _SKELETON_EDGES = (
        ("l_ear", "l_eye"),
        ("l_eye", "nose"),
        ("nose", "r_eye"),
        ("r_eye", "r_ear"),
        ("l_shoulder", "neck"),
        ("neck", "r_shoulder"),
        ("l_shoulder", "l_elbow"),
        ("l_elbow", "l_wrist"),
        ("l_wrist", "l_thumb"),
        ("l_wrist", "l_pinky"),
        ("r_shoulder", "r_elbow"),
        ("r_elbow", "r_wrist"),
        ("r_wrist", "r_thumb"),
        ("r_wrist", "r_pinky"),
        ("neck", "mid_hip"),
        ("l_hip", "mid_hip"),
        ("mid_hip", "r_hip"),
        ("l_hip", "l_knee"),
        ("l_knee", "l_ankle"),
        ("l_ankle", "l_heel"),
        ("l_ankle", "l_big_toe"),
        ("l_ankle", "l_small_toe"),
        ("r_hip", "r_knee"),
        ("r_knee", "r_ankle"),
        ("r_ankle", "r_heel"),
        ("r_ankle", "r_big_toe"),
        ("r_ankle", "r_small_toe"),
    )

    def build_clip(self, source: dict, progress_callback=None) -> RasterClip | None:
        h5py_module = self.controller._get_h5py_module()
        if h5py_module is None:
            self.controller._trigger_player_joints_h5_load_error(
                "H5 Dependency Missing",
                "Unable to load `player_joints_h5` input",
                "h5py must be installed in the current runtime.",
            )
            return None

        source_path = source["path"]
        if not os.path.isfile(source_path):
            self.controller._trigger_player_joints_h5_load_error(
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
            self.controller._trigger_player_joints_h5_load_error(
                "Media Load Error",
                "Unable to read H5 joint file",
                str(exc),
            )
            return None

        validation_error = self._validate_datasets(datasets)
        if validation_error:
            h5_file.close()
            self.controller._trigger_player_joints_h5_load_error(
                "Unsupported H5 Schema",
                "Unsupported `player_joints_h5` payload",
                validation_error,
            )
            return None

        joint_names = self._detect_joint_names(datasets)
        if not joint_names:
            h5_file.close()
            self.controller._trigger_player_joints_h5_load_error(
                "Unsupported H5 Schema",
                "No usable joint coordinate columns found",
                f"Available columns: {sorted(datasets)}",
            )
            return None

        frame_groups, timing_error = self._build_frame_groups(
            datasets[self._TIME_COLUMN],
            progress_callback=progress_callback,
        )
        if timing_error:
            h5_file.close()
            self.controller._trigger_player_joints_h5_load_error(
                "Unsupported H5 Schema",
                "Unsupported `player_joints_h5` timing",
                timing_error,
            )
            return None

        if not frame_groups:
            h5_file.close()
            self.controller._trigger_player_joints_h5_load_error(
                "Media Load Error",
                "H5 joint file contains no frames",
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
        ball_source = self._open_ball_source(
            source.get("ball_path"),
            h5py_module,
            hold_ms,
            progress_callback=progress_callback,
        )
        frame_source = _H5PlayerJointsFrameSource(
            h5_file,
            datasets,
            joint_names,
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
        image.fill(QColor("#1E252B"))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        layout = self._joint_scene_layout(image.width(), image.height())
        self._draw_joint_scene_ground(painter, layout)
        for person in sorted(list(frame_payload.get("people", [])), key=self._person_scene_depth):
            self._draw_person_skeleton(painter, person, layout)
        self._draw_ball(painter, frame_payload.get("ball"), layout)
        self._draw_h5_overlay(painter, frame_index, frame_payload)
        painter.end()
        return image

    def _read_flat_datasets(self, h5_file) -> dict:
        datasets = {}
        for key in h5_file.keys():
            dataset = h5_file[key]
            if not hasattr(dataset, "shape"):
                continue
            if len(dataset.shape) != 1:
                continue
            datasets[str(key)] = dataset
        return datasets

    def _validate_datasets(self, datasets: dict) -> str:
        if not datasets:
            return "No flat one-dimensional datasets were found."
        if self._TIME_COLUMN not in datasets:
            return f"Missing required `{self._TIME_COLUMN}` column."

        lengths = {name: int(dataset.shape[0]) for name, dataset in datasets.items()}
        unique_lengths = set(lengths.values())
        if len(unique_lengths) != 1:
            return f"Expected equal-length datasets but received lengths: {lengths}"
        if next(iter(unique_lengths), 0) <= 0:
            return "Datasets contain no rows."
        return ""

    def _validate_ball_datasets(self, datasets: dict) -> str:
        required_columns = (self._TIME_COLUMN, "x", "y", "z")
        missing_columns = [column for column in required_columns if column not in datasets]
        if missing_columns:
            return f"Missing required ball H5 columns: {missing_columns}"

        lengths = {name: int(datasets[name].shape[0]) for name in required_columns}
        unique_lengths = set(lengths.values())
        if len(unique_lengths) != 1:
            return f"Expected equal-length ball H5 datasets but received lengths: {lengths}"
        if next(iter(unique_lengths), 0) <= 0:
            return "Ball H5 datasets contain no rows."
        return ""

    def _open_ball_source(
        self,
        ball_path: str | None,
        h5py_module,
        hold_ms: int,
        progress_callback=None,
    ):
        if not ball_path:
            return None
        if not os.path.isfile(ball_path):
            self._log_ball_overlay_warning("Ball H5 file not found", ball_path)
            return None

        ball_file = None
        try:
            ball_file = h5py_module.File(ball_path, "r")
            datasets = self._read_flat_datasets(ball_file)
            validation_error = self._validate_ball_datasets(datasets)
            if validation_error:
                self._log_ball_overlay_warning("Unsupported ball H5 schema", validation_error)
                ball_file.close()
                return None
            timestamp_rows, timing_error = self._scan_ball_timestamp_rows(
                datasets[self._TIME_COLUMN],
                progress_callback=progress_callback,
            )
            if timing_error:
                self._log_ball_overlay_warning("Unsupported ball H5 timing", timing_error)
                ball_file.close()
                return None
            if not timestamp_rows:
                self._log_ball_overlay_warning("Ball H5 contains no usable timestamps", ball_path)
                ball_file.close()
                return None
            tolerance_ms = max(1, int(round(float(hold_ms) * self._BALL_TIMING_TOLERANCE_FACTOR)))
            return _H5BallFrameSource(ball_file, datasets, timestamp_rows, tolerance_ms, self)
        except Exception as exc:
            if ball_file is not None:
                try:
                    ball_file.close()
                except Exception:
                    pass
            self._log_ball_overlay_warning("Unable to read ball H5 file", str(exc))
            return None

    def _scan_ball_timestamp_rows(self, timestamp_dataset, progress_callback=None):
        timestamp_rows = []
        row_count = int(timestamp_dataset.shape[0])
        for chunk_start in range(0, row_count, self._TIMESTAMP_CHUNK_ROWS):
            chunk_stop = min(row_count, chunk_start + self._TIMESTAMP_CHUNK_ROWS)
            if progress_callback is not None:
                progress_callback(chunk_start, row_count, "Scanning ball timestamps…")
            try:
                values = timestamp_dataset[chunk_start:chunk_stop]
            except Exception as exc:
                return [], f"Unable to read `{self._TIME_COLUMN}` values: {exc}"

            for offset, value in enumerate(values):
                row_index = chunk_start + offset
                timestamp = self._parse_utc_timestamp(value)
                if timestamp is not None:
                    timestamp_rows.append((timestamp, row_index))
        if progress_callback is not None:
            progress_callback(row_count, row_count, "Scanning ball timestamps…")
        return sorted(timestamp_rows, key=lambda item: item[0]), ""

    @staticmethod
    def _log_ball_overlay_warning(summary: str, details: str):
        print(f"Skipping ball H5 overlay: {summary}. {details}")

    def _detect_joint_names(self, datasets: dict) -> list[str]:
        names = []
        for key in datasets:
            if not key.endswith("_x"):
                continue
            joint = key[:-2]
            if f"{joint}_y" in datasets:
                names.append(joint)
        return sorted(names)

    def _build_frame_groups(self, timestamp_dataset, progress_callback=None):
        frame_groups = []
        row_count = int(timestamp_dataset.shape[0])
        active_text = None
        active_timestamp = None
        active_start = 0

        for chunk_start in range(0, row_count, self._TIMESTAMP_CHUNK_ROWS):
            chunk_stop = min(row_count, chunk_start + self._TIMESTAMP_CHUNK_ROWS)
            if progress_callback is not None:
                progress_callback(chunk_start, row_count, "Scanning H5 timestamps…")
            try:
                values = timestamp_dataset[chunk_start:chunk_stop]
            except Exception as exc:
                return [], f"Unable to read `{self._TIME_COLUMN}` values: {exc}"

            for offset, value in enumerate(values):
                row_index = chunk_start + offset
                text = self._decode_scalar(value).strip()
                if not text:
                    return [], f"Invalid `{self._TIME_COLUMN}` value at row {row_index}: {text!r}"
                if active_text is None:
                    active_text = text
                    active_timestamp = self._parse_utc_timestamp_text(text)
                    if active_timestamp is None:
                        return [], f"Invalid `{self._TIME_COLUMN}` value at row {row_index}: {text!r}"
                    active_start = row_index
                    continue
                if text == active_text:
                    continue

                frame_groups.append(
                    _H5FrameGroup(
                        timestamp=active_timestamp,
                        start_row=active_start,
                        stop_row=row_index,
                    )
                )
                active_text = text
                active_timestamp = self._parse_utc_timestamp_text(text)
                if active_timestamp is None:
                    return [], f"Invalid `{self._TIME_COLUMN}` value at row {row_index}: {text!r}"
                active_start = row_index

        if active_text is not None and active_timestamp is not None:
            frame_groups.append(
                _H5FrameGroup(
                    timestamp=active_timestamp,
                    start_row=active_start,
                    stop_row=row_count,
                )
            )

        if progress_callback is not None:
            progress_callback(row_count, row_count, "Scanning H5 timestamps…")
        return sorted(frame_groups, key=lambda group: group.timestamp), ""

    def _frame_payload_for_row_range(
        self,
        datasets: dict,
        joint_names: list[str],
        start_row: int,
        stop_row: int,
        timestamp: _datetime.datetime,
    ) -> dict:
        row_count = max(0, int(stop_row) - int(start_row))
        column_slices = {}
        for joint_name in joint_names:
            for axis in ("x", "y", "z"):
                column_name = f"{joint_name}_{axis}"
                if column_name in datasets:
                    column_slices[column_name] = datasets[column_name][start_row:stop_row]
        for column_name in ("is_home", "jersey_number", "role_name", "player_id"):
            if column_name in datasets:
                column_slices[column_name] = datasets[column_name][start_row:stop_row]

        people = []
        for row_offset in range(row_count):
            person = self._person_payload_for_offset(column_slices, joint_names, row_offset)
            if person["joints"]:
                people.append(person)
        return {"people": people, "timestamp_utc": timestamp}

    def _person_payload_for_offset(self, column_slices: dict, joint_names: list[str], row_offset: int) -> dict:
        joints = {}
        for joint_name in joint_names:
            x = self._coerce_finite_float(column_slices[f"{joint_name}_x"][row_offset])
            y = self._coerce_finite_float(column_slices[f"{joint_name}_y"][row_offset])
            if x is None or y is None:
                continue
            joint = {"x": x, "y": y}
            z_column = f"{joint_name}_z"
            if z_column in column_slices:
                z = self._coerce_finite_float(column_slices[z_column][row_offset])
                if z is not None:
                    joint["z"] = z
            joints[joint_name] = joint

        return {
            "joints": joints,
            "is_home": self._coerce_int_value(self._slice_value(column_slices.get("is_home"), row_offset)),
            "jersey_number": self._clean_label_value(self._slice_value(column_slices.get("jersey_number"), row_offset)),
            "role_name": self._clean_label_value(self._slice_value(column_slices.get("role_name"), row_offset)),
            "player_id": self._clean_label_value(self._slice_value(column_slices.get("player_id"), row_offset)),
        }

    def _draw_person_skeleton(self, painter: QPainter, person: dict, layout: dict):
        joints = person.get("joints")
        if not isinstance(joints, dict) or not joints:
            return

        fill_color = self._color_for_person(person)
        line_pen = QPen(fill_color)
        line_pen.setWidthF(max(2.0, layout["scale"] * 0.18))
        painter.setPen(line_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for start, end in self._SKELETON_EDGES:
            if start not in joints or end not in joints:
                continue
            x1, y1 = self._canvas_for_joint(joints[start], layout)
            x2, y2 = self._canvas_for_joint(joints[end], layout)
            painter.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))

        outline_pen = QPen(QColor("black"))
        outline_pen.setWidthF(max(0.8, layout["scale"] * 0.06))
        painter.setPen(outline_pen)
        painter.setBrush(fill_color)
        radius = self._joint_marker_radius(layout)
        for joint in joints.values():
            canvas_x, canvas_y = self._canvas_for_joint(joint, layout)
            painter.drawEllipse(QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2))

        label = person.get("jersey_number") or person.get("role_name") or person.get("player_id")
        anchor = joints.get("neck") or joints.get("mid_hip") or next(iter(joints.values()))
        if label:
            self._draw_person_label(painter, str(label), anchor, layout, fill_color)

    def _joint_marker_radius(self, layout: dict) -> float:
        return max(
            self._JOINT_MARKER_RADIUS_MIN,
            float(layout.get("scale", 0.0)) * self._JOINT_MARKER_RADIUS_SCALE,
        )

    def _canvas_for_joint(self, joint: dict, layout: dict):
        return self._project_joint_scene_point(
            joint["x"],
            joint["y"],
            joint.get("z", 0.0),
            layout,
        )

    def _joint_scene_layout(self, image_width: int, image_height: int) -> dict:
        pitch_length = self.controller._TRACKING_PITCH_LENGTH
        pitch_width = self.controller._TRACKING_PITCH_WIDTH
        corners = (
            (-pitch_length / 2.0, -pitch_width / 2.0, 0.0),
            (pitch_length / 2.0, -pitch_width / 2.0, 0.0),
            (pitch_length / 2.0, pitch_width / 2.0, 0.0),
            (-pitch_length / 2.0, pitch_width / 2.0, 0.0),
            (-pitch_length / 2.0, -pitch_width / 2.0, self._SCENE_Z_MAX),
            (pitch_length / 2.0, pitch_width / 2.0, self._SCENE_Z_MAX),
        )
        projected = [self._scene_basis(x, y, z) for x, y, z in corners]
        min_u = min(point[0] for point in projected)
        max_u = max(point[0] for point in projected)
        min_v = min(point[1] for point in projected)
        max_v = max(point[1] for point in projected)
        scale = min(
            (image_width - (2 * self._SCENE_MARGIN)) / max(1.0, max_u - min_u),
            (image_height - (2 * self._SCENE_MARGIN)) / max(1.0, max_v - min_v),
        )
        return {
            "scale": scale,
            "origin_x": (image_width / 2.0) - (((min_u + max_u) / 2.0) * scale),
            "origin_y": (image_height / 2.0) - (((min_v + max_v) / 2.0) * scale) + 36.0,
        }

    def _scene_basis(self, x: float, y: float, z: float):
        # The H5 field-width axis follows the same direction as the centroid
        # and video modalities. Reflect Y when projecting into the 3D view so
        # positive field-width coordinates remain on the corresponding side.
        u = (x + y) * 0.70710678118
        v = ((x - y) * 0.35355339059) - (max(0.0, self._coerce_finite_float(z) or 0.0) * self._SCENE_Z_SCALE)
        return u, v

    def _project_joint_scene_point(self, x: float, y: float, z: float, layout: dict):
        u, v = self._scene_basis(x, y, z)
        return (
            layout["origin_x"] + (u * layout["scale"]),
            layout["origin_y"] + (v * layout["scale"]),
        )

    def _draw_joint_scene_ground(self, painter: QPainter, layout: dict):
        pitch_length = self.controller._TRACKING_PITCH_LENGTH
        pitch_width = self.controller._TRACKING_PITCH_WIDTH
        corners = [
            self._project_joint_scene_point(-pitch_length / 2.0, -pitch_width / 2.0, 0.0, layout),
            self._project_joint_scene_point(pitch_length / 2.0, -pitch_width / 2.0, 0.0, layout),
            self._project_joint_scene_point(pitch_length / 2.0, pitch_width / 2.0, 0.0, layout),
            self._project_joint_scene_point(-pitch_length / 2.0, pitch_width / 2.0, 0.0, layout),
        ]
        field = QPolygonF([QPointF(x, y) for x, y in corners])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#5C9A3A"))
        painter.drawPolygon(field)

        grid_pen = QPen(QColor(255, 255, 255, 42))
        grid_pen.setWidthF(max(0.6, layout["scale"] * 0.035))
        painter.setPen(grid_pen)
        for x in range(-50, 51, 10):
            x1, y1 = self._project_joint_scene_point(float(x), -pitch_width / 2.0, 0.0, layout)
            x2, y2 = self._project_joint_scene_point(float(x), pitch_width / 2.0, 0.0, layout)
            painter.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))
        for y in range(-30, 31, 10):
            x1, y1 = self._project_joint_scene_point(-pitch_length / 2.0, float(y), 0.0, layout)
            x2, y2 = self._project_joint_scene_point(pitch_length / 2.0, float(y), 0.0, layout)
            painter.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))

        outline_pen = QPen(QColor("white"))
        outline_pen.setWidthF(max(1.6, layout["scale"] * 0.08))
        painter.setPen(outline_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(field)
        self._draw_football_pitch_markings(painter, layout)
        self._draw_3d_goals(painter, layout)

    def _draw_football_pitch_markings(self, painter: QPainter, layout: dict):
        pitch_length = self.controller._TRACKING_PITCH_LENGTH
        pitch_width = self.controller._TRACKING_PITCH_WIDTH
        half_length = pitch_length / 2.0
        half_width = pitch_width / 2.0

        line_pen = QPen(QColor("white"))
        line_pen.setWidthF(max(1.4, layout["scale"] * 0.07))
        painter.setPen(line_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        self._draw_scene_line(painter, (0.0, -half_width, 0.0), (0.0, half_width, 0.0), layout)
        self._draw_scene_ellipse(painter, 0.0, 0.0, 9.15, 9.15, layout)
        self._draw_scene_spot(painter, 0.0, 0.0, layout)

        for sign in (-1.0, 1.0):
            goal_x = sign * half_length
            penalty_inner_x = sign * (half_length - 16.5)
            six_inner_x = sign * (half_length - 5.5)
            penalty_spot_x = sign * (half_length - 11.0)

            self._draw_scene_polyline(
                painter,
                [
                    (goal_x, -20.15, 0.0),
                    (penalty_inner_x, -20.15, 0.0),
                    (penalty_inner_x, 20.15, 0.0),
                    (goal_x, 20.15, 0.0),
                ],
                layout,
            )
            self._draw_scene_polyline(
                painter,
                [
                    (goal_x, -9.16, 0.0),
                    (six_inner_x, -9.16, 0.0),
                    (six_inner_x, 9.16, 0.0),
                    (goal_x, 9.16, 0.0),
                ],
                layout,
            )
            self._draw_scene_spot(painter, penalty_spot_x, 0.0, layout)
            self._draw_penalty_arc(painter, sign, penalty_spot_x, layout)

        for corner_x in (-half_length, half_length):
            for corner_y in (-half_width, half_width):
                self._draw_corner_arc(painter, corner_x, corner_y, layout)

    def _draw_3d_goals(self, painter: QPainter, layout: dict):
        half_length = self.controller._TRACKING_PITCH_LENGTH / 2.0
        half_goal = self._GOAL_WIDTH / 2.0
        goal_pen = QPen(QColor("#F5F5F5"))
        goal_pen.setWidthF(max(2.0, layout["scale"] * 0.12))
        painter.setPen(goal_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for sign in (-1.0, 1.0):
            front_x = sign * half_length
            back_x = sign * (half_length + self._GOAL_DEPTH)
            posts = (
                (front_x, -half_goal, 0.0),
                (front_x, half_goal, 0.0),
                (front_x, -half_goal, self._GOAL_HEIGHT),
                (front_x, half_goal, self._GOAL_HEIGHT),
                (back_x, -half_goal, 0.0),
                (back_x, half_goal, 0.0),
                (back_x, -half_goal, self._GOAL_HEIGHT),
                (back_x, half_goal, self._GOAL_HEIGHT),
            )
            edges = (
                (0, 2),
                (1, 3),
                (2, 3),
                (0, 4),
                (1, 5),
                (2, 6),
                (3, 7),
                (4, 6),
                (5, 7),
                (6, 7),
            )
            for start_idx, end_idx in edges:
                self._draw_scene_line(painter, posts[start_idx], posts[end_idx], layout)

    def _draw_scene_line(self, painter: QPainter, start: tuple, end: tuple, layout: dict):
        x1, y1 = self._project_joint_scene_point(start[0], start[1], start[2], layout)
        x2, y2 = self._project_joint_scene_point(end[0], end[1], end[2], layout)
        painter.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))

    def _draw_scene_polyline(self, painter: QPainter, points: list[tuple], layout: dict):
        if len(points) < 2:
            return
        for start, end in zip(points, points[1:]):
            self._draw_scene_line(painter, start, end, layout)

    def _draw_scene_ellipse(self, painter: QPainter, center_x: float, center_y: float, radius_x: float, radius_y: float, layout: dict):
        points = []
        for step in range(73):
            angle = (math.tau * step) / 72.0
            x = center_x + (math.cos(angle) * radius_x)
            y = center_y + (math.sin(angle) * radius_y)
            points.append((x, y, 0.0))
        self._draw_scene_polyline(painter, points, layout)

    def _draw_scene_spot(self, painter: QPainter, x: float, y: float, layout: dict):
        canvas_x, canvas_y = self._project_joint_scene_point(x, y, 0.0, layout)
        radius = max(2.0, layout["scale"] * 0.12)
        painter.setBrush(QColor("white"))
        painter.drawEllipse(QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_penalty_arc(self, painter: QPainter, sign: float, center_x: float, layout: dict):
        points = []
        for step in range(49):
            angle = -math.pi / 2.0 + (math.pi * step / 48.0)
            x = center_x - (sign * math.cos(angle) * 9.15)
            y = math.sin(angle) * 9.15
            if (sign < 0 and x > center_x) or (sign > 0 and x < center_x):
                points.append((x, y, 0.0))
        self._draw_scene_polyline(painter, points, layout)

    def _draw_corner_arc(self, painter: QPainter, corner_x: float, corner_y: float, layout: dict):
        points = []
        for step in range(19):
            theta = (math.pi / 2.0) * step / 18.0
            x = corner_x + (-math.copysign(math.cos(theta), corner_x) * 1.0)
            y = corner_y + (-math.copysign(math.sin(theta), corner_y) * 1.0)
            points.append((x, y, 0.0))
        self._draw_scene_polyline(painter, points, layout)

    def _person_scene_depth(self, person: dict):
        joints = person.get("joints")
        if not isinstance(joints, dict) or not joints:
            return 0.0
        anchor = joints.get("mid_hip") or joints.get("neck") or next(iter(joints.values()))
        return float(anchor.get("x", 0.0)) + float(anchor.get("y", 0.0))

    def _draw_person_label(self, painter: QPainter, label: str, anchor: dict, layout: dict, fill_color: QColor):
        canvas_x, canvas_y = self._canvas_for_joint(anchor, layout)
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(max(7.0, layout["scale"] * 0.7))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text = label[:12]
        text_width = metrics.horizontalAdvance(text)
        text_height = metrics.height()
        rect = QRectF(canvas_x - (text_width / 2.0) - 4, canvas_y - 24, text_width + 8, text_height + 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(fill_color.lighter(180))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_ball(self, painter: QPainter, ball: dict | None, layout: dict):
        if not isinstance(ball, dict):
            return
        x = self._coerce_valid_ball_float(ball.get("x"))
        y = self._coerce_valid_ball_float(ball.get("y"))
        z = self._coerce_valid_ball_float(ball.get("z"))
        if x is None or y is None or z is None:
            return

        canvas_x, canvas_y = self._project_joint_scene_point(x, y, z, layout)
        radius = max(
            self._BALL_MARKER_RADIUS_MIN,
            float(layout.get("scale", 0.0)) * self._BALL_MARKER_RADIUS_SCALE,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawEllipse(QRectF(canvas_x - radius + 1.5, canvas_y - radius + 1.5, radius * 2, radius * 2))
        outline_pen = QPen(QColor("#20242A"))
        outline_pen.setWidthF(max(1.0, radius * 0.24))
        painter.setPen(outline_pen)
        painter.setBrush(QColor("#F8F8F2"))
        painter.drawEllipse(QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2))

    def _draw_h5_overlay(self, painter: QPainter, frame_index: int, frame_payload: dict):
        timestamp = frame_payload.get("timestamp_utc")
        timestamp_text = timestamp.isoformat(sep=" ") if hasattr(timestamp, "isoformat") else ""
        frame_time_ms = self._frame_axis_value_for_index(frame_index)
        overlay_text = f"Frame {frame_index + 1}/{self.frame_count}  {frame_time_ms / 1000.0:.2f}s"
        if timestamp_text:
            overlay_text = f"{overlay_text}  {timestamp_text} UTC"

        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(overlay_text)
        text_height = metrics.height()
        rect = QRectF(16, 16, text_width + 20, text_height + 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor("white"))
        painter.drawText(
            rect.adjusted(10, 6, -10, -6),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            overlay_text,
        )

    def _color_for_person(self, person: dict) -> QColor:
        is_home = person.get("is_home")
        if is_home == 1:
            return QColor(self.controller._TRACKING_HOME_COLOR)
        if is_home == 0:
            return QColor(self.controller._TRACKING_AWAY_COLOR)
        return QColor("#F2C94C")

    def _median_frame_delta_ms(self, time_axis_ms: list[int]) -> int:
        deltas = [
            next_value - prev_value
            for prev_value, next_value in zip(time_axis_ms, time_axis_ms[1:])
            if next_value > prev_value
        ]
        if not deltas:
            return 1
        deltas = sorted(deltas)
        middle = len(deltas) // 2
        if len(deltas) % 2:
            return max(1, int(round(deltas[middle])))
        return max(1, int(round((deltas[middle - 1] + deltas[middle]) / 2.0)))

    def _parse_utc_timestamp(self, value):
        return self._parse_utc_timestamp_text(self._decode_scalar(value).strip())

    def _parse_utc_timestamp_text(self, text: str):
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = _datetime.datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = _datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                try:
                    parsed = _datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(_datetime.timezone.utc).replace(tzinfo=None)
        return parsed

    def _clean_label_value(self, value) -> str:
        text = self._decode_scalar(value).strip()
        if text.lower() in {"", "none", "null", "nan", "-1"}:
            return ""
        return text

    @staticmethod
    def _slice_value(values, row_offset: int):
        if values is None:
            return None
        return values[row_offset]

    @staticmethod
    def _coerce_int_value(value):
        if value is None:
            return None
        try:
            value = int(value)
        except Exception:
            return None
        return value

    @staticmethod
    def _decode_scalar(value) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        return str(value)

    @staticmethod
    def _coerce_finite_float(value):
        try:
            number = float(value)
        except Exception:
            return None
        if not math.isfinite(number):
            return None
        return number

    @classmethod
    def _coerce_valid_ball_float(cls, value):
        number = cls._coerce_finite_float(value)
        if number is None:
            return None
        if number == -1.0:
            return None
        return number
