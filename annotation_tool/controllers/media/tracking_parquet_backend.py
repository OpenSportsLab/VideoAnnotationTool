from __future__ import annotations

import json
import os

from .raster_backend import RasterClip
from .pitch_backend import PitchMediaBackend


class TrackingParquetMediaBackend(PitchMediaBackend):
    backend_type = "tracking_parquet"

    def build_clip(self, source: dict, progress_callback=None) -> RasterClip | None:
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
        rows = dataframe.to_dict(orient="records")
        total_rows = len(rows)
        progress_step = max(1, total_rows // 100)
        for row_index, row in enumerate(rows):
            if progress_callback is not None and row_index % progress_step == 0:
                progress_callback(row_index, total_rows, "Preparing tracking frames…")
            frame_payloads.append(
                {
                    "home": self._parse_tracking_players(row.get(home_column)),
                    "away": self._parse_tracking_players(row.get(away_column)),
                    "ball": self._parse_tracking_ball(row.get(ball_column)),
                }
            )
        if progress_callback is not None:
            progress_callback(total_rows, total_rows, "Preparing tracking frames…")

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
