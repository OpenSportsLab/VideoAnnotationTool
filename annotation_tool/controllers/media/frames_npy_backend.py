from __future__ import annotations

import os

from PyQt6.QtGui import QImage

from .raster_backend import BaseRasterMediaBackend, RasterClip


class FramesNpyMediaBackend(BaseRasterMediaBackend):
    backend_type = "frames_npy"

    def build_clip(self, source: dict) -> RasterClip | None:
        numpy_module = self.controller._get_numpy_module()
        if numpy_module is None:
            self.controller._trigger_frame_load_error(
                "NumPy Dependency Missing",
                "Unable to load `frames_npy` input",
                "NumPy is not installed in the current runtime.",
            )
            return None

        source_path = source["path"]
        if not os.path.isfile(source_path):
            self.controller._trigger_frame_load_error(
                "Media Load Error",
                "Frame stack file not found",
                source_path,
            )
            return None

        try:
            frame_stack = numpy_module.load(source_path, mmap_mode="r")
        except Exception as exc:
            self.controller._trigger_frame_load_error(
                "Media Load Error",
                "Unable to read frame stack",
                str(exc),
            )
            return None

        validation_error = self._validate_frame_stack(frame_stack, numpy_module)
        if validation_error:
            self.controller._trigger_frame_load_error(
                "Invalid Frame Stack",
                "Unsupported `frames_npy` payload",
                validation_error,
            )
            return None

        fallback_fps = self.controller._coerce_source_fps(
            source.get("fps"),
            self.controller._FRAME_DEFAULT_FPS,
        )
        time_axis_ms, duration_ms, hold_ms = self._build_uniform_frame_timing(
            int(frame_stack.shape[0]),
            fallback_fps,
        )
        return RasterClip(
            frame_source=frame_stack,
            frame_count=int(frame_stack.shape[0]),
            time_axis_ms=[max(0, int(value)) for value in list(time_axis_ms or [])],
            hold_ms=max(1, int(hold_ms or 1)),
            duration_ms=max(0, int(duration_ms)),
            fallback_fps=fallback_fps,
        )

    def render_frame_image(self, frame_index: int, frame_payload) -> QImage:
        numpy_module = self.controller._get_numpy_module()
        frame = frame_payload
        if numpy_module is not None and not frame.flags["C_CONTIGUOUS"]:
            frame = numpy_module.ascontiguousarray(frame)

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
    def _validate_frame_stack(frame_stack, numpy_module) -> str:
        if frame_stack is None:
            return "The frame stack could not be loaded."
        if getattr(frame_stack, "dtype", None) != numpy_module.uint8:
            return f"Expected dtype uint8 but received {getattr(frame_stack, 'dtype', None)}."
        if getattr(frame_stack, "ndim", None) != 4:
            return f"Expected a 4D array but received ndim={getattr(frame_stack, 'ndim', None)}."
        if frame_stack.shape[0] <= 0:
            return "The frame stack contains no frames."
        if frame_stack.shape[-1] not in (3, 4):
            return f"Expected 3 or 4 channels per frame but received shape {frame_stack.shape}."
        return ""
