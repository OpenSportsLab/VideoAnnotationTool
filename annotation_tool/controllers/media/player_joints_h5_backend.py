from __future__ import annotations

import datetime as _datetime
import math
import os
from dataclasses import dataclass

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication

from .raster_backend import RasterClip
from .tracking_parquet_backend import TrackingParquetMediaBackend


@dataclass
class _H5FrameGroup:
    timestamp: _datetime.datetime
    start_row: int
    stop_row: int


class _H5PlayerJointsFrameSource:
    def __init__(self, h5_file, datasets: dict, joint_names: list[str], frame_groups: list[_H5FrameGroup], backend):
        self._h5_file = h5_file
        self._datasets = datasets
        self._joint_names = joint_names
        self._frame_groups = frame_groups
        self._backend = backend

    def __len__(self):
        return len(self._frame_groups)

    def __getitem__(self, frame_index: int) -> dict:
        group = self._frame_groups[frame_index]
        return self._backend._frame_payload_for_row_range(
            self._datasets,
            self._joint_names,
            group.start_row,
            group.stop_row,
            group.timestamp,
        )

    def close(self):
        try:
            self._h5_file.close()
        except Exception:
            pass


class PlayerJointsH5MediaBackend(TrackingParquetMediaBackend):
    backend_type = "player_joints_h5"

    _TIME_COLUMN = "timestamp_utc"
    _TIMESTAMP_CHUNK_ROWS = 100000
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

    def build_clip(self, source: dict) -> RasterClip | None:
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

        frame_groups, timing_error = self._build_frame_groups(datasets[self._TIME_COLUMN])
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
        frame_source = _H5PlayerJointsFrameSource(h5_file, datasets, joint_names, frame_groups, self)
        return RasterClip(
            frame_source=frame_source,
            frame_count=len(frame_groups),
            time_axis_ms=time_axis_ms,
            hold_ms=hold_ms,
            duration_ms=duration_ms,
            fallback_fps=0.0,
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
        for person in list(frame_payload.get("people", [])):
            self._draw_person_skeleton(painter, person, layout)
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

    def _detect_joint_names(self, datasets: dict) -> list[str]:
        names = []
        for key in datasets:
            if not key.endswith("_x"):
                continue
            joint = key[:-2]
            if f"{joint}_y" in datasets:
                names.append(joint)
        return sorted(names)

    def _build_frame_groups(self, timestamp_dataset):
        frame_groups = []
        row_count = int(timestamp_dataset.shape[0])
        active_text = None
        active_timestamp = None
        active_start = 0

        for chunk_start in range(0, row_count, self._TIMESTAMP_CHUNK_ROWS):
            chunk_stop = min(row_count, chunk_start + self._TIMESTAMP_CHUNK_ROWS)
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
            self._process_pending_ui_events()

        if active_text is not None and active_timestamp is not None:
            frame_groups.append(
                _H5FrameGroup(
                    timestamp=active_timestamp,
                    start_row=active_start,
                    stop_row=row_count,
                )
            )

        return sorted(frame_groups, key=lambda group: group.timestamp), ""

    @staticmethod
    def _process_pending_ui_events():
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

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
        line_pen.setWidthF(max(1.5, layout["scale"] * 0.12))
        painter.setPen(line_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for start, end in self._SKELETON_EDGES:
            if start not in joints or end not in joints:
                continue
            x1, y1 = self._canvas_for_joint(joints[start], layout)
            x2, y2 = self._canvas_for_joint(joints[end], layout)
            painter.drawLine(int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))

        outline_pen = QPen(QColor("black"))
        outline_pen.setWidthF(max(0.6, layout["scale"] * 0.05))
        painter.setPen(outline_pen)
        painter.setBrush(fill_color)
        radius = max(2.5, layout["scale"] * 0.34)
        for joint in joints.values():
            canvas_x, canvas_y = self._canvas_for_joint(joint, layout)
            painter.drawEllipse(QRectF(canvas_x - radius, canvas_y - radius, radius * 2, radius * 2))

        label = person.get("jersey_number") or person.get("role_name") or person.get("player_id")
        anchor = joints.get("neck") or joints.get("mid_hip") or next(iter(joints.values()))
        if label:
            self._draw_person_label(painter, str(label), anchor, layout, fill_color)

    def _canvas_for_joint(self, joint: dict, layout: dict):
        pitch_x, pitch_y = self._tracking_pitch_coordinates(joint["x"], joint["y"])
        return self._tracking_world_to_canvas(pitch_x, pitch_y, layout)

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
