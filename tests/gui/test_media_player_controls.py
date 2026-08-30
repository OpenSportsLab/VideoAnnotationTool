import time
import threading
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QMessageBox

from controllers.media_controller import MediaController
from controllers.media.raster_backend import BaseRasterMediaBackend, RasterClip
from ui.media_player import MediaCenterPanel, MediaViewerPane, ViewerLayoutMode


FRAME_STACK_PATH = (
    Path(__file__).resolve().parents[2]
    / "test_data"
    / "sn-gar"
    / "sngar-frames"
    / "train"
    / "clip_000000.npy"
)
TRACKING_PARQUET_PATH = (
    Path(__file__).resolve().parents[2]
    / "test_data"
    / "sngar-tracking"
    / "test"
    / "clip_000000.parquet"
)
PLAYER_JOINTS_H5_PATH = (
    Path(__file__).resolve().parents[2]
    / "test_data"
    / "live_joints_sirus_mini_test.h5"
)

# FRAME_STACK_PATH/TRACKING_PARQUET_PATH are real files someone created
# locally; test_data/ is gitignored except for a small whitelist that
# doesn't include them (see .gitignore), so they only exist on machines that
# made them by hand. The two tests that load them directly (without mocking
# the error dialog) would otherwise hang forever on a real, unmocked
# QMessageBox popped by the "file not found"/"invalid" load path.
_frame_stack_missing = pytest.mark.skipif(
    not FRAME_STACK_PATH.exists(),
    reason=f"local-only fixture not present: {FRAME_STACK_PATH}",
)
_tracking_parquet_missing = pytest.mark.skipif(
    not TRACKING_PARQUET_PATH.exists(),
    reason=f"local-only fixture not present: {TRACKING_PARQUET_PATH}",
)


def _write_minimal_player_joints_h5(path: Path, timestamps: list[bytes]):
    row_count = len(timestamps)
    with h5py.File(path, "w") as h5_file:
        h5_file.create_dataset("timestamp_utc", data=np.array(timestamps))
        h5_file.create_dataset("neck_x", data=np.linspace(0.0, 1.0, row_count))
        h5_file.create_dataset("neck_y", data=np.linspace(0.0, 1.0, row_count))
        h5_file.create_dataset("neck_z", data=np.linspace(1.4, 1.5, row_count))


def _write_ball_h5(path: Path, timestamps: list[bytes], x_values, y_values=None, z_values=None):
    row_count = len(timestamps)
    if y_values is None:
        y_values = np.zeros(row_count)
    if z_values is None:
        z_values = np.full(row_count, 0.12)
    with h5py.File(path, "w") as h5_file:
        h5_file.create_dataset("timestamp_utc", data=np.array(timestamps))
        h5_file.create_dataset("x", data=np.array(x_values, dtype=float))
        h5_file.create_dataset("y", data=np.array(y_values, dtype=float))
        h5_file.create_dataset("z", data=np.array(z_values, dtype=float))


def _write_minimal_player_centroids_h5(path: Path, timestamps: list[bytes], x_values=None, y_values=None):
    row_count = len(timestamps)
    if x_values is None:
        x_values = np.linspace(0.0, 1.0, row_count)
    if y_values is None:
        y_values = np.linspace(0.0, 1.0, row_count)
    with h5py.File(path, "w") as h5_file:
        h5_file.create_dataset("timestamp_utc", data=np.array(timestamps))
        h5_file.create_dataset("x", data=np.array(x_values, dtype=float))
        h5_file.create_dataset("y", data=np.array(y_values, dtype=float))
        h5_file.create_dataset("is_home", data=np.array([1 if idx % 2 == 0 else 0 for idx in range(row_count)]))
        h5_file.create_dataset("jersey_number", data=np.array([str(idx + 1).encode("utf-8") for idx in range(row_count)]))


@pytest.fixture
def media_panel_and_controller(qtbot):
    panel = MediaCenterPanel()
    qtbot.addWidget(panel)
    panel.show()
    qtbot.wait(20)

    controller = MediaController(panel.player, panel)
    yield panel, controller
    controller.stop()
    panel.close()


@pytest.mark.gui
def test_timeline_zoom_exceeds_old_cap_and_preserves_center(media_panel_and_controller, qtbot):
    panel, _controller = media_panel_and_controller
    initial_center = panel._get_current_center_ratio()

    for _ in range(8):
        panel._change_zoom(1)
    qtbot.wait(20)

    assert panel.zoom_level > 20.0
    assert panel._get_current_center_ratio() == pytest.approx(initial_center, abs=0.01)


@pytest.mark.gui
def test_timeline_zoom_stops_at_qt_width_limit_and_can_zoom_out(
    media_panel_and_controller,
    monkeypatch,
):
    panel, _controller = media_panel_and_controller
    viewport_width = max(1, panel.scroll_area.viewport().width())
    practical_test_limit = viewport_width * 32
    monkeypatch.setattr(
        "ui.media_player._QT_MAX_WIDGET_SIZE",
        practical_test_limit,
    )

    for _ in range(20):
        panel._change_zoom(1)

    saturated_level = panel.zoom_level
    saturated_width = panel.slider.width()
    assert saturated_level == pytest.approx(32.0)
    assert saturated_width == practical_test_limit

    panel._change_zoom(1)
    assert panel.zoom_level == saturated_level
    assert panel.slider.width() == saturated_width

    panel._change_zoom(-1)
    assert panel.zoom_level < saturated_level

    panel.zoom_level = saturated_level * 2
    panel._update_slider_width()
    assert panel.zoom_level == saturated_level
    assert panel.slider.width() == saturated_width

    for _ in range(20):
        panel._change_zoom(-1)
    assert panel.zoom_level == 1.0


@pytest.mark.gui
def test_mute_button_toggles_media_controller_and_updates_label(window, qtbot):
    assert window.center_panel.btn_mute.text() == ""
    assert window.center_panel.btn_mute.toolTip() == "Mute"
    assert window.center_panel.btn_mute.accessibleName() == "Mute"
    assert window.media_controller.is_muted() is False

    mute_states = []
    window.media_controller.muteStateChanged.connect(mute_states.append)

    qtbot.mouseClick(window.center_panel.btn_mute, Qt.MouseButton.LeftButton)
    qtbot.wait(20)
    assert window.media_controller.is_muted() is True
    assert window.center_panel.btn_mute.text() == ""
    assert window.center_panel.btn_mute.toolTip() == "Unmute"
    assert window.center_panel.btn_mute.accessibleName() == "Unmute"
    assert mute_states == [True]

    qtbot.mouseClick(window.center_panel.btn_mute, Qt.MouseButton.LeftButton)
    qtbot.wait(20)
    assert window.media_controller.is_muted() is False
    assert window.center_panel.btn_mute.text() == ""
    assert window.center_panel.btn_mute.toolTip() == "Mute"
    assert window.center_panel.btn_mute.accessibleName() == "Mute"
    assert mute_states == [True, False]


@pytest.mark.gui
def test_media_controller_set_muted_is_idempotent(window, qtbot):
    window.media_controller.set_muted(False)
    qtbot.wait(10)

    mute_states = []
    window.media_controller.muteStateChanged.connect(mute_states.append)

    window.media_controller.set_muted(False)
    qtbot.wait(10)
    assert mute_states == []

    window.media_controller.set_muted(True)
    qtbot.wait(10)
    assert mute_states == [True]

    window.media_controller.set_muted(True)
    qtbot.wait(10)
    assert mute_states == [True]

    window.media_controller.set_muted(False)
    qtbot.wait(10)
    assert mute_states == [True, False]


@pytest.mark.gui
def test_media_controller_mute_signal_updates_button_text(window, qtbot):
    window.media_controller.muteStateChanged.emit(True)
    qtbot.wait(10)
    assert window.center_panel.btn_mute.text() == ""
    assert window.center_panel.btn_mute.toolTip() == "Unmute"
    assert window.center_panel.btn_mute.accessibleName() == "Unmute"

    window.media_controller.muteStateChanged.emit(False)
    qtbot.wait(10)
    assert window.center_panel.btn_mute.text() == ""
    assert window.center_panel.btn_mute.toolTip() == "Mute"
    assert window.center_panel.btn_mute.accessibleName() == "Mute"


@pytest.mark.gui
def test_mute_state_is_restored_and_persisted_via_qsettings(window, qtbot):
    settings = window.dataset_explorer_controller.settings
    settings.setValue(window._MUTE_SETTING_KEY, True)
    settings.sync()

    window.media_controller.set_muted(False)
    qtbot.wait(10)
    assert window.media_controller.is_muted() is False

    window._restore_mute_state_from_settings()
    qtbot.wait(10)
    assert window.media_controller.is_muted() is True
    assert window.center_panel.btn_mute.toolTip() == "Unmute"

    window.media_controller.set_muted(False)
    qtbot.wait(10)
    saved = settings.value(window._MUTE_SETTING_KEY, True)
    if isinstance(saved, str):
        assert saved.strip().lower() in {"0", "false", "no", "off"}
    else:
        assert bool(saved) is False


@pytest.mark.gui
def test_raster_backend_does_not_show_frame_after_reentrant_stop(media_panel_and_controller, monkeypatch):
    _panel, controller = media_panel_and_controller
    shown_images = []

    class ReentrantStopRasterBackend(BaseRasterMediaBackend):
        def build_clip(self, _source):
            return RasterClip(
                frame_source=[{"frame": 1}],
                frame_count=1,
                time_axis_ms=[0],
                hold_ms=40,
                duration_ms=40,
                fallback_fps=0.0,
            )

        def render_frame_image(self, _frame_index, _frame_payload):
            self.stop()
            image = QImage(4, 4, QImage.Format.Format_ARGB32)
            image.fill(0xFFFFFFFF)
            return image

    backend = ReentrantStopRasterBackend(controller)
    monkeypatch.setattr(controller, "_show_frame_image", shown_images.append)

    assert backend.load_source({"type": "test_raster", "path": "synthetic"}, auto_play=False) is True
    assert shown_images == []


@pytest.mark.gui
@_frame_stack_missing
def test_frames_npy_controller_play_pause_seek_and_rate(media_panel_and_controller, qtbot):
    panel, controller = media_panel_and_controller

    durations = []
    states = []
    controller.durationChanged.connect(durations.append)
    controller.playbackStateChanged.connect(states.append)

    controller.load_and_play({"type": "frames_npy", "path": str(FRAME_STACK_PATH), "fps": 2.0})

    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)
    qtbot.waitUntil(lambda: controller.current_position_ms() > 0, timeout=1500)

    assert panel.frame_widget.isVisible() is True
    assert panel.video_widget.isVisible() is False
    assert durations
    assert durations[-1] == 8000
    assert states and states[-1] is True

    first_position = controller.current_position_ms()
    controller.set_playback_rate(2.0)
    qtbot.wait(250)
    assert controller.current_position_ms() > first_position

    controller.pause()
    paused_position = controller.current_position_ms()
    qtbot.wait(150)
    assert abs(controller.current_position_ms() - paused_position) <= 40
    assert states[-1] is False

    controller.set_position(4500)
    qtbot.wait(30)
    assert 4400 <= controller.current_position_ms() <= 4600

    controller.seek_relative(-500)
    qtbot.wait(30)
    assert 3900 <= controller.current_position_ms() <= 4100


@pytest.mark.gui
@pytest.mark.parametrize(
    ("array_factory", "expected_snippet"),
    [
        (lambda: np.zeros((16, 224, 224), dtype=np.uint8), "Expected a 4D array"),
        (lambda: np.zeros((16, 224, 224, 3), dtype=np.float32), "Expected dtype uint8"),
    ],
)
def test_frames_npy_invalid_payload_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
    tmp_path,
    array_factory,
    expected_snippet,
):
    _panel, controller = media_panel_and_controller
    errors = []
    bad_path = tmp_path / "bad_frames.npy"
    np.save(bad_path, array_factory())

    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "frames_npy", "path": str(bad_path)})

    # The float32 case saves a payload above _ASYNC_RASTER_LOAD_THRESHOLD_BYTES,
    # so validation runs on a background load thread; wait for it instead of
    # asserting immediately (the uint8 case stays under threshold and
    # resolves synchronously, so waitUntil is a no-op there).
    qtbot.waitUntil(lambda: bool(errors), timeout=2000)
    assert errors
    assert errors[-1][0]["title"] == "Invalid Frame Stack"
    assert expected_snippet in errors[-1][1]


@pytest.mark.gui
def test_frames_npy_missing_numpy_dependency_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
):
    _panel, controller = media_panel_and_controller
    errors = []

    monkeypatch.setattr("controllers.media_controller.np", None)
    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "frames_npy", "path": str(FRAME_STACK_PATH)})

    assert errors
    assert errors[-1][0]["title"] == "NumPy Dependency Missing"
    assert "NumPy is not installed" in errors[-1][1]


@pytest.mark.gui
def test_frames_npy_missing_file_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    errors = []
    missing_path = tmp_path / "missing_frames.npy"

    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "frames_npy", "path": str(missing_path)})

    assert errors
    assert errors[-1][0]["title"] == "Media Load Error"
    assert str(missing_path) in errors[-1][1]


@pytest.mark.gui
@_tracking_parquet_missing
def test_tracking_parquet_controller_play_pause_seek_and_rate(media_panel_and_controller, qtbot):
    panel, controller = media_panel_and_controller

    durations = []
    states = []
    controller.durationChanged.connect(durations.append)
    controller.playbackStateChanged.connect(states.append)

    controller.load_and_play({"type": "tracking_parquet", "path": str(TRACKING_PARQUET_PATH), "fps": 2.0})

    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)
    qtbot.waitUntil(lambda: controller.current_position_ms() > 0, timeout=1500)

    assert panel.frame_widget.isVisible() is True
    assert panel.video_widget.isVisible() is False
    assert durations
    assert durations[-1] in {4804, 4805}
    assert states and states[-1] is True

    first_position = controller.current_position_ms()
    controller.set_playback_rate(2.0)
    qtbot.wait(250)
    assert controller.current_position_ms() > first_position

    controller.pause()
    paused_position = controller.current_position_ms()
    qtbot.wait(150)
    assert abs(controller.current_position_ms() - paused_position) <= 40
    assert states[-1] is False

    controller.set_position(3400)
    qtbot.wait(30)
    assert 3300 <= controller.current_position_ms() <= 3600

    controller.seek_relative(-600)
    qtbot.wait(30)
    assert 2700 <= controller.current_position_ms() <= 3000


@pytest.mark.gui
def test_tracking_parquet_falls_back_to_input_fps_when_timestamps_invalid(
    media_panel_and_controller,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    parquet_path = tmp_path / "tracking_no_timestamps.parquet"
    dataframe = pd.DataFrame(
        {
            "videoTimeMs": [float("nan")] * 4,
            "homePlayers": ['[{"jerseyNum": "10", "x": 0.0, "y": 0.0}]'] * 4,
            "awayPlayers": ['[{"jerseyNum": "9", "x": 1.0, "y": 1.0}]'] * 4,
            "balls": ['[{"x": 0.5, "y": 0.5, "z": 0.0}]'] * 4,
        }
    )
    dataframe.to_parquet(parquet_path)

    durations = []
    controller.durationChanged.connect(durations.append)

    controller.load_and_play({"type": "tracking_parquet", "path": str(parquet_path), "fps": 2.0})

    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)
    assert durations[-1] == 2000

    controller.pause()
    controller.set_position(1200)
    qtbot.wait(30)
    assert controller.current_position_ms() == 1000


@pytest.mark.gui
def test_tracking_parquet_malformed_rows_render_without_failing(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    parquet_path = tmp_path / "tracking_malformed_rows.parquet"
    dataframe = pd.DataFrame(
        {
            "videoTimeMs": [1000.0, 1300.0],
            "homePlayers": ['{bad json}', '[{"jerseyNum": "7", "x": -3.0, "y": 2.0}]'],
            "awayPlayers": ['[]', '[{"jerseyNum": "3", "x": 4.0, "y": -1.0}]'],
            "balls": ['[]', '[{"x": 0.0, "y": 0.0, "z": 0.1}]'],
        }
    )
    dataframe.to_parquet(parquet_path)

    errors = []
    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "tracking_parquet", "path": str(parquet_path)})

    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)
    assert errors == []


@pytest.mark.gui
@pytest.mark.parametrize(
    ("module_name", "expected_title"),
    [
        ("pd", "Tracking Dependency Missing"),
        ("pyarrow", "Tracking Dependency Missing"),
    ],
)
def test_tracking_parquet_missing_dependency_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    module_name,
    expected_title,
):
    _panel, controller = media_panel_and_controller
    errors = []

    monkeypatch.setattr(f"controllers.media_controller.{module_name}", None)
    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "tracking_parquet", "path": str(TRACKING_PARQUET_PATH)})

    assert errors
    assert errors[-1][0]["title"] == expected_title
    assert "must be installed" in errors[-1][1]


@pytest.mark.gui
def test_tracking_parquet_missing_file_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    errors = []
    missing_path = tmp_path / "missing_tracking.parquet"

    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "tracking_parquet", "path": str(missing_path)})

    assert errors
    assert errors[-1][0]["title"] == "Media Load Error"
    assert str(missing_path) in errors[-1][1]


@pytest.mark.gui
def test_tracking_parquet_invalid_schema_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    errors = []
    parquet_path = tmp_path / "bad_tracking.parquet"
    pd.DataFrame({"unexpected": [1, 2, 3]}).to_parquet(parquet_path)

    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "tracking_parquet", "path": str(parquet_path)})

    assert errors
    assert errors[-1][0]["title"] == "Unsupported Tracking Schema"
    assert "unexpected" in errors[-1][1]


@pytest.mark.gui
def test_player_joints_h5_controller_play_pause_seek_and_rate(media_panel_and_controller, qtbot):
    panel, controller = media_panel_and_controller

    durations = []
    states = []
    controller.durationChanged.connect(durations.append)
    controller.playbackStateChanged.connect(states.append)

    controller.load_and_play({"type": "player_joints_h5", "path": str(PLAYER_JOINTS_H5_PATH)})

    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)
    qtbot.waitUntil(lambda: controller.current_position_ms() > 0, timeout=1500)

    assert panel.frame_widget.isVisible() is True
    assert panel.video_widget.isVisible() is False
    assert durations
    assert durations[-1] == 2000
    assert states and states[-1] is True

    first_position = controller.current_position_ms()
    controller.set_playback_rate(2.0)
    qtbot.wait(250)
    assert controller.current_position_ms() > first_position

    controller.pause()
    paused_position = controller.current_position_ms()
    qtbot.wait(150)
    assert abs(controller.current_position_ms() - paused_position) <= 40
    assert states[-1] is False

    controller.set_position(345)
    qtbot.wait(30)
    assert controller.current_position_ms() == 340


@pytest.mark.gui
def test_large_player_joints_h5_load_is_async_and_reports_progress(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    h5_path = tmp_path / "large_joints.h5"
    _write_minimal_player_joints_h5(
        h5_path,
        [
            b"2026-01-01 12:00:00.000000",
            b"2026-01-01 12:00:00.040000",
            b"2026-01-01 12:00:00.080000",
        ],
    )
    controller._single._ASYNC_RASTER_LOAD_THRESHOLD_BYTES = 1
    progress_updates = []
    # Grouped/routed sessions redirect each backend's progress reporting to
    # its own MediaViewerPane (session.media_panel = pane), not the
    # top-level MediaCenterPanel -- so the pane class, not the panel
    # instance, is what needs patching to observe it.
    original_show_progress = MediaViewerPane.show_loading_progress

    def record_progress(self, message, current=0, total=0):
        progress_updates.append((message, current, total))
        original_show_progress(self, message, current, total)

    monkeypatch.setattr(MediaViewerPane, "show_loading_progress", record_progress)
    event_loop_ticks = []
    QTimer.singleShot(0, lambda: event_loop_ticks.append(True))

    controller.route_media_group(
        [{"type": "player_joints_h5", "path": str(h5_path)}],
        str(h5_path),
        False,
    )

    record = controller._sessions[0]
    backend = record["controller"]._active_backend
    assert backend._is_loading is True
    assert panel._viewer_panes[0].loading_widget.isVisible() is True
    qtbot.waitUntil(lambda: bool(event_loop_ticks), timeout=1500)
    qtbot.waitUntil(lambda: not backend._is_loading, timeout=3000)

    assert any(total == 3 and current < total for _message, current, total in progress_updates)
    assert any(total == 3 and current == total for _message, current, total in progress_updates)
    assert record["duration_ms"] == 120
    assert record["origin_utc"].isoformat(sep=" ") == "2026-01-01 12:00:00"
    assert controller._global_origin_utc == record["origin_utc"]
    assert panel._viewer_panes[0].loading_widget.isVisible() is False


@pytest.mark.gui
def test_async_raster_load_survives_controller_deletion(qtbot, tmp_path):
    started = threading.Event()
    release = threading.Event()
    build_finished = threading.Event()
    source_closed = threading.Event()

    class DisposableController(QObject):
        positionChanged = pyqtSignal(int)
        durationChanged = pyqtSignal(int)
        playbackStateChanged = pyqtSignal(bool)

        _FRAME_TIMER_INTERVAL_MS = 30
        _FRAME_DEFAULT_FPS = 2.0
        _RASTER_FRAME_CACHE_LIMIT = 8
        _ASYNC_RASTER_LOAD_THRESHOLD_BYTES = 1

        def __init__(self):
            super().__init__()
            self.player = None
            self.media_panel = None

        def _handle_raster_load_progress(self, backend, request_id, generation, current, total, message):
            backend._on_async_load_progress(request_id, generation, current, total, message)

        def _handle_raster_load_finished(self, backend, request_id, generation, clip, error_details):
            backend._on_async_load_finished(request_id, generation, clip, error_details)

        def _show_load_progress(self, *_args):
            return None

        def _show_frame_image(self, *_args):
            return None

        def _trigger_error_dialog(self, *_args, **_kwargs):
            return None

    class CloseableFrameSource(list):
        def close(self):
            source_closed.set()

    class SlowRasterBackend(BaseRasterMediaBackend):
        def build_clip(self, _source, progress_callback=None):
            started.set()
            release.wait(timeout=2.0)
            build_finished.set()
            return RasterClip(
                frame_source=CloseableFrameSource([0]),
                frame_count=1,
                time_axis_ms=[0],
                hold_ms=40,
                duration_ms=40,
                fallback_fps=25.0,
            )

        def render_frame_image(self, _frame_index, _frame_payload):
            return QImage(1, 1, QImage.Format.Format_ARGB32)

    source_path = tmp_path / "slow-raster.bin"
    source_path.write_bytes(b"large")
    controller = DisposableController()
    backend = SlowRasterBackend(controller)

    assert backend.load_source(
        {"type": "test_raster", "path": str(source_path)},
        auto_play=False,
    )
    qtbot.waitUntil(started.is_set, timeout=1500)
    cancel_event = backend._load_cancel_event

    controller.deleteLater()
    qtbot.waitUntil(cancel_event.is_set, timeout=1500)
    release.set()
    qtbot.waitUntil(build_finished.is_set, timeout=1500)
    qtbot.waitUntil(source_closed.is_set, timeout=1500)

    assert backend._clip is None


@pytest.mark.gui
def test_player_joints_h5_rate_change_keeps_current_position_anchor(media_panel_and_controller, qtbot):
    panel, controller = media_panel_and_controller

    controller.load_and_play({"type": "player_joints_h5", "path": str(PLAYER_JOINTS_H5_PATH)})

    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)
    qtbot.waitUntil(lambda: controller.current_position_ms() >= 300, timeout=1500)

    before_rate_change = controller.current_position_ms()
    controller.set_playback_rate(4.0)
    after_rate_change = controller.current_position_ms()

    assert after_rate_change >= before_rate_change
    assert after_rate_change - before_rate_change <= 80


@pytest.mark.gui
def test_player_joints_h5_load_keeps_h5_datasets_lazy_and_closes_on_stop(
    media_panel_and_controller,
    qtbot,
):
    panel, controller = media_panel_and_controller

    controller.load_and_play({"type": "player_joints_h5", "path": str(PLAYER_JOINTS_H5_PATH)}, auto_play=False)
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    backend = controller._active_backend
    frame_source = backend._clip.frame_source
    assert not isinstance(frame_source, list)
    assert isinstance(frame_source._datasets["nose_x"], h5py.Dataset)
    assert frame_source._h5_file.id.valid == 1

    controller.stop()

    assert frame_source._h5_file.id.valid == 0


@pytest.mark.gui
def test_player_joints_h5_normalized_source_preserves_ball_path(
    media_panel_and_controller,
    ball_h5_path,
):
    _panel, controller = media_panel_and_controller

    source = controller._normalize_media_source(
        {
            "type": "player_joints_h5",
            "path": str(PLAYER_JOINTS_H5_PATH),
            "ball_path": str(ball_h5_path),
        }
    )

    assert source["type"] == "player_joints_h5"
    assert source["path"] == str(PLAYER_JOINTS_H5_PATH)
    assert source["ball_path"] == str(ball_h5_path)
    assert "fps" not in source


@pytest.mark.gui
def test_player_joints_h5_ball_overlay_loads_lazily_aligns_and_closes(
    media_panel_and_controller,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    joints_path = tmp_path / "joints.h5"
    ball_path = tmp_path / "ball.h5"
    _write_minimal_player_joints_h5(
        joints_path,
        [
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:00.040000",
        ],
    )
    _write_ball_h5(
        ball_path,
        [
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:00.020000",
            b"2026-01-01 00:00:00.080000",
        ],
        [1.0, 2.0, 3.0],
    )

    controller.load_and_play(
        {"type": "player_joints_h5", "path": str(joints_path), "ball_path": str(ball_path)},
        auto_play=False,
    )
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    frame_source = controller._active_backend._clip.frame_source
    ball_source = frame_source._ball_source
    assert ball_source is not None
    assert isinstance(ball_source._datasets["x"], h5py.Dataset)
    assert frame_source[0]["ball"]["x"] == pytest.approx(1.0)
    assert frame_source[1]["ball"]["x"] == pytest.approx(2.0)

    controller.stop()

    assert ball_source._h5_file.id.valid == 0


@pytest.mark.gui
def test_player_joints_h5_invalid_ball_rows_are_skipped_without_failing(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    errors = []
    joints_path = tmp_path / "joints.h5"
    ball_path = tmp_path / "ball.h5"
    _write_minimal_player_joints_h5(
        joints_path,
        [
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:00.040000",
        ],
    )
    _write_ball_h5(
        ball_path,
        [b"2026-01-01 00:00:00.000000", b"2026-01-01 00:00:00.020000"],
        [1.0, -1.0],
    )
    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play(
        {"type": "player_joints_h5", "path": str(joints_path), "ball_path": str(ball_path)},
        auto_play=False,
    )
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    frame_source = controller._active_backend._clip.frame_source
    assert frame_source[0]["ball"]["x"] == pytest.approx(1.0)
    assert "ball" not in frame_source[1]
    assert errors == []


@pytest.mark.gui
def test_player_joints_h5_missing_ball_file_is_nonfatal(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    errors = []
    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play(
        {
            "type": "player_joints_h5",
            "path": str(PLAYER_JOINTS_H5_PATH),
            "ball_path": str(tmp_path / "missing_ball.h5"),
        },
        auto_play=False,
    )
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    assert controller._active_backend._clip.frame_source._ball_source is None
    assert errors == []


@pytest.mark.gui
def test_player_joints_h5_render_cache_is_bounded(media_panel_and_controller, qtbot):
    panel, controller = media_panel_and_controller
    controller._RASTER_FRAME_CACHE_LIMIT = 3

    controller.load_and_play({"type": "player_joints_h5", "path": str(PLAYER_JOINTS_H5_PATH)}, auto_play=False)
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    backend = controller._active_backend
    for position_ms in (0, 100, 200, 300, 400, 500):
        controller.set_position(position_ms)
        qtbot.wait(10)

    assert len(backend._frame_image_cache) <= 3


@pytest.mark.gui
def test_player_joints_h5_3d_projection_uses_depth_and_z_height(media_panel_and_controller, qtbot):
    panel, controller = media_panel_and_controller

    controller.load_and_play({"type": "player_joints_h5", "path": str(PLAYER_JOINTS_H5_PATH)}, auto_play=False)
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    backend = controller._active_backend
    layout = backend._joint_scene_layout(
        controller._TRACKING_IMAGE_WIDTH,
        controller._TRACKING_IMAGE_HEIGHT,
    )
    origin_x, origin_y = backend._project_joint_scene_point(0.0, 0.0, 0.0, layout)
    x_axis_x, x_axis_y = backend._project_joint_scene_point(10.0, 0.0, 0.0, layout)
    positive_y_x, positive_y_y = backend._project_joint_scene_point(0.0, 10.0, 0.0, layout)
    negative_y_x, negative_y_y = backend._project_joint_scene_point(0.0, -10.0, 0.0, layout)
    diagonal_x, diagonal_y = backend._project_joint_scene_point(10.0, 10.0, 0.0, layout)
    elevated_x, elevated_y = backend._project_joint_scene_point(0.0, 0.0, 1.5, layout)
    _origin_u, origin_v = backend._scene_basis(0.0, 0.0, 0.0)
    _elevated_u, elevated_v = backend._scene_basis(0.0, 0.0, 1.5)

    assert x_axis_x > origin_x
    assert x_axis_y > origin_y
    assert positive_y_x > origin_x
    assert positive_y_y < origin_y
    assert negative_y_x < origin_x
    assert negative_y_y > origin_y
    assert diagonal_x > origin_x
    assert diagonal_y == pytest.approx(origin_y)
    assert elevated_x == pytest.approx(origin_x)
    assert elevated_y < origin_y
    assert origin_v - elevated_v == pytest.approx(1.5 * backend._SCENE_Z_SCALE)


@pytest.mark.gui
def test_player_joints_h5_goal_posts_project_above_field(media_panel_and_controller, qtbot):
    panel, controller = media_panel_and_controller

    controller.load_and_play({"type": "player_joints_h5", "path": str(PLAYER_JOINTS_H5_PATH)}, auto_play=False)
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    backend = controller._active_backend
    layout = backend._joint_scene_layout(
        controller._TRACKING_IMAGE_WIDTH,
        controller._TRACKING_IMAGE_HEIGHT,
    )
    goal_x = controller._TRACKING_PITCH_LENGTH / 2.0
    ground_x, ground_y = backend._project_joint_scene_point(goal_x, backend._GOAL_WIDTH / 2.0, 0.0, layout)
    crossbar_x, crossbar_y = backend._project_joint_scene_point(goal_x, backend._GOAL_WIDTH / 2.0, backend._GOAL_HEIGHT, layout)
    _ground_u, ground_v = backend._scene_basis(goal_x, backend._GOAL_WIDTH / 2.0, 0.0)
    _crossbar_u, crossbar_v = backend._scene_basis(goal_x, backend._GOAL_WIDTH / 2.0, backend._GOAL_HEIGHT)

    assert crossbar_x == pytest.approx(ground_x)
    assert crossbar_y < ground_y
    assert ground_v - crossbar_v == pytest.approx(backend._GOAL_HEIGHT * backend._SCENE_Z_SCALE)


@pytest.mark.gui
def test_player_joints_h5_joint_marker_radius_is_small_and_parameterized(media_panel_and_controller, qtbot):
    panel, controller = media_panel_and_controller

    controller.load_and_play({"type": "player_joints_h5", "path": str(PLAYER_JOINTS_H5_PATH)}, auto_play=False)
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    backend = controller._active_backend
    layout = backend._joint_scene_layout(
        controller._TRACKING_IMAGE_WIDTH,
        controller._TRACKING_IMAGE_HEIGHT,
    )
    radius = backend._joint_marker_radius(layout)

    assert radius == pytest.approx(
        max(
            backend._JOINT_MARKER_RADIUS_MIN,
            layout["scale"] * backend._JOINT_MARKER_RADIUS_SCALE,
        )
    )
    assert radius < 3.0


@pytest.mark.gui
def test_player_joints_h5_missing_timestamp_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    errors = []
    h5_path = tmp_path / "missing_timestamp.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("nose_x", data=np.array([0.0, 1.0]))
        h5_file.create_dataset("nose_y", data=np.array([0.0, 1.0]))

    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "player_joints_h5", "path": str(h5_path)})

    assert errors
    assert errors[-1][0]["title"] == "Unsupported H5 Schema"
    assert "timestamp_utc" in errors[-1][1]


@pytest.mark.gui
def test_player_joints_h5_malformed_rows_render_without_failing(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    errors = []
    h5_path = tmp_path / "partial_nan_joints.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset(
            "timestamp_utc",
            data=np.array(
                [
                    b"2026-01-01 00:00:00.000000",
                    b"2026-01-01 00:00:00.040000",
                ]
            ),
        )
        h5_file.create_dataset("is_home", data=np.array([1, 0]))
        h5_file.create_dataset("jersey_number", data=np.array([b"10", b"7"]))
        h5_file.create_dataset("nose_x", data=np.array([0.0, np.nan]))
        h5_file.create_dataset("nose_y", data=np.array([0.0, np.nan]))
        h5_file.create_dataset("neck_x", data=np.array([1.0, 2.0]))
        h5_file.create_dataset("neck_y", data=np.array([1.0, 2.0]))

    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "player_joints_h5", "path": str(h5_path)})

    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)
    assert errors == []


@pytest.mark.gui
def test_player_joints_h5_missing_dependency_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
):
    _panel, controller = media_panel_and_controller
    errors = []

    monkeypatch.setattr("controllers.media_controller.h5py", None)
    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "player_joints_h5", "path": str(PLAYER_JOINTS_H5_PATH)})

    assert errors
    assert errors[-1][0]["title"] == "H5 Dependency Missing"
    assert "h5py must be installed" in errors[-1][1]


@pytest.mark.gui
def test_player_joints_h5_missing_file_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    errors = []
    missing_path = tmp_path / "missing_joints.h5"

    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "player_joints_h5", "path": str(missing_path)})

    assert errors
    assert errors[-1][0]["title"] == "Media Load Error"
    assert str(missing_path) in errors[-1][1]


@pytest.mark.gui
def test_player_joints_h5_inconsistent_lengths_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    errors = []
    h5_path = tmp_path / "bad_lengths.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("timestamp_utc", data=np.array([b"2026-01-01 00:00:00.000000"]))
        h5_file.create_dataset("nose_x", data=np.array([0.0, 1.0]))
        h5_file.create_dataset("nose_y", data=np.array([0.0, 1.0]))

    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "player_joints_h5", "path": str(h5_path)})

    assert errors
    assert errors[-1][0]["title"] == "Unsupported H5 Schema"
    assert "equal-length" in errors[-1][1]


@pytest.mark.gui
def test_player_centroids_h5_controller_load_play_pause_seek_and_rate(
    media_panel_and_controller,
    qtbot,
    player_centroids_h5_path,
):
    panel, controller = media_panel_and_controller

    durations = []
    states = []
    controller.durationChanged.connect(durations.append)
    controller.playbackStateChanged.connect(states.append)

    controller.load_and_play(
        {"type": "player_centroids_h5", "path": str(player_centroids_h5_path)}
    )

    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=6000)
    qtbot.waitUntil(lambda: controller.current_position_ms() > 0, timeout=1500)

    assert panel.frame_widget.isVisible() is True
    assert panel.video_widget.isVisible() is False
    assert durations and durations[-1] > 0
    assert states and states[-1] is True

    first_position = controller.current_position_ms()
    controller.set_playback_rate(4.0)
    after_rate_change = controller.current_position_ms()
    assert after_rate_change - first_position <= 80
    qtbot.wait(150)
    assert controller.current_position_ms() > after_rate_change

    controller.pause()
    paused_position = controller.current_position_ms()
    qtbot.wait(150)
    assert abs(controller.current_position_ms() - paused_position) <= 40

    controller.set_position(1500)
    qtbot.wait(30)
    assert 1400 <= controller.current_position_ms() <= 1600


@pytest.mark.gui
def test_player_centroids_h5_keeps_h5_datasets_lazy_and_closes_on_stop(
    media_panel_and_controller,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    h5_path = tmp_path / "centroids.h5"
    _write_minimal_player_centroids_h5(
        h5_path,
        [
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:00.040000",
        ],
    )

    controller.load_and_play({"type": "player_centroids_h5", "path": str(h5_path)}, auto_play=False)
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    frame_source = controller._active_backend._clip.frame_source
    assert isinstance(frame_source._datasets["x"], h5py.Dataset)
    assert frame_source._h5_file.id.valid == 1
    assert frame_source[0]["players"][0]["x"] == pytest.approx(0.0)

    controller.stop()

    assert frame_source._h5_file.id.valid == 0


@pytest.mark.gui
def test_player_centroids_h5_ball_overlay_loads_aligns_and_closes(
    media_panel_and_controller,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    centroids_path = tmp_path / "centroids.h5"
    ball_path = tmp_path / "ball.h5"
    _write_minimal_player_centroids_h5(
        centroids_path,
        [
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:00.040000",
        ],
    )
    _write_ball_h5(
        ball_path,
        [
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:00.020000",
        ],
        [4.0, 5.0],
    )

    controller.load_and_play(
        {"type": "player_centroids_h5", "path": str(centroids_path), "ball_path": str(ball_path)},
        auto_play=False,
    )
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    frame_source = controller._active_backend._clip.frame_source
    ball_source = frame_source._ball_source
    assert ball_source is not None
    assert isinstance(ball_source._datasets["x"], h5py.Dataset)
    assert frame_source[1]["ball"]["x"] == pytest.approx(5.0)

    controller.stop()

    assert ball_source._h5_file.id.valid == 0


@pytest.mark.gui
def test_player_centroids_h5_malformed_rows_render_without_failing(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    errors = []
    h5_path = tmp_path / "bad_rows_centroids.h5"
    _write_minimal_player_centroids_h5(
        h5_path,
        [
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:00.000000",
        ],
        x_values=[0.0, -1.0],
        y_values=[0.0, np.nan],
    )
    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "player_centroids_h5", "path": str(h5_path)}, auto_play=False)
    qtbot.waitUntil(lambda: panel.frame_widget.pixmap() is not None, timeout=1500)

    frame_source = controller._active_backend._clip.frame_source
    assert len(frame_source[0]["players"]) == 1
    assert errors == []


@pytest.mark.gui
@pytest.mark.parametrize(
    ("datasets", "expected_snippet"),
    [
        ({"x": [0.0], "y": [0.0]}, "timestamp_utc"),
        ({"timestamp_utc": [b"2026-01-01 00:00:00.000000"], "x": [0.0]}, "Missing required centroid"),
        (
            {
                "timestamp_utc": [b"2026-01-01 00:00:00.000000"],
                "x": [0.0, 1.0],
                "y": [0.0],
            },
            "equal-length",
        ),
    ],
)
def test_player_centroids_h5_invalid_schema_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    tmp_path,
    datasets,
    expected_snippet,
):
    _panel, controller = media_panel_and_controller
    errors = []
    h5_path = tmp_path / "invalid_centroids.h5"
    with h5py.File(h5_path, "w") as h5_file:
        for key, values in datasets.items():
            h5_file.create_dataset(key, data=np.array(values))
    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "player_centroids_h5", "path": str(h5_path)})

    assert errors
    assert errors[-1][0]["title"] == "Unsupported H5 Schema"
    assert expected_snippet in errors[-1][1]


@pytest.mark.gui
def test_player_centroids_h5_missing_dependency_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    player_centroids_h5_path,
):
    _panel, controller = media_panel_and_controller
    errors = []

    monkeypatch.setattr("controllers.media_controller.h5py", None)
    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play(
        {"type": "player_centroids_h5", "path": str(player_centroids_h5_path)}
    )

    assert errors
    assert errors[-1][0]["title"] == "H5 Dependency Missing"
    assert "h5py must be installed" in errors[-1][1]


@pytest.mark.gui
def test_player_centroids_h5_missing_file_reports_clear_error(
    media_panel_and_controller,
    monkeypatch,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    errors = []
    missing_path = tmp_path / "missing_centroids.h5"
    monkeypatch.setattr(
        controller,
        "_trigger_error_dialog",
        lambda error_details, **kwargs: errors.append((kwargs, error_details)),
    )

    controller.load_and_play({"type": "player_centroids_h5", "path": str(missing_path)})

    assert errors
    assert errors[-1][0]["title"] == "Media Load Error"
    assert str(missing_path) in errors[-1][1]
@pytest.mark.gui
def test_grouped_h5_playback_uses_utc_union_and_multiple_panes(
    media_panel_and_controller,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    controller.positionChanged.connect(panel.on_media_position_changed)
    controller.durationChanged.connect(panel.on_media_duration_changed)
    joints_path = tmp_path / "group_joints.h5"
    centroids_path = tmp_path / "group_centroids.h5"
    _write_minimal_player_joints_h5(
        joints_path,
        [
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:01.000000",
            b"2026-01-01 00:00:02.000000",
        ],
    )
    _write_minimal_player_centroids_h5(
        centroids_path,
        [
            b"2026-01-01 00:00:01.000000",
            b"2026-01-01 00:00:02.000000",
        ],
    )

    controller.route_media_group(
        [
            {"type": "player_joints_h5", "path": str(joints_path)},
            {"type": "player_centroids_h5", "path": str(centroids_path)},
        ],
        str(joints_path),
        False,
    )

    assert len(panel._viewer_panes) == 2
    assert controller._global_origin_utc.isoformat(sep=" ") == "2026-01-01 00:00:00"
    assert controller._group_duration_ms == 3000
    assert controller._sessions[0]["offset_ms"] == 0
    assert controller._sessions[1]["offset_ms"] == 1000
    assert panel._viewer_panes[0].timing_label.text() == "UTC +0.000s"
    assert panel._viewer_panes[1].timing_label.text() == "UTC +1.000s"
    assert "Not available" in panel._viewer_panes[1].status_label.text()

    controller.set_position(1500)
    qtbot.wait(20)
    assert panel._viewer_panes[0].frame_widget.pixmap() is not None
    assert panel._viewer_panes[1].frame_widget.pixmap() is not None
    assert "2026-01-01 00:00:01.500 UTC" in panel.time_label.text()

    controller.play()
    qtbot.waitUntil(lambda: controller.current_position_ms() > 1500, timeout=1000)
    controller.pause()
    shared_positions = [
        record["controller"].current_position_ms() + record["offset_ms"]
        for record in controller._sessions
    ]
    assert max(shared_positions) - min(shared_positions) <= 1000
    assert controller.is_playing() is False


@pytest.mark.gui
def test_grouped_relative_source_aligns_to_union_start_and_feed_mute(
    media_panel_and_controller,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    joints_path = tmp_path / "relative_joints.h5"
    frames_path = tmp_path / "relative_frames.npy"
    _write_minimal_player_joints_h5(
        joints_path,
        [b"2026-01-01 12:00:00.000000", b"2026-01-01 12:00:00.040000"],
    )
    np.save(frames_path, np.zeros((2, 4, 4, 3), dtype=np.uint8))

    controller.route_media_group(
        [
            {"type": "player_joints_h5", "path": str(joints_path)},
            {"type": "frames_npy", "path": str(frames_path), "fps": 25.0},
        ],
        str(frames_path),
        False,
    )

    assert controller._sessions[1]["offset_ms"] == 0
    assert panel._viewer_panes[1].timing_label.text() == "Relative"
    assert panel._viewer_panes[1].property("focused") is True

    controller.toggle_feed_mute(str(frames_path))
    assert panel._viewer_panes[1].btn_mute.toolTip() == "Unmute this feed"
    assert controller._sessions[1]["controller"].player.audioOutput().isMuted() is True
    controller.set_muted(True)
    controller.toggle_feed_mute(str(frames_path))
    assert controller._sessions[1]["controller"].player.audioOutput().isMuted() is True
    controller.set_muted(False)
    assert controller._sessions[1]["controller"].player.audioOutput().isMuted() is False


@pytest.mark.gui
def test_focus_source_only_changes_viewer_highlight_and_preserves_position(
    media_panel_and_controller,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    first_path = tmp_path / "focus_first.h5"
    second_path = tmp_path / "focus_second.h5"
    timestamps = [b"2026-01-01 12:00:00.000000", b"2026-01-01 12:00:01.000000"]
    _write_minimal_player_joints_h5(first_path, timestamps)
    _write_minimal_player_centroids_h5(second_path, timestamps)

    controller.route_media_group(
        [
            {"type": "player_joints_h5", "path": str(first_path)},
            {"type": "player_centroids_h5", "path": str(second_path)},
        ],
        str(first_path),
        False,
    )
    controller.set_position(750)
    position_before_focus = controller.current_position_ms()
    playing_before_focus = controller.is_playing()

    controller.focus_source(str(second_path))

    assert controller.current_position_ms() == position_before_focus
    assert controller.is_playing() is playing_before_focus
    assert panel._viewer_panes[0].property("focused") is False
    assert panel._viewer_panes[1].property("focused") is True

    pane_ids = [id(pane) for pane in panel._viewer_panes]
    for mode in (ViewerLayoutMode.SINGLE, ViewerLayoutMode.TABS, ViewerLayoutMode.MOSAIC):
        panel.set_viewer_layout(mode)
        assert controller.current_position_ms() == position_before_focus
        assert controller.is_playing() is playing_before_focus
        assert [id(pane) for pane in panel._viewer_panes] == pane_ids


@pytest.mark.gui
def test_viewer_layouts_reuse_panes_and_focus_the_selected_modality(
    media_panel_and_controller,
):
    panel, _controller = media_panel_and_controller
    sources = [
        {"type": "video", "path": "/tmp/camera_a.mp4"},
        {"type": "tracking", "path": "/tmp/tracking.parquet"},
        {"type": "text", "path": "/tmp/notes.txt"},
    ]
    panel.configure_viewers(sources, sources[0]["path"])
    pane_ids = [id(pane) for pane in panel._viewer_panes]

    panel.set_viewer_layout(ViewerLayoutMode.SINGLE)
    assert panel.viewer_layout_stack.currentWidget() is panel.single_view_stack
    assert panel.single_view_stack.currentWidget() is panel._viewer_panes[0]

    panel.focus_viewer(sources[2]["path"])
    assert panel.single_view_stack.currentWidget() is panel._viewer_panes[2]

    panel.set_viewer_layout(ViewerLayoutMode.TABS)
    assert panel.viewer_layout_stack.currentWidget() is panel.viewer_tabs
    assert panel.viewer_tabs.count() == 3
    assert panel.viewer_tabs.currentWidget() is panel._viewer_panes[2]
    assert panel.viewer_tabs.tabText(1) == "tracking · tracking.parquet"

    panel.set_viewer_layout(ViewerLayoutMode.MOSAIC)
    assert panel.viewer_layout_stack.currentWidget() is panel.viewer_scroll
    assert [id(pane) for pane in panel._viewer_panes] == pane_ids
    assert all(pane.isVisible() for pane in panel._viewer_panes)


@pytest.mark.gui
def test_modality_tab_selection_emits_focus_without_reconfiguring_panes(
    media_panel_and_controller,
    qtbot,
):
    panel, _controller = media_panel_and_controller
    sources = [
        {"type": "video", "path": "/tmp/camera_a.mp4"},
        {"type": "video", "path": "/tmp/camera_b.mp4"},
    ]
    panel.configure_viewers(sources, sources[0]["path"])
    pane_ids = [id(pane) for pane in panel._viewer_panes]
    focus_requests = []
    panel.paneFocusRequested.connect(focus_requests.append)

    panel.set_viewer_layout(ViewerLayoutMode.TABS)
    panel.viewer_tabs.setCurrentIndex(1)
    qtbot.wait(10)

    assert focus_requests == [sources[1]["path"]]
    assert panel._viewer_panes[1].property("focused") is True
    assert [id(pane) for pane in panel._viewer_panes] == pane_ids


@pytest.mark.gui
def test_sync_mode_pins_single_and_tab_layouts_to_syncing_modality(
    media_panel_and_controller,
    qtbot,
):
    panel, _controller = media_panel_and_controller
    sources = [
        {"type": "video", "path": "/tmp/camera_a.mp4"},
        {"type": "video", "path": "/tmp/camera_b.mp4"},
    ]
    panel.configure_viewers(sources, sources[0]["path"])
    panel.set_sync_mode(True, sources[1]["path"])

    panel.set_viewer_layout(ViewerLayoutMode.SINGLE)
    assert panel.single_view_stack.currentWidget() is panel._viewer_panes[1]

    panel.set_viewer_layout(ViewerLayoutMode.TABS)
    assert panel.viewer_tabs.currentIndex() == 1
    assert panel.viewer_tabs.tabBar().isEnabled() is False
    panel.viewer_tabs.setCurrentIndex(0)
    qtbot.wait(10)
    assert panel.viewer_tabs.currentIndex() == 1

    panel.set_sync_mode(False)
    assert panel.viewer_tabs.tabBar().isEnabled() is True


@pytest.mark.gui
def test_grouped_videos_autoplay_from_shared_clock(media_panel_and_controller, qtbot):
    panel, controller = media_panel_and_controller
    video_root = Path(__file__).resolve().parents[1] / "data"
    sources = [
        {"type": "video", "path": str(video_root / "test_video_1.mp4")},
        {"type": "video", "path": str(video_root / "test_video_2.mp4")},
    ]

    controller.route_media_group(sources, sources[0]["path"], True)

    qtbot.waitUntil(lambda: controller._group_duration_ms > 0, timeout=5000)
    qtbot.waitUntil(controller.is_playing, timeout=5000)
    qtbot.waitUntil(lambda: controller.current_position_ms() > 0, timeout=5000)
    assert len(panel._viewer_panes) == 2
    assert all(record["controller"].is_playing() for record in controller._sessions)

    controller.set_position(1000)

    def grouped_video_positions():
        return [record["controller"].current_position_ms() for record in controller._sessions]

    qtbot.wait(300)
    qtbot.waitUntil(
        lambda: max(grouped_video_positions()) - min(grouped_video_positions()) <= 250,
        timeout=2500,
    )
    positions = grouped_video_positions()
    assert max(positions) - min(positions) <= 250


@pytest.mark.gui
def test_group_clock_does_not_seek_video_for_normal_position_reporting_lag(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
):
    _panel, controller = media_panel_and_controller
    video_path = Path(__file__).resolve().parents[1] / "data" / "test_video_1.mp4"
    source = {"type": "video", "path": str(video_path), "fps": 50.0}

    controller.route_media_group([source], source["path"], False)
    qtbot.waitUntil(lambda: controller._sessions[0]["duration_ms"] > 0, timeout=5000)
    session = controller._sessions[0]["controller"]
    target = 2000
    seek_calls = []
    reported_position = target - controller._VIDEO_DRIFT_TOLERANCE_MS
    monkeypatch.setattr(session, "current_position_ms", lambda: reported_position)
    monkeypatch.setattr(session, "set_position", seek_calls.append)

    controller._render_group_position(target, force_video_seek=True)
    assert seek_calls == []

    reported_position -= 1
    controller._render_group_position(target, force_video_seek=True)
    assert seek_calls == [target]


@pytest.mark.gui
def test_running_video_clock_skips_drift_seek_but_accepts_explicit_seek(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
):
    _panel, controller = media_panel_and_controller
    video_path = Path(__file__).resolve().parents[1] / "data" / "test_video_1.mp4"
    source = {"type": "video", "path": str(video_path)}

    controller.route_media_group([source], source["path"], False)
    qtbot.waitUntil(lambda: controller._sessions[0]["duration_ms"] > 0, timeout=5000)
    record = controller._sessions[0]
    session = record["controller"]
    seek_calls = []
    monkeypatch.setattr(session, "is_playing", lambda: True)
    monkeypatch.setattr(session, "current_position_ms", lambda: 1234)
    monkeypatch.setattr(session, "set_position", seek_calls.append)
    controller._group_playing = True

    assert controller.current_position_ms() == 1234 + record["offset_ms"]
    controller._render_group_position(4000, force_video_seek=True)
    assert seek_calls == []

    controller.set_position(4000)
    assert seek_calls == [4000 - record["offset_ms"]]


@pytest.mark.gui
def test_deferred_raster_render_does_not_block_gui_thread(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    frames_path = tmp_path / "deferred_frames.npy"
    np.save(frames_path, np.zeros((3, 8, 8, 3), dtype=np.uint8))
    controller.load_and_play(
        {"type": "frames_npy", "path": str(frames_path), "fps": 2.0},
        auto_play=False,
    )
    backend = controller._active_backend
    original_render = backend.render_frame_image

    def slow_render(frame_index, payload):
        time.sleep(0.2)
        return original_render(frame_index, payload)

    monkeypatch.setattr(backend, "render_frame_image", slow_render)
    started = time.perf_counter()
    backend.set_position_deferred(500)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    qtbot.waitUntil(lambda: 1 in backend._frame_image_cache, timeout=1500)


@pytest.mark.gui
def test_deferred_raster_render_displays_forward_progress_while_newer_frame_is_pending(
    media_panel_and_controller,
    monkeypatch,
    qtbot,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    frames_path = tmp_path / "slow_deferred_frames.npy"
    np.save(frames_path, np.zeros((3, 8, 8, 3), dtype=np.uint8))
    controller.load_and_play(
        {"type": "frames_npy", "path": str(frames_path), "fps": 2.0},
        auto_play=False,
    )
    backend = controller._active_backend
    displayed_indices = []

    def slow_index_image(frame_index, _payload):
        time.sleep(0.1)
        image = QImage(1, 1, QImage.Format.Format_ARGB32)
        image.fill(frame_index)
        return image

    monkeypatch.setattr(backend, "render_frame_image", slow_index_image)
    # load_and_play() runs through controller._single, and the backend keeps
    # a reference to that inner object (backend.controller is
    # controller._single), not the outer MediaController facade. The facade
    # only forwards attribute *reads* via __getattr__, not writes, so
    # patching `controller` directly here would set a stray attribute the
    # real call path never sees.
    monkeypatch.setattr(
        controller._single,
        "_show_frame_image",
        lambda image: displayed_indices.append(image.pixel(0, 0)),
    )

    backend.set_position_deferred(500)
    backend.set_position_deferred(1000)

    qtbot.waitUntil(lambda: 1 in displayed_indices, timeout=1500)
    assert backend._frame_last_rendered_index == 2


@pytest.mark.gui
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2022-12-03 13:27:59.461000", "2022-12-03 13:27:59.461000"),
        ("2022-12-03T13:27:59", "2022-12-03 13:27:59"),
        ("2022-12-03T13:27:59Z", "2022-12-03 13:27:59"),
        ("2022-12-03T16:27:59+03:00", "2022-12-03 13:27:59"),
        ("invalid", None),
        ("", None),
    ],
)
def test_utc_time_start_parser_normalizes_supported_formats(
    media_panel_and_controller,
    value,
    expected,
):
    _panel, controller = media_panel_and_controller
    parsed = controller._parse_utc_time_start(value)
    assert (parsed.isoformat(sep=" ") if parsed is not None else None) == expected


@pytest.mark.gui
def test_utc_time_start_is_preserved_and_changes_source_identity(media_panel_and_controller):
    _panel, controller = media_panel_and_controller
    first = controller._normalize_media_source(
        {
            "type": "video",
            "path": "/tmp/example.mp4",
            "UTC_time_start": "2022-12-03 13:27:59.461000",
        }
    )
    second = dict(first, UTC_time_start="2022-12-03 13:28:00.461000")

    assert first["UTC_time_start"] == "2022-12-03 13:27:59.461000"
    assert controller._source_key(first) != controller._source_key(second)
    assert controller._source_key(first) != controller._source_key(
        {"type": "video", "path": "/tmp/example.mp4"}
    )


@pytest.mark.gui
def test_changing_utc_time_start_reloads_and_realigns_group(media_panel_and_controller, tmp_path):
    _panel, controller = media_panel_and_controller
    frames_path = tmp_path / "identity_frames.npy"
    np.save(frames_path, np.zeros((2, 4, 4, 3), dtype=np.uint8))
    first = {
        "type": "frames_npy",
        "path": str(frames_path),
        "fps": 25.0,
        "UTC_time_start": "2026-01-01 12:00:00",
    }
    second = dict(first, UTC_time_start="2026-01-01 12:00:05")

    controller.route_media_group([first], str(frames_path), False)
    first_group_key = controller._group_key
    first_origin = controller._sessions[0]["origin_utc"]
    controller.route_media_group([second], str(frames_path), False)

    assert controller._group_key != first_group_key
    assert controller._sessions[0]["origin_utc"] != first_origin
    assert controller._sessions[0]["origin_utc"].isoformat(sep=" ") == "2026-01-01 12:00:05"


@pytest.mark.gui
def test_explicit_utc_time_start_overrides_h5_origin(media_panel_and_controller, tmp_path):
    panel, controller = media_panel_and_controller
    h5_path = tmp_path / "override_origin.h5"
    _write_minimal_player_joints_h5(
        h5_path,
        [b"2026-01-01 12:00:00.000000", b"2026-01-01 12:00:00.040000"],
    )

    controller.route_media_group(
        [
            {
                "type": "player_joints_h5",
                "path": str(h5_path),
                "UTC_time_start": "2026-01-01 11:59:58.500000",
            }
        ],
        str(h5_path),
        False,
    )

    assert controller._sessions[0]["origin_utc"].isoformat(sep=" ") == "2026-01-01 11:59:58.500000"
    assert controller._global_origin_utc == controller._sessions[0]["origin_utc"]
    assert panel._viewer_panes[0].timing_label.text() == "UTC +0.000s"


@pytest.mark.gui
def test_video_utc_time_start_aligns_with_timestamped_h5(
    media_panel_and_controller,
    qtbot,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    h5_path = tmp_path / "aligned_joints.h5"
    _write_minimal_player_joints_h5(
        h5_path,
        [b"2022-12-03 13:28:00.000000", b"2022-12-03 13:28:00.040000"],
    )
    video_path = Path(__file__).resolve().parents[1] / "data" / "test_video_1.mp4"

    controller.route_media_group(
        [
            {
                "type": "video",
                "path": str(video_path),
                "UTC_time_start": "2022-12-03 13:27:59.461000",
            },
            {"type": "player_joints_h5", "path": str(h5_path)},
        ],
        str(video_path),
        False,
    )

    qtbot.waitUntil(lambda: controller._sessions[0]["duration_ms"] > 0, timeout=5000)
    assert controller._global_origin_utc.isoformat(sep=" ") == "2022-12-03 13:27:59.461000"
    assert controller._sessions[0]["offset_ms"] == 0
    assert controller._sessions[1]["offset_ms"] == 539


@pytest.mark.gui
def test_invalid_explicit_utc_time_start_forces_relative_warning(
    media_panel_and_controller,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    valid_path = tmp_path / "valid_origin.h5"
    invalid_path = tmp_path / "invalid_override.h5"
    timestamps = [b"2026-01-01 12:00:00.000000", b"2026-01-01 12:00:00.040000"]
    _write_minimal_player_joints_h5(valid_path, timestamps)
    _write_minimal_player_centroids_h5(invalid_path, timestamps)

    controller.route_media_group(
        [
            {"type": "player_joints_h5", "path": str(valid_path)},
            {
                "type": "player_centroids_h5",
                "path": str(invalid_path),
                "UTC_time_start": "not-a-time",
            },
        ],
        str(invalid_path),
        False,
    )

    invalid_record = controller._sessions[1]
    assert invalid_record["origin_utc"] is None
    assert invalid_record["utc_start_invalid"] is True
    assert invalid_record["offset_ms"] == 0
    assert panel._viewer_panes[1].timing_label.text() == "Relative ⚠ invalid UTC_time_start"
    assert "aligned as relative" in panel._viewer_panes[1].timing_label.toolTip()


@pytest.mark.gui
def test_sync_mode_freezes_group_and_controls_only_selected_h5(
    media_panel_and_controller,
    qtbot,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    first_path = tmp_path / "sync_first.h5"
    second_path = tmp_path / "sync_second.h5"
    timestamps = [
        b"2026-01-01 12:00:00.000000",
        b"2026-01-01 12:00:00.100000",
        b"2026-01-01 12:00:00.250000",
        b"2026-01-01 12:00:00.400000",
    ]
    _write_minimal_player_joints_h5(first_path, timestamps)
    _write_minimal_player_centroids_h5(second_path, timestamps)
    controller.route_media_group(
        [
            {"type": "player_joints_h5", "path": str(first_path)},
            {"type": "player_centroids_h5", "path": str(second_path)},
        ],
        str(first_path),
        False,
    )
    controller.set_position(100)
    frozen_first_position = controller._sessions[0]["controller"].current_position_ms()

    controller.enter_sync_mode(str(second_path))

    assert controller._sync_record is controller._sessions[1]
    assert controller._sync_anchor_utc.isoformat(sep=" ") == "2026-01-01 12:00:00.100000"
    assert panel.sync_bar.isVisible() is True
    assert panel._viewer_panes[1].property("syncing") is True
    assert controller.current_position_ms() == 100

    controller.play()
    qtbot.waitUntil(lambda: controller.current_position_ms() > 100, timeout=1000)
    controller.pause()
    assert controller._sessions[0]["controller"].current_position_ms() == frozen_first_position


@pytest.mark.gui
def test_viewer_go_to_start_seeks_shared_clock_to_modality_utc_origin(
    media_panel_and_controller,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    first_path = tmp_path / "go_start_first.h5"
    second_path = tmp_path / "go_start_second.h5"
    _write_minimal_player_joints_h5(
        first_path,
        [b"2026-01-01 12:00:00.000000", b"2026-01-01 12:00:01.000000"],
    )
    _write_minimal_player_centroids_h5(
        second_path,
        [b"2026-01-01 12:00:00.250000", b"2026-01-01 12:00:01.250000"],
    )
    controller.route_media_group(
        [
            {"type": "player_joints_h5", "path": str(first_path)},
            {"type": "player_centroids_h5", "path": str(second_path)},
        ],
        str(first_path),
        False,
    )

    assert all(pane._navigation_available for pane in panel._viewer_panes)
    panel._viewer_panes[1].goToStartRequested.emit(str(second_path))
    assert controller.current_position_ms() == 250

    panel._viewer_panes[1].goToEndRequested.emit(str(second_path))
    assert controller.current_position_ms() == 1250

    panel._viewer_panes[0].goToStartRequested.emit(str(first_path))
    assert controller.current_position_ms() == 0

    panel._viewer_panes[0].goToEndRequested.emit(str(first_path))
    assert controller.current_position_ms() == 1000


@pytest.mark.gui
def test_sync_mode_frame_step_apply_and_cancel(media_panel_and_controller, tmp_path):
    panel, controller = media_panel_and_controller
    first_path = tmp_path / "step_first.h5"
    second_path = tmp_path / "step_second.h5"
    timestamps = [
        b"2026-01-01 12:00:00.000000",
        b"2026-01-01 12:00:00.100000",
        b"2026-01-01 12:00:00.250000",
    ]
    _write_minimal_player_joints_h5(first_path, timestamps)
    _write_minimal_player_centroids_h5(second_path, timestamps)
    sources = [
        {"type": "player_joints_h5", "path": str(first_path)},
        {"type": "player_centroids_h5", "path": str(second_path)},
    ]
    controller.route_media_group(sources, str(first_path), False)
    controller.set_position(100)
    controller.enter_sync_mode(str(second_path))

    controller.step_sync_frame(1)
    assert controller.current_position_ms() == 250
    controller.step_sync_frame(-1)
    assert controller.current_position_ms() == 100

    emitted = []
    controller.inputUtcStartMutationRequested.connect(
        lambda path, utc_text: emitted.append((path, utc_text))
    )
    controller.set_position(250)
    controller.apply_sync_mode()

    assert emitted == [(str(second_path), "2026-01-01 11:59:59.850000")]
    assert controller._sync_record is None
    assert panel.sync_bar.isVisible() is False
    assert controller.is_playing() is False

    controller.route_media_group(sources, str(first_path), False)
    controller.set_position(100)
    controller.enter_sync_mode(str(second_path))
    controller.set_position(250)
    controller.focus_source(str(first_path))
    assert controller._focused_path == str(first_path)
    controller.cancel_sync_mode()
    assert controller._sync_record is None
    assert controller.current_position_ms() == 100
    assert len(emitted) == 1

    controller.enter_sync_mode(str(second_path))
    controller.set_position(250)
    controller.route_media_group(sources, str(first_path), False)
    assert controller._sync_record is None
    assert panel.sync_bar.isVisible() is False
    assert len(emitted) == 1


@pytest.mark.gui
def test_sync_availability_requires_two_playable_inputs_and_utc_reference(
    media_panel_and_controller,
    tmp_path,
):
    panel, controller = media_panel_and_controller
    first_frames = tmp_path / "first.npy"
    second_frames = tmp_path / "second.npy"
    np.save(first_frames, np.zeros((2, 4, 4, 3), dtype=np.uint8))
    np.save(second_frames, np.zeros((2, 4, 4, 3), dtype=np.uint8))

    controller.route_media_group(
        [{"type": "frames_npy", "path": str(first_frames), "fps": 25.0}],
        str(first_frames),
        False,
    )
    assert panel._viewer_panes[0]._sync_available is False
    assert "at least two" in panel._viewer_panes[0]._sync_unavailable_reason

    controller.route_media_group(
        [
            {"type": "frames_npy", "path": str(first_frames), "fps": 25.0},
            {"type": "frames_npy", "path": str(second_frames), "fps": 25.0},
        ],
        str(first_frames),
        False,
    )
    assert all(pane._sync_available is False for pane in panel._viewer_panes)
    assert "absolute UTC" in panel._viewer_panes[0]._sync_unavailable_reason

    utc_sources = [
        {
            "type": "frames_npy",
            "path": str(first_frames),
            "fps": 25.0,
            "UTC_time_start": "2026-01-01 12:00:00",
        },
        {"type": "frames_npy", "path": str(second_frames), "fps": 25.0},
    ]
    controller.route_media_group(utc_sources, str(first_frames), False)
    assert all(pane._sync_available is True for pane in panel._viewer_panes)


@pytest.mark.gui
def test_sync_apply_emits_only_the_new_absolute_input_origin(
    media_panel_and_controller,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    utc_frames = tmp_path / "utc_frames.npy"
    relative_frames = tmp_path / "relative_frames.npy"
    np.save(utc_frames, np.zeros((3, 4, 4, 3), dtype=np.uint8))
    np.save(relative_frames, np.zeros((3, 4, 4, 3), dtype=np.uint8))
    controller.route_media_group(
        [
            {
                "type": "frames_npy",
                "path": str(utc_frames),
                "fps": 10.0,
                "UTC_time_start": "2026-01-01 12:00:00.000000",
            },
            {"type": "frames_npy", "path": str(relative_frames), "fps": 10.0},
        ],
        str(utc_frames),
        False,
    )
    controller.set_position(100)
    controller.enter_sync_mode(str(utc_frames))
    controller.set_position(0)

    emitted = []
    controller.inputUtcStartMutationRequested.connect(
        lambda path, utc_text: emitted.append((path, utc_text))
    )
    controller.apply_sync_mode()

    assert emitted == [
        (str(utc_frames), "2026-01-01 12:00:00.100000"),
    ]


@pytest.mark.gui
def test_viewer_manual_utc_prompts_normalize_and_remove(
    media_panel_and_controller,
    monkeypatch,
):
    panel, _controller = media_panel_and_controller
    pane = panel._viewer_panes[0]
    pane.configure(
        {
            "type": "video",
            "path": "/tmp/example.mp4",
            "UTC_time_start": "2026-01-01T14:00:00+02:00",
        }
    )

    entered_defaults = []
    monkeypatch.setattr(
        "ui.media_player.QInputDialog.getText",
        lambda *args, **kwargs: (
            entered_defaults.append(kwargs.get("text"))
            or "2026-01-01T15:00:01.250000+03:00",
            True,
        ),
    )
    set_requests = []
    pane.utcStartSetRequested.connect(
        lambda path, utc: set_requests.append((path, utc))
    )
    pane._prompt_utc_start()

    assert entered_defaults == ["2026-01-01 12:00:00.000000"]
    assert set_requests == [
        ("/tmp/example.mp4", "2026-01-01 12:00:01.250000")
    ]

    monkeypatch.setattr(
        "ui.media_player.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    remove_requests = []
    pane.utcStartRemoveRequested.connect(remove_requests.append)
    pane._confirm_remove_utc_start()
    assert remove_requests == ["/tmp/example.mp4"]


@pytest.mark.gui
def test_manual_utc_requests_pause_and_preserve_absolute_anchor(
    media_panel_and_controller,
    tmp_path,
):
    _panel, controller = media_panel_and_controller
    frames_path = tmp_path / "frames.npy"
    np.save(frames_path, np.zeros((5, 4, 4, 3), dtype=np.uint8))
    controller.route_media_group(
        [
            {
                "type": "frames_npy",
                "path": str(frames_path),
                "fps": 10.0,
                "UTC_time_start": "2026-01-01 12:00:00.000000",
            }
        ],
        str(frames_path),
        False,
    )
    controller.set_position(200)

    set_requests = []
    controller.inputUtcStartMutationRequested.connect(
        lambda path, utc: set_requests.append((path, utc))
    )
    controller.request_manual_utc_start(
        str(frames_path), "2026-01-01T14:00:01+02:00"
    )
    assert set_requests == [
        (str(frames_path), "2026-01-01 12:00:01.000000")
    ]
    assert controller._pending_restore_anchor_utc.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    ) == "2026-01-01 12:00:00.200000"
    assert controller.is_playing() is False
