"""
Focused Dataset Explorer controller and panel tests using minimal fixtures.
"""

import pytest
import h5py
import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QSettings, Qt, QTimer
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from controllers.dataset_explorer_controller import DatasetExplorerController
from ui.dataset_explorer_panel import DatasetExplorerPanel


@pytest.fixture
def explorer_panel_and_controller(qtbot, tmp_path):
    panel = DatasetExplorerPanel(
        tree_title="Data",
        filter_items=["Show All", "Show Labelled", "Show Smart Labelled", "Show Not Labelled"],
        clear_text="Clear All",
        enable_context_menu=True,
    )
    qtbot.addWidget(panel)

    controller = DatasetExplorerController(panel=panel, tree_model=panel.tree_model)
    controller.settings = QSettings(str(tmp_path / "dataset_explorer_test.ini"), QSettings.Format.IniFormat)
    return panel, controller


def _known_row(panel, key: str) -> int:
    for row in range(panel.table_header_known.rowCount()):
        key_item = panel.table_header_known.item(row, 0)
        if key_item and key_item.text() == key:
            return row
    raise AssertionError(f"Missing known header row: {key}")


def _large_dataset(sample_count=11_301):
    return {
        "version": "2.0",
        "labels": {"action": {"type": "single_label", "labels": ["pass"]}},
        "data": [
            {
                "id": f"clip_{index + 1}",
                "inputs": [],
                "labels": {"action": {"label": "pass"}} if index % 2 == 0 else {},
            }
            for index in range(sample_count)
        ],
    }


def test_large_dataset_exposes_only_bounded_sorted_pages(
    explorer_panel_and_controller,
    qtbot,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    rebuild_calls = {"count": 0}
    original_rebuild = controller._rebuild_runtime_index

    def counted_rebuild():
        rebuild_calls["count"] += 1
        return original_rebuild()

    controller._rebuild_runtime_index = counted_rebuild
    emitted_summaries = []
    controller.classificationActionListChanged.connect(emitted_summaries.append)

    sample_count = 62_159
    assert controller.load_project(_large_dataset(sample_count), str(tmp_path / "large.json"))
    assert rebuild_calls["count"] == 1
    assert panel.tree_model.rowCount() == panel.tree_model.PAGE_SIZE
    assert panel.tree_model.index(0, 0).data() == "clip_1"
    assert panel.tree_model.index(1, 0).data() == "clip_2"
    assert emitted_summaries and "sample_ref" not in emitted_summaries[-1][0]
    assert panel.page_range_label.text() == "Showing 1–500 of 62,159 · scroll for more"

    heartbeat_rows = []
    QTimer.singleShot(0, lambda: heartbeat_rows.append(panel.tree_model.rowCount()))
    qtbot.waitUntil(lambda: bool(heartbeat_rows), timeout=1000)
    assert heartbeat_rows == [panel.tree_model.PAGE_SIZE]
    qtbot.wait(50)
    assert panel.tree_model.rowCount() == panel.tree_model.PAGE_SIZE

    assert panel.tree_model.next_page()
    assert panel.tree_model.index(0, 0).data() == "clip_501"
    assert panel.tree_model.index(1, 0).data() == "clip_502"

    assert panel.tree_model.set_page(panel.tree_model.page_count() - 1)
    assert panel.tree_model.rowCount() == sample_count % panel.tree_model.PAGE_SIZE
    assert panel.tree_model.index(0, 0).data() == "clip_62001"


def test_bounded_page_filter_and_reset(
    explorer_panel_and_controller,
    qtbot,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    assert controller.load_project(_large_dataset(), str(tmp_path / "large.json"))

    controller.handle_filter_change(1, selection_fallback="clear_selection")
    assert panel.tree_model.rowCount() == panel.tree_model.PAGE_SIZE
    assert panel.tree_model.index(0, 0).data() == "clip_1"
    assert panel.tree_model.index(1, 0).data() == "clip_3"

    controller.reset(full_reset=True)
    qtbot.wait(50)
    assert panel.tree_model.rowCount() == 0


def test_visible_sample_routes_media_without_exposing_later_pages(
    explorer_panel_and_controller,
    qtbot,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    dataset = _large_dataset(sample_count=2_000)
    for index, sample in enumerate(dataset["data"]):
        sample["inputs"] = [{"type": "video", "path": f"clips/{index + 1}.mp4"}]

    routed = []
    controller.mediaSelectionRouteRequested.connect(
        lambda sources, focused_path: routed.append(
            (panel.tree_model.rowCount(), sources, focused_path)
        )
    )

    assert controller.load_project(dataset, str(tmp_path / "large.json"))
    assert panel.tree_model.rowCount() == panel.tree_model.PAGE_SIZE

    second_index = panel.tree_model.index(1, 0)
    QTimer.singleShot(0, lambda: panel.tree.setCurrentIndex(second_index))
    qtbot.waitUntil(lambda: bool(routed), timeout=1000)

    visible_when_routed, sources, focused_path = routed[-1]
    assert visible_when_routed == panel.tree_model.PAGE_SIZE
    assert sources[0]["path"].endswith("clips/2.mp4")
    assert focused_path == ""
    qtbot.wait(50)
    assert panel.tree_model.rowCount() == panel.tree_model.PAGE_SIZE


def _send_boundary_wheel(widget, delta):
    event = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(widget, event)


def test_boundary_wheel_changes_page_and_preserves_off_page_playback(
    explorer_panel_and_controller,
    qtbot,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    dataset = _large_dataset(sample_count=1_200)
    for index, sample in enumerate(dataset["data"]):
        sample["inputs"] = [{"type": "video", "path": f"clips/{index + 1}.mp4"}]

    routes = []
    stops = []
    controller.mediaSelectionRouteRequested.connect(lambda *args: routes.append(args))
    controller.mediaStopRequested.connect(lambda: stops.append(True))
    assert controller.load_project(dataset, str(tmp_path / "large.json"))

    panel.tree.setCurrentIndex(panel.tree_model.index(0, 0))
    assert controller.current_selected_sample_id == "clip_1"
    initial_route_count = len(routes)

    panel.show()
    qtbot.waitExposed(panel)
    scroll_bar = panel.tree.verticalScrollBar()
    scroll_bar.setValue(scroll_bar.maximum())
    _send_boundary_wheel(panel.tree.viewport(), -120)
    qtbot.waitUntil(lambda: panel.tree_model.page_number() == 1, timeout=1000)

    assert panel.tree_model.index(0, 0).data() == "clip_501"
    assert not panel.tree.currentIndex().isValid()
    assert controller.current_selected_sample_id == "clip_1"
    assert len(routes) == initial_route_count
    assert stops == []

    controller.handle_active_mode_changed(0)
    assert controller.current_selected_sample_id == "clip_1"
    assert len(routes) == initial_route_count
    assert stops == []

    scroll_bar.setValue(scroll_bar.minimum())
    _send_boundary_wheel(panel.tree.viewport(), 120)
    qtbot.waitUntil(lambda: panel.tree_model.page_number() == 0, timeout=1000)
    assert panel.tree.currentIndex().data() == "clip_1"
    assert len(routes) == initial_route_count
    assert stops == []


def test_next_sample_navigation_crosses_page_boundary_once(
    explorer_panel_and_controller,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    dataset = _large_dataset(sample_count=1_200)
    for index, sample in enumerate(dataset["data"]):
        sample["inputs"] = [{"type": "video", "path": f"clips/{index + 1}.mp4"}]

    routes = []
    controller.mediaSelectionRouteRequested.connect(lambda *args: routes.append(args))
    assert controller.load_project(dataset, str(tmp_path / "large.json"))
    panel.tree.setCurrentIndex(panel.tree_model.index(499, 0))
    route_count = len(routes)

    controller.navigate_samples(1)

    assert panel.tree_model.page_number() == 1
    assert panel.tree.currentIndex().data() == "clip_501"
    assert controller.current_selected_sample_id == "clip_501"
    assert len(routes) == route_count + 1


def test_filter_restores_eligible_selection_on_its_matching_page(
    explorer_panel_and_controller,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    assert controller.load_project(_large_dataset(sample_count=1_200), str(tmp_path / "large.json"))
    selected = controller._top_level_index_for_sample("clip_1001")
    panel.tree.setCurrentIndex(selected)
    assert controller.current_selected_sample_id == "clip_1001"

    controller.handle_filter_change(1)

    assert panel.tree_model.page_number() == 1
    assert panel.tree.currentIndex().data() == "clip_1001"
    assert controller.current_selected_sample_id == "clip_1001"
    assert panel.page_range_label.text() == "Showing 501–600 of 600 · scroll for more"


def test_write_promotes_and_reprojects_absolute_temporal_annotations(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    controller.current_working_directory = str(tmp_path)
    controller.dataset_json = {
        "version": "2.0",
        "labels": {},
        "data": [
            {
                "id": "sample-1",
                "inputs": [
                    {
                        "type": "video",
                        "path": "clip.mp4",
                        "UTC_time_start": "2026-01-01T12:00:00Z",
                    }
                ],
                "events": [
                    {"head": "action", "label": "pass", "position_ms": 1000},
                    {
                        "head": "action",
                        "label": "shot",
                        "position_ms": 9999,
                        "timestamp_utc": "2026-01-01T14:00:02.500000+02:00",
                    },
                    {
                        "head": "action",
                        "label": "bad",
                        "position_ms": 3000,
                        "timestamp_utc": "not-a-time",
                    },
                ],
                "dense_captions": [
                    {"position_ms": 1500, "lang": "en", "text": "caption"}
                ],
            }
        ],
    }

    written = controller._dataset_json_for_write(str(tmp_path / "saved.json"))
    sample = written["data"][0]

    assert sample["events"][0]["timestamp_utc"] == "2026-01-01 12:00:01.000000"
    assert sample["events"][1]["timestamp_utc"] == "2026-01-01 12:00:02.500000"
    assert sample["events"][1]["position_ms"] == 2500
    assert sample["events"][2] == {
        "head": "action",
        "label": "bad",
        "position_ms": 3000,
        "timestamp_utc": "not-a-time",
    }
    assert sample["dense_captions"][0]["timestamp_utc"] == (
        "2026-01-01 12:00:01.500000"
    )


def test_write_uses_backend_h5_timestamp_as_a_genuine_origin(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    h5_path = tmp_path / "tracking.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset(
            "timestamp_utc",
            data=np.asarray([b"2026-01-01 12:00:00.500000"]),
        )

    controller.current_working_directory = str(tmp_path)
    controller.dataset_json = {
        "version": "2.0",
        "labels": {},
        "data": [
            {
                "id": "sample-h5",
                "inputs": [
                    {"type": "player_joints_h5", "path": str(h5_path)}
                ],
                "events": [
                    {"head": "action", "label": "pass", "position_ms": 750}
                ],
            }
        ],
    }

    written = controller._dataset_json_for_write(str(tmp_path / "saved.json"))
    assert written["data"][0]["events"][0]["timestamp_utc"] == (
        "2026-01-01 12:00:01.250000"
    )


def test_removing_h5_utc_override_restores_backend_origin(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    h5_path = tmp_path / "tracking.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset(
            "timestamp_utc",
            data=np.asarray([b"2026-01-01 12:00:00.500000"]),
        )
    controller.current_working_directory = str(tmp_path)
    controller.dataset_json = {
        "version": "2.0",
        "labels": {},
        "data": [
            {
                "id": "sample-h5",
                "inputs": [
                    {
                        "type": "player_joints_h5",
                        "path": str(h5_path),
                        "UTC_time_start": "2026-01-01 11:59:59.000000",
                    }
                ],
                "events": [
                    {
                        "head": "action",
                        "label": "pass",
                        "position_ms": 2500,
                        "timestamp_utc": "2026-01-01 12:00:01.500000",
                    }
                ],
            }
        ],
    }
    controller._rebuild_runtime_index()

    assert controller._remove_input_utc_time_start(
        "sample-h5",
        str(h5_path),
        "2026-01-01 11:59:59.000000",
    )
    sample = controller.get_sample("sample-h5")
    assert "UTC_time_start" not in sample["inputs"][0]
    assert sample["events"][0]["timestamp_utc"] == "2026-01-01 12:00:01.500000"
    assert sample["events"][0]["position_ms"] == 1000


def _unknown_row(panel, key: str) -> int:
    for row in range(panel.table_header_unknown.rowCount()):
        key_item = panel.table_header_unknown.item(row, 0)
        if key_item and key_item.text() == key:
            return row
    raise AssertionError(f"Missing unknown header row: {key}")


def test_normalize_dataset_json_inserts_defaults_preserves_unknowns_and_fixes_ids(
    explorer_panel_and_controller,
):
    _panel, controller = explorer_panel_and_controller
    raw = {
        "custom_root": {"keep": True},
        "metadata": "not-a-dict",
        "modalities": "video",
        "data": [
            {
                "id": "clip_dup",
                "inputs": [{"path": "clips/one.mp4", "type": "video"}],
                "metadata": "bad",
                "events": [{"head": "action", "label": "pass", "position_ms": "1001"}],
                "custom_sample": {"keep": 1},
            },
            {
                "id": "clip_dup",
                "inputs": [{"path": "clips/two.mp4", "type": "video"}],
            },
            {
                "inputs": [{"path": "clips/three.mp4", "type": "video"}],
            },
        ],
    }

    normalized, error = controller._normalize_dataset_json(raw)

    assert error == ""
    assert normalized["version"] == "2.0"
    assert "task" not in normalized
    assert normalized["metadata"] == {}
    assert normalized["modalities"] == ["video"]
    assert "questions" not in normalized
    assert normalized["custom_root"] == {"keep": True}
    assert [sample["id"] for sample in normalized["data"]] == ["clip_dup", "clip_dup__2", "sample_3"]
    assert normalized["data"][0]["events"][0]["position_ms"] == 1001
    assert normalized["data"][0]["metadata"] == {}
    assert normalized["data"][0]["custom_sample"] == {"keep": 1}


def test_normalize_dataset_json_rejects_invalid_root_and_non_list_data(explorer_panel_and_controller):
    _panel, controller = explorer_panel_and_controller

    normalized, error = controller._normalize_dataset_json(["not", "a", "dict"])
    assert normalized is None
    assert error == "Root JSON must be an object."

    normalized, error = controller._normalize_dataset_json({"data": {}})
    assert normalized is None
    assert error == "Top-level 'data' must be a list."


def test_normalize_dataset_json_drops_legacy_vqa_and_smart_keys(explorer_panel_and_controller):
    _panel, controller = explorer_panel_and_controller
    raw = {
        "questions": [
            {"id": "q1", "question": "How are you?"},
            {"id": "q1", "question": "duplicate"},
            {"id": "", "question": "invalid"},
        ],
        "data": [
            {
                "id": "clip_1",
                "inputs": [{"path": "clips/one.mp4", "type": "video"}],
                "labels": {"phase": {"label": "build"}},
                "events": [{"head": "ball_action", "label": "pass", "position_ms": 1000}],
                "answers": [
                    {"question_id": "q1", "answer": "ok"},
                    {"question_id": "q2", "answer": "unknown-id"},
                    {"question_id": "q1", "answer": "duplicate-id"},
                ],
                "smart_label": {"label": "shot"},
                "smart_event": {"head": "ball_action", "label": "shot", "position_ms": 1200},
                "smart_labels": {"action": {"label": "shot", "conf_dict": {"shot": 0.72}}},
                "smart_events": [{"head": "ball_action", "label": "shot", "position_ms": 2000}],
            }
        ],
    }

    normalized, error = controller._normalize_dataset_json(raw)
    assert error == ""
    sample = normalized["data"][0]
    assert "questions" not in normalized
    assert "answers" not in sample
    assert sample["labels"]["phase"]["label"] == "build"
    assert "smart_labels" not in sample
    assert "smart_events" not in sample
    assert "smart_label" not in sample
    assert "smart_event" not in sample


def test_dataset_json_for_write_rewrites_relative_paths_and_strips_empty_fields(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    project_root = tmp_path / "project"
    save_root = tmp_path / "exports"
    media_dir = project_root / "clips"
    media_dir.mkdir(parents=True)
    save_root.mkdir(parents=True)
    media_path = media_dir / "clip.mp4"
    media_path.write_bytes(b"video")

    controller.project_root = str(project_root)
    controller.current_working_directory = str(project_root)
    controller.dataset_json = {
        "version": "2.0",
        "date": "2026-04-08",
        "task": "video_annotation",
        "dataset_name": "write_test",
        "description": None,
        "modalities": ["video"],
        "metadata": {},
        "labels": {},
        "questions": [{"id": "q1", "question": "Legacy question"}],
        "custom_root": {"keep": True},
        "data": [
            {
                "id": "clip_1",
                "inputs": [{"path": "clips/clip.mp4", "type": "video"}],
                "labels": {},
                "events": [],
                "captions": [],
                "dense_captions": [],
                "answers": [
                    {"question": "How are you?", "answers": ["I am fine.", "I am good."]},
                    {"question": "How are you?", "answers": ["Still fine."]},
                    {"question": "", "answers": ["drop"]},
                    {"question_id": "q1", "answer": "drop legacy"},
                ],
                "metadata": {},
                "custom_sample": {"keep": 1},
            }
        ],
    }

    written = controller._dataset_json_for_write(str(save_root / "dataset.json"))

    assert written["description"] == ""
    assert written["metadata"] == {}
    assert written["modalities"] == ["video"]
    assert written["task"] == "video_annotation"
    assert written["custom_root"] == {"keep": True}
    assert "questions" not in written
    assert written["data"][0]["inputs"][0]["path"] == "../project/clips/clip.mp4"
    assert "labels" not in written["data"][0]
    assert "events" not in written["data"][0]
    assert "captions" not in written["data"][0]
    assert "dense_captions" not in written["data"][0]
    assert written["data"][0]["answers"] == [
        {"question": "How are you?", "answers": ["I am fine.", "I am good.", "Still fine."]}
    ]
    assert "metadata" not in written["data"][0]
    assert written["data"][0]["custom_sample"] == {"keep": 1}


def test_available_mode_indices_for_sample_prefers_fixed_order(explorer_panel_and_controller):
    _panel, controller = explorer_panel_and_controller
    sample = {
        "labels": {"action": {"label": "shot", "confidence_score": 0.9}},
        "events": [
            {"head": "action", "label": "pass", "position_ms": 1000},
            {"head": "action", "label": "shot", "position_ms": 2000, "confidence_score": 0.7},
        ],
        "captions": [{"lang": "en", "text": "caption"}],
        "dense_captions": [{"position_ms": 1500, "lang": "en", "text": "dense"}],
        "answers": [{"question": "How are you?", "answers": ["answer"]}],
    }
    assert controller._available_mode_indices_for_sample(sample) == [0, 1, 2, 3, 4]
    assert controller._available_mode_indices_for_sample({"events": [{"position_ms": 1}]}) == [1]
    assert controller._available_mode_indices_for_sample({"captions": [{"text": ""}]}) == []
    assert controller._available_mode_indices_for_sample({"answers": [{"question": "Q", "answers": ["x"]}]}) == [4]
    assert controller._available_mode_indices_for_sample({"answers": [{"question_id": "q1", "answer": "x"}]}) == []


def test_dataset_tree_sample_label_shows_average_smart_confidence_suffix(
    explorer_panel_and_controller,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    controller.project_root = str(tmp_path)
    controller.current_working_directory = str(tmp_path)
    controller.dataset_json = {
        "data": [
            {
                "id": "clip_1",
                "inputs": [{"path": "clips/one.mp4", "type": "video"}],
                "labels": {"action": {"label": "shot", "confidence_score": 0.8}},
                "events": [
                    {"head": "ball_action", "label": "pass", "position_ms": 1000},
                    {"head": "ball_action", "label": "shot", "position_ms": 2000, "confidence_score": 0.7},
                ],
            },
            {
                "id": "clip_2",
                "inputs": [{"path": "clips/two.mp4", "type": "video"}],
                "labels": {"action": {"label": "pass"}},
            },
        ]
    }

    controller.populate_tree()

    assert panel.tree_model.columnCount() == 1
    assert panel.tree.isHeaderHidden()
    assert panel.tree_model.index(0, 0).data() == "clip_1 (conf:0.75)"
    assert panel.tree_model.index(1, 0).data() == "clip_2"
    assert controller._average_smart_confidence_for_sample(controller.get_sample("clip_1")) == pytest.approx(0.75)
    assert controller._average_smart_confidence_for_sample(controller.get_sample("clip_2")) is None


def test_dataset_tree_sample_label_keeps_natural_sample_sort(
    explorer_panel_and_controller,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    controller.project_root = str(tmp_path)
    controller.current_working_directory = str(tmp_path)
    controller.dataset_json = {
        "data": [
            {
                "id": "clip_10",
                "inputs": [{"path": "clips/ten.mp4", "type": "video"}],
                "events": [{"head": "action", "label": "pass", "position_ms": 1, "confidence_score": 0.2}],
            },
            {
                "id": "clip_1",
                "inputs": [{"path": "clips/one.mp4", "type": "video"}],
            },
            {
                "id": "clip_2",
                "inputs": [{"path": "clips/two.mp4", "type": "video"}],
                "labels": {"action": {"label": "shot", "confidence_score": 0.85}},
            },
        ]
    }

    controller.populate_tree()
    panel.tree_model.sort(0, Qt.SortOrder.AscendingOrder)

    assert [panel.tree_model.index(row, 0).data() for row in range(3)] == [
        "clip_1",
        "clip_2 (conf:0.85)",
        "clip_10 (conf:0.20)",
    ]


def test_dataset_tree_confidence_sort_checkbox_defaults_unchecked(explorer_panel_and_controller):
    panel, _controller = explorer_panel_and_controller

    assert panel.sort_conf_checkbox.text() == "Sort by conf"
    assert panel.sort_conf_checkbox.isChecked() is False


def test_dataset_tree_confidence_sort_checkbox_toggles_order(
    explorer_panel_and_controller,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    controller.project_root = str(tmp_path)
    controller.current_working_directory = str(tmp_path)
    controller.dataset_json = {
        "data": [
            {
                "id": "clip_10",
                "inputs": [{"path": "clips/ten.mp4", "type": "video"}],
                "labels": {"action": {"label": "pass", "confidence_score": 0.2}},
            },
            {
                "id": "clip_1",
                "inputs": [{"path": "clips/one.mp4", "type": "video"}],
            },
            {
                "id": "clip_2",
                "inputs": [{"path": "clips/two.mp4", "type": "video"}],
                "labels": {"action": {"label": "shot", "confidence_score": 0.85}},
            },
        ]
    }

    controller.populate_tree()
    assert [panel.tree_model.index(row, 0).data() for row in range(3)] == [
        "clip_1",
        "clip_2 (conf:0.85)",
        "clip_10 (conf:0.20)",
    ]

    panel.sort_conf_checkbox.setChecked(True)
    assert [panel.tree_model.index(row, 0).data() for row in range(3)] == [
        "clip_2 (conf:0.85)",
        "clip_10 (conf:0.20)",
        "clip_1",
    ]

    panel.sort_conf_checkbox.setChecked(False)
    assert [panel.tree_model.index(row, 0).data() for row in range(3)] == [
        "clip_1",
        "clip_2 (conf:0.85)",
        "clip_10 (conf:0.20)",
    ]


def test_dataset_tree_confidence_sort_reorders_after_confidence_refresh(
    explorer_panel_and_controller,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    controller.project_root = str(tmp_path)
    controller.current_working_directory = str(tmp_path)
    controller.dataset_json = {
        "data": [
            {
                "id": "clip_1",
                "inputs": [{"path": "clips/one.mp4", "type": "video"}],
            },
            {
                "id": "clip_2",
                "inputs": [{"path": "clips/two.mp4", "type": "video"}],
                "labels": {"action": {"label": "shot", "confidence_score": 0.5}},
            },
        ]
    }

    controller.populate_tree()
    panel.sort_conf_checkbox.setChecked(True)
    assert [panel.tree_model.index(row, 0).data() for row in range(2)] == [
        "clip_2 (conf:0.50)",
        "clip_1",
    ]

    sample = controller.get_sample("clip_1")
    sample["labels"] = {"action": {"label": "pass", "confidence_score": 0.9}}
    controller.update_item_status(controller.get_path_by_id("clip_1"))

    assert [panel.tree_model.index(row, 0).data() for row in range(2)] == [
        "clip_1 (conf:0.90)",
        "clip_2 (conf:0.50)",
    ]


def test_dataset_tree_child_inputs_keep_roles_and_no_conf_suffix(
    explorer_panel_and_controller,
    tmp_path,
):
    panel, controller = explorer_panel_and_controller
    controller.project_root = str(tmp_path)
    controller.current_working_directory = str(tmp_path)
    controller.dataset_json = {
        "data": [
            {
                "id": "multi",
                "inputs": [
                    {"path": "clips/view_1.mp4", "type": "video"},
                    {"path": "clips/view_2.mp4", "type": "video"},
                ],
                "labels": {"action": {"label": "shot", "confidence_score": 0.9}},
            }
        ]
    }

    controller.populate_tree()

    parent = panel.tree_model.index(0, 0)
    child_name = panel.tree_model.index(0, 0, parent)
    assert child_name.isValid()
    assert child_name.data(panel.tree_model.DataIdRole) == "multi"
    assert child_name.data() == "view_1.mp4"


def test_dataset_tree_rename_strips_conf_suffix(explorer_panel_and_controller, qtbot):
    panel, controller = explorer_panel_and_controller
    controller.dataset_json = {"labels": {}, "data": [{"id": "clip_1", "inputs": []}]}
    controller.populate_tree()
    rename_requests = []
    panel.tree_model.renameRequested.connect(lambda old, new: rename_requests.append((old, new)))

    index = panel.tree_model.index(0, 0)
    assert panel.tree_model.setData(index, "renamed_clip (conf:0.75)", Qt.ItemDataRole.EditRole)
    qtbot.waitUntil(lambda: bool(rename_requests))

    assert rename_requests == [("clip_1", "renamed_clip")]


def test_group_selected_files_and_sample_id_rules(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    group_a = tmp_path / "group_a"
    group_b = tmp_path / "group_b"
    group_a.mkdir()
    group_b.mkdir()

    file_a1 = str(group_a / "view_1.mp4")
    file_a2 = str(group_a / "view_2.mp4")
    file_b1 = str(group_b / "view_1.mp4")

    assert controller._group_selected_files([file_a1, file_a2]) == [[file_a1, file_a2]]
    grouped = controller._group_selected_files([file_a2, file_b1, file_a1])
    assert grouped == [[file_a1, file_a2], [file_b1]]
    assert controller._sample_id_from_group([file_a1]) == "view_1"
    assert controller._sample_id_from_group([file_a1, file_a2]) == "group_a"
    assert controller._sample_id_from_group([file_b1]) == "view_1"


def test_source_groups_from_selected_paths_maps_files_to_single_and_folders_to_multi(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    single_file = tmp_path / "single.mp4"
    single_file.write_bytes(b"media")

    group_dir = tmp_path / "group_dir"
    group_dir.mkdir()
    group_view_2 = group_dir / "view_2.mp4"
    group_view_1 = group_dir / "view_1.mp4"
    ignored = group_dir / "notes.txt"
    group_view_2.write_bytes(b"media")
    group_view_1.write_bytes(b"media")
    ignored.write_text("ignore", encoding="utf-8")

    source_groups = controller._source_groups_from_selected_paths(
        [str(single_file), str(group_dir)]
    )

    assert source_groups == [
        [str(single_file)],
        [str(group_view_1), str(group_view_2)],
    ]


def test_panel_header_editor_flags_and_raw_json_widget_are_configured(explorer_panel_and_controller):
    panel, _controller = explorer_panel_and_controller
    panel.set_header_rows(
        known={
            "version": "2.0",
            "metadata": {"source": "pytest"},
        },
        unknown={
            "custom_owner": "qa-team",
            "task": "video_annotation",
            "modalities": ["video"],
        },
        draft={},
    )

    metadata_item = panel.table_header_known.item(_known_row(panel, "metadata"), 1)
    owner_item = panel.table_header_unknown.item(_unknown_row(panel, "custom_owner"), 1)
    task_item = panel.table_header_unknown.item(_unknown_row(panel, "task"), 1)
    modalities_item = panel.table_header_unknown.item(_unknown_row(panel, "modalities"), 1)

    assert not bool(metadata_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert not bool(modalities_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert not bool(owner_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert not bool(task_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert panel.json_raw_text.isReadOnly() is True


def test_panel_nested_json_edit_updates_draft_and_emits_signal(
    explorer_panel_and_controller,
):
    panel, _controller = explorer_panel_and_controller
    panel.set_header_rows(
        known={"metadata": {"source": "pytest"}},
        unknown={},
        draft={},
    )

    draft_events = []
    panel.headerDraftChanged.connect(draft_events.append)

    panel._open_json_value_dialog = lambda key, current_value: {"source": "updated", "owner": "qa"}
    panel._on_known_header_cell_double_clicked(_known_row(panel, "metadata"), 1)

    assert panel.get_staged_header_draft() == {"metadata": {"source": "updated", "owner": "qa"}}
    assert draft_events[-1] == {"metadata": {"source": "updated", "owner": "qa"}}
    assert panel.table_header_known.item(_known_row(panel, "metadata"), 1).text().startswith("{")


def test_panel_open_json_value_dialog_rejects_invalid_json_and_returns_missing(
    explorer_panel_and_controller,
    monkeypatch,
):
    panel, _controller = explorer_panel_and_controller

    exec_results = iter([QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected])
    warning_calls = {"count": 0}

    monkeypatch.setattr("ui.dataset_explorer_panel.QDialog.exec", lambda self: next(exec_results))
    monkeypatch.setattr("ui.dataset_explorer_panel.QPlainTextEdit.toPlainText", lambda self: "{invalid json")
    monkeypatch.setattr(
        "ui.dataset_explorer_panel.QMessageBox.warning",
        lambda *args, **kwargs: warning_calls.__setitem__("count", warning_calls["count"] + 1)
        or QMessageBox.StandardButton.Ok,
    )

    result = panel._open_json_value_dialog("metadata", {"source": "pytest"})

    assert result is panel._MISSING
    assert warning_calls["count"] == 1


def test_recent_path_helpers_normalize_and_dedupe_equivalent_paths(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    dataset_path = (tmp_path / "datasets" / "demo.json").resolve()
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text("{}", encoding="utf-8")

    controller._add_recent_project(str(dataset_path))
    controller._add_recent_project(str(dataset_path.parent / "." / dataset_path.name))

    recents = controller.get_recent_projects()
    assert recents == [str(dataset_path)]

    other_path = (tmp_path / "datasets" / "second.json").resolve()
    other_path.write_text("{}", encoding="utf-8")
    controller._add_recent_project(str(other_path))
    controller._add_recent_project(str(dataset_path))

    assert controller.get_recent_projects()[:2] == [str(dataset_path), str(other_path)]
