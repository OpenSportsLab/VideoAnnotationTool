"""Raw TRACAB playback using OpenSportsLib's calibrated, indexed reader."""
from .pitch_backend import PitchMediaBackend
from .raster_backend import RasterClip


class _TracabFrames:
    def __init__(self, reader):
        self.reader = reader

    def __len__(self):
        return len(self.reader)

    def __getitem__(self, index):
        row = self.reader[index]
        return {"home": row["homePlayers"], "away": row["awayPlayers"],
                "ball": next(iter(row["balls"]), None)}

    def close(self):
        self.reader.close()


class TracabTrackingMediaBackend(PitchMediaBackend):
    backend_type = "tracking_tracab"

    def _report_error(self, title, details):
        self.controller._trigger_error_dialog(
            details, title=title, text="<b>Unable to read TRACAB DAT</b>",
            informative_text=(
                "Check the TRACAB DAT and metadata_path files, UTC origin, duration, "
                "team codes and calibrated periods in the JSON input."
            ),
        )

    def build_clip(self, source, progress_callback=None):
        try:
            from opensportslib.tracking import TracabTrackingReader
        except ImportError as exc:
            self._report_error(
                "Tracking Dependency Missing",
                "Install the OpenSportsLib checkout with native TRACAB support. " + str(exc),
            )
            return None
        try:
            reader = TracabTrackingReader(source["path"], source, progress_callback)
        except (OSError, ValueError, KeyError) as exc:
            self._report_error("Media Load Error", str(exc))
            return None
        return RasterClip(
            frame_source=_TracabFrames(reader), frame_count=len(reader),
            time_axis_ms=reader.time_axis_ms, hold_ms=max(1, round(reader.interval_ms)),
            duration_ms=reader.duration_ms, fallback_fps=reader.fps,
            origin_utc=reader.origin_utc.replace(tzinfo=None),
        )
