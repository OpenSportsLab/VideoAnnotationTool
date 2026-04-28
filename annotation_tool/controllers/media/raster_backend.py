from __future__ import annotations

import math
import statistics
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import QElapsedTimer, QTimer
from PyQt6.QtGui import QImage

from .base import BaseMediaBackend


@dataclass
class RasterClip:
    frame_source: Any
    frame_count: int
    time_axis_ms: list[int]
    hold_ms: int
    duration_ms: int
    fallback_fps: float


class BaseRasterMediaBackend(BaseMediaBackend):
    """Shared timer-driven playback runtime for raster-based media sources."""

    def __init__(self, controller):
        super().__init__(controller)
        self._clip: RasterClip | None = None
        self._frame_position_ms = 0
        self._frame_anchor_position_ms = 0
        self._frame_last_rendered_index = -1
        self._frame_last_emitted_position_ms = -1
        self._frame_playing = False
        self._frame_image_cache: dict[int, QImage] = {}
        self._frame_clock = QElapsedTimer()

        self.frame_timer = QTimer(controller)
        self.frame_timer.setInterval(self.controller._FRAME_TIMER_INTERVAL_MS)
        self.frame_timer.timeout.connect(self._advance_frame_playback)

    def load_source(self, source: dict, auto_play: bool) -> bool:
        self.stop()
        clip = self.build_clip(source)
        if clip is None:
            return False

        self._current_source = source
        self._playback_rate = 1.0
        self._clip = clip
        self._frame_position_ms = 0
        self._frame_anchor_position_ms = 0
        self._frame_last_rendered_index = -1
        self._frame_last_emitted_position_ms = -1
        self._frame_playing = False
        self._frame_image_cache = {}

        self.controller.durationChanged.emit(self._clip.duration_ms)
        self._set_frame_position(0, emit_position=True, snap_to_frame=True)
        if auto_play:
            self.play()
        return True

    def build_clip(self, source: dict) -> RasterClip | None:
        raise NotImplementedError

    def render_frame_image(self, frame_index: int, frame_payload) -> QImage:
        raise NotImplementedError

    def play(self):
        if self._clip is None:
            return
        if self._frame_position_ms >= self._clip.duration_ms and self._clip.duration_ms > 0:
            self._set_frame_position(0, emit_position=True, snap_to_frame=True)
        self._frame_anchor_position_ms = self._frame_position_ms
        self._frame_clock.restart()
        self._frame_playing = True
        if not self.frame_timer.isActive():
            self.frame_timer.start()
        self.controller.playbackStateChanged.emit(True)

    def pause(self):
        if not self._frame_playing:
            return
        self._frame_playing = False
        self.frame_timer.stop()
        self._set_frame_position(self.current_position_ms(), emit_position=True)
        self.controller.playbackStateChanged.emit(False)

    def stop(self):
        if self.frame_timer.isActive():
            self.frame_timer.stop()
        self._clip = None
        self._frame_position_ms = 0
        self._frame_anchor_position_ms = 0
        self._frame_last_rendered_index = -1
        self._frame_last_emitted_position_ms = -1
        self._frame_playing = False
        self._frame_image_cache = {}
        super().stop()

    def set_position(self, position_ms: int):
        target = max(0, int(position_ms))
        self._set_frame_position(target, emit_position=True, snap_to_frame=True)
        if self._frame_playing:
            self._frame_anchor_position_ms = self._frame_position_ms
            self._frame_clock.restart()

    def set_playback_rate(self, rate: float):
        super().set_playback_rate(rate)
        if self._frame_playing:
            self._frame_anchor_position_ms = self.current_position_ms()
            self._frame_clock.restart()

    def current_position_ms(self) -> int:
        if self._clip is None:
            return 0
        if self._frame_playing and self._frame_clock.isValid():
            next_position = self._frame_anchor_position_ms + int(
                self._frame_clock.elapsed() * self._playback_rate
            )
            return max(0, min(next_position, self._clip.duration_ms))
        return max(0, int(self._frame_position_ms))

    def duration_ms(self) -> int:
        if self._clip is None:
            return 0
        return max(0, int(self._clip.duration_ms))

    def is_playing(self) -> bool:
        return bool(self._frame_playing)

    @property
    def frame_count(self) -> int:
        return self._clip.frame_count if self._clip is not None else 0

    def _frame_axis_value_for_index(self, frame_index: int) -> int:
        if self._clip is None or not self._clip.time_axis_ms:
            return 0
        clamped_index = max(0, min(frame_index, len(self._clip.time_axis_ms) - 1))
        return int(self._clip.time_axis_ms[clamped_index])

    def _frame_index_for_position(self, position_ms: int, prefer_nearest: bool = False) -> int:
        if self._clip is None or self._clip.frame_count <= 0 or not self._clip.time_axis_ms:
            return 0

        target = max(0, int(position_ms))
        if target >= self._clip.duration_ms:
            return self._clip.frame_count - 1

        if prefer_nearest:
            insertion_idx = bisect_left(self._clip.time_axis_ms, target)
            if insertion_idx <= 0:
                return 0
            if insertion_idx >= self._clip.frame_count:
                return self._clip.frame_count - 1

            prev_time = self._clip.time_axis_ms[insertion_idx - 1]
            next_time = self._clip.time_axis_ms[insertion_idx]
            if abs(next_time - target) < abs(target - prev_time):
                return insertion_idx
            return insertion_idx - 1

        return max(
            0,
            min(
                self._clip.frame_count - 1,
                bisect_right(self._clip.time_axis_ms, target) - 1,
            ),
        )

    def _frame_image_for_index(self, frame_index: int) -> QImage:
        cached = self._frame_image_cache.get(frame_index)
        if cached is not None:
            return cached

        if self._clip is None or not (0 <= frame_index < self._clip.frame_count):
            return QImage()

        image = self.render_frame_image(frame_index, self._clip.frame_source[frame_index])
        self._frame_image_cache[frame_index] = image
        return image

    def _set_frame_position(self, position_ms: int, *, emit_position: bool, snap_to_frame: bool = False):
        if self._clip is None:
            return

        clamped = max(0, min(int(position_ms), self._clip.duration_ms))
        if snap_to_frame and self._clip.frame_count > 0:
            clamped = self._frame_axis_value_for_index(
                self._frame_index_for_position(clamped, prefer_nearest=True)
            )
        self._frame_position_ms = clamped

        frame_index = self._frame_index_for_position(clamped)
        if frame_index != self._frame_last_rendered_index:
            self.controller._show_frame_image(self._frame_image_for_index(frame_index))
            self._frame_last_rendered_index = frame_index

        if emit_position and clamped != self._frame_last_emitted_position_ms:
            self.controller.positionChanged.emit(clamped)
            self._frame_last_emitted_position_ms = clamped

    def _advance_frame_playback(self):
        if not self._frame_playing or self._clip is None:
            return

        next_position = self._frame_anchor_position_ms + int(
            self._frame_clock.elapsed() * self._playback_rate
        )
        if next_position >= self._clip.duration_ms:
            self._set_frame_position(self._clip.duration_ms, emit_position=True)
            self.frame_timer.stop()
            self._frame_playing = False
            self.controller.playbackStateChanged.emit(False)
            return

        self._set_frame_position(next_position, emit_position=True)

    def _build_uniform_frame_timing(self, frame_count: int, fps: float):
        safe_fps = self.controller._coerce_source_fps(fps, self.controller._FRAME_DEFAULT_FPS)
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
            or median_delta > self.controller._TIMESTAMP_MAX_STEP_MS
        ):
            return self._build_uniform_frame_timing(len(raw_values), fallback_fps)

        frame_count = len(raw_values)
        filled = [0.0] * frame_count
        for index, value in known:
            filled[index] = value

        first_known_idx, _first_known_value = known[0]
        last_known_idx, _last_known_value = known[-1]

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

    @staticmethod
    def _coerce_finite_float(value):
        try:
            number = float(value)
        except Exception:
            return None
        if not math.isfinite(number):
            return None
        return number
