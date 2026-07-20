from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from PyQt6.QtCore import Qt

from controllers.media_controller import MediaController
from ui.media_player import MediaCenterPanel


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
