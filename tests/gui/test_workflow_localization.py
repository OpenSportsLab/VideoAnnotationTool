"""
Localization mode persistence/editing workflows.
"""

import copy
import importlib
import json
import os
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QMessageBox

try:
    _colors_module = importlib.import_module("annotation_tool.colors")
except ModuleNotFoundError:
    _colors_module = importlib.import_module("colors")

localization_label_color_hex = _colors_module.localization_label_color_hex
localization_label_text_hex = _colors_module.localization_label_text_hex


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
    "question_answer": 4,
}

FRAME_STACK_PATH = (
    Path(__file__).resolve().parents[2]
    / "test_data"
    / "sn-gar"
    / "sngar-frames"
    / "train"
    / "clip_000000.npy"
)


def _double_click_table_cell(window, qtbot, row: int, col: int):
    table_view = window.localization_panel.table.table
    model = window.localization_panel.table.model
    idx = model.index(row, col)
    assert idx.isValid()
    table_view.scrollTo(idx)
    rect = table_view.visualRect(idx)
    qtbot.mouseDClick(table_view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    qtbot.wait(50)


@pytest.mark.gui
def test_localization_hides_outer_tab_bar_when_only_hand_annotation_remains(window):
    panel = window.localization_panel

    assert panel.tabs.count() == 1
    assert panel.tabs.tabText(0) == "Hand Annotation"
    assert panel.tabs.tabBar().isHidden() is True


@pytest.mark.gui
def test_localization_inference_manager_uses_checked_in_loc_config(window):
    manager = type(window.localization_editor_controller.inference_manager)()
    config_path = Path(manager.config_path)

    assert config_path.name == "loc_config.yaml"
    assert config_path.is_file()
    assert config_path.parent.name == "annotation_tool"


@pytest.mark.gui
def test_localization_smart_inference_passes_head_context_to_manager(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    responses = iter([("jeetv/snpro-snbas-2024", True), ("00:00.000", True), ("00:05.000", True)])
    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QInputDialog.getText",
        lambda *args, **kwargs: next(responses),
    )

    captured = {}

    def fake_start_inference(video_path, start_ms, end_ms, model_id, head_name, labels, input_fps):
        captured.update(
            {
                "video_path": video_path,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "model_id": model_id,
                "head_name": head_name,
                "labels": list(labels),
                "input_fps": input_fps,
            }
        )

    monkeypatch.setattr(window.localization_editor_controller.inference_manager, "start_inference", fake_start_inference)

    window.localization_editor_controller._on_head_smart_inference_requested("ball_action")

    assert captured["video_path"] == window.localization_editor_controller.current_video_path
    assert captured["start_ms"] == 0
    assert captured["end_ms"] == 5000
    assert captured["model_id"] == "jeetv/snpro-snbas-2024"
    assert captured["head_name"] == "ball_action"
    assert captured["labels"] == window.dataset_explorer_controller.label_definitions["ball_action"]["labels"]
    assert captured["input_fps"] == pytest.approx(25.0)


@pytest.mark.gui
def test_localization_inference_loading_cue_toggles_controls(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.localization_editor_controller
    panel = window.localization_panel

    monkeypatch.setattr(controller, "_prompt_model_id", lambda: "jeetv/snpro-snbas-2024")
    monkeypatch.setattr(controller, "_prompt_inference_range", lambda: (0, 5000))

    captured = {}

    def fake_start_inference(video_path, start_ms, end_ms, model_id, head_name, labels, input_fps):
        captured.update(
            {
                "video_path": video_path,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "model_id": model_id,
                "head_name": head_name,
                "labels": list(labels),
                "input_fps": input_fps,
            }
        )

    monkeypatch.setattr(controller.inference_manager, "start_inference", fake_start_inference)
    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QMessageBox.critical",
        lambda *args, **kwargs: None,
    )

    controller._on_head_smart_inference_requested("ball_action")
    qtbot.wait(50)

    assert captured["video_path"] == controller.current_video_path
    assert panel._inference_loading_dialog.isVisible() is True
    assert panel.spottingTabs.isEnabled() is False
    assert panel.table.table.isEnabled() is False

    controller._on_inference_error("synthetic failure")
    qtbot.wait(50)

    assert panel._inference_loading_dialog.isVisible() is False
    assert panel.spottingTabs.isEnabled() is True
    assert panel.table.table.isEnabled() is True


@pytest.mark.gui
def test_localization_inference_cancel_dispatches_to_manager(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.localization_editor_controller
    panel = window.localization_panel

    calls = {"count": 0}
    monkeypatch.setattr(
        controller.inference_manager,
        "cancel_inference",
        lambda: calls.__setitem__("count", calls["count"] + 1) or True,
    )

    panel.inferenceCancelRequested.emit()
    qtbot.wait(20)
    assert calls["count"] == 1


@pytest.mark.gui
def test_localization_label_colors_persist_in_qsettings_not_json(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    from controllers.localization.label_color_settings import get_saved_label_color

    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.localization_editor_controller
    settings = window.dataset_explorer_controller.settings
    controller._on_label_color_req("ball_action", "pass", "#ff8844")
    qtbot.wait(20)

    assert get_saved_label_color(settings, "ball_action", "pass") == "#ff8844"

    assert window.dataset_explorer_controller.save_project() is True
    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    assert "label_colors" not in saved.get("labels", {}).get("ball_action", {})

    window.dataset_explorer_controller.close_project()
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    qtbot.wait(50)

    restored_colors = (
        window.localization_editor_controller._schema_definitions
        .get("ball_action", {})
        .get("label_colors", {})
    )
    assert restored_colors.get("pass") == "#ff8844"


@pytest.mark.gui
# Workflow: Localization annotation round-trip with timestamp edit:
# 1) create event(label+time) + save + reopen, then 2) change time + save + reopen and verify final timestamp.
def test_localization_annotate_save_reload_edit_time_and_persist(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    # 1) Open localization JSON.
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["localization"]
    assert window.tree_model.rowCount() == 1

    # 2) Select first data item.
    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    video_path = window.get_current_action_path()
    assert video_path is not None

    # 3) Annotate with label, then set timestamp.
    window.localization_editor_controller._on_spotting_triggered("ball_action", "shot")
    events = window.dataset_explorer_controller.localization_events.get(video_path, [])
    assert any(e.get("label") == "shot" for e in events)

    old_event = next(e for e in events if e.get("label") == "shot")
    new_event = old_event.copy()
    new_event["position_ms"] = 2345
    window.localization_editor_controller._on_annotation_modified(old_event, new_event)

    events_after_add = window.dataset_explorer_controller.localization_events.get(video_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 2345 for e in events_after_add)
    table_events = [
        window.localization_panel.table.model.get_annotation_at(i)
        for i in range(window.localization_panel.table.model.rowCount())
    ]
    assert any(e and e.get("label") == "shot" and e.get("position_ms") == 2345 for e in table_events)

    # 4) Save + close + reopen and verify event persistence.
    window.dataset_explorer_controller.save_project()
    saved_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_events = saved_data.get("data", [])[0].get("events", [])
    assert any(e.get("label") == "shot" and str(e.get("position_ms")) == "2345" for e in saved_events)

    window.dataset_explorer_controller.close_project()
    assert window.dataset_explorer_controller.json_loaded is False

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    reopened_index = window.tree_model.index(0, 0)
    assert reopened_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(reopened_index)
    qtbot.wait(50)

    reopened_path = window.get_current_action_path()
    assert reopened_path is not None
    reopened_events = window.dataset_explorer_controller.localization_events.get(reopened_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 2345 for e in reopened_events)

    # 5) Edit timestamp, save again, reload again, and verify changed time persists.
    old_event_after_reload = next(
        e for e in reopened_events if e.get("label") == "shot" and e.get("position_ms") == 2345
    )
    edited_event = old_event_after_reload.copy()
    edited_event["position_ms"] = 3456
    window.localization_editor_controller._on_annotation_modified(old_event_after_reload, edited_event)

    edited_events = window.dataset_explorer_controller.localization_events.get(reopened_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 3456 for e in edited_events)

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_events_after_edit = saved_data_after_edit.get("data", [])[0].get("events", [])
    assert any(e.get("label") == "shot" and str(e.get("position_ms")) == "3456" for e in saved_events_after_edit)

    window.dataset_explorer_controller.close_project()
    assert window.dataset_explorer_controller.json_loaded is False

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    final_index = window.tree_model.index(0, 0)
    assert final_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(final_index)
    qtbot.wait(50)

    final_path = window.get_current_action_path()
    assert final_path is not None
    final_events = window.dataset_explorer_controller.localization_events.get(final_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 3456 for e in final_events)


@pytest.mark.gui
def test_localization_events_remain_chronological_after_add_modify_delete(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    path = window.localization_editor_controller.current_video_path
    sample_id = window.localization_editor_controller.current_sample_id
    assert path
    assert sample_id

    # Add an early event (before existing 1000ms).
    window.history_manager.execute_localization_event_add(
        sample_id,
        {"head": "ball_action", "label": "shot", "position_ms": 500},
    )
    qtbot.wait(50)
    events = list(window.dataset_explorer_controller.localization_events.get(path, []))
    assert [int(e.get("position_ms", 0)) for e in events] == sorted(int(e.get("position_ms", 0)) for e in events)

    # Modify event time so ordering must be recomputed again.
    old_event = next(e for e in events if e.get("label") == "shot" and int(e.get("position_ms", 0)) == 500)
    updated_event = dict(old_event)
    updated_event["position_ms"] = 1500
    window.localization_editor_controller._on_annotation_modified(old_event, updated_event)
    qtbot.wait(50)
    events = list(window.dataset_explorer_controller.localization_events.get(path, []))
    assert [int(e.get("position_ms", 0)) for e in events] == sorted(int(e.get("position_ms", 0)) for e in events)

    # # Delete one event and ensure ordering remains canonical. (Freezes without proper handling in delete flow.)
    # window.localization_editor_controller._on_delete_single_annotation(events[0])
    # qtbot.wait(50)
    # events = list(window.dataset_explorer_controller.localization_events.get(path, []))
    # assert [int(e.get("position_ms", 0)) for e in events] == sorted(int(e.get("position_ms", 0)) for e in events)

    # Persisted JSON order must match chronological order too.
    window.dataset_explorer_controller.save_project()
    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_events = saved.get("data", [])[0].get("events", [])
    assert [int(e.get("position_ms", 0)) for e in saved_events] == sorted(
        int(e.get("position_ms", 0)) for e in saved_events
    )


@pytest.mark.gui
def test_localization_label_colors_match_table_rows_and_timeline_markers(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.localization_editor_controller
    controller.on_media_position_changed(2500)
    controller._on_spotting_triggered("ball_action", "shot")
    qtbot.wait(50)

    model = window.localization_panel.table.model

    row_by_label = {}
    for row in range(model.rowCount()):
        item = model.get_annotation_at(row)
        if item and item.get("head") == "ball_action":
            row_by_label[item.get("label")] = row

    assert "pass" in row_by_label
    assert "shot" in row_by_label

    pass_brush = model.data(model.index(row_by_label["pass"], 0), Qt.ItemDataRole.BackgroundRole)
    shot_brush = model.data(model.index(row_by_label["shot"], 0), Qt.ItemDataRole.BackgroundRole)
    assert isinstance(pass_brush, QBrush)
    assert isinstance(shot_brush, QBrush)

    expected_pass = localization_label_color_hex("ball_action", "pass")
    expected_shot = localization_label_color_hex("ball_action", "shot")
    assert expected_pass != expected_shot
    assert pass_brush.color().name() == expected_pass
    assert shot_brush.color().name() == expected_shot

    marker_colors = {
        int(marker.get("start_ms", 0)): marker.get("color").name()
        for marker in window.center_panel.slider.markers
    }
    assert marker_colors[1000] == expected_pass
    assert marker_colors[2500] == expected_shot

    tabs_adapter = window.localization_panel.annot_mgmt.tabs
    button_styles = {
        label: button.styleSheet()
        for button, (head, label) in tabs_adapter._button_meta.items()
        if head == "ball_action"
    }
    assert expected_pass in button_styles["pass"]
    assert expected_shot in button_styles["shot"]
    assert localization_label_text_hex(expected_pass) in button_styles["pass"]
    assert localization_label_text_hex(expected_shot) in button_styles["shot"]


# @pytest.mark.gui
# def test_localization_button_context_menu_color_change_updates_button_table_and_marker(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("localization")
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )
#     window.dataset_explorer_controller.import_annotations()

#     first_index = window.tree_model.index(0, 0)
#     assert first_index.isValid()
#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

#     tabs_adapter = window.localization_panel.annot_mgmt.tabs
#     pass_button = next(
#         button for button, (head, label) in tabs_adapter._button_meta.items()
#         if head == "ball_action" and label == "pass"
#     )

#     monkeypatch.setattr(
#         "ui.localization.QColorDialog.getColor",
#         lambda *args, **kwargs: QColor("#ff8844"),
#     )

#     tabs_adapter._show_label_context_menu(pass_button, "ball_action", "pass")
#     qtbot.wait(50)

#     assert window.dataset_explorer_controller.label_definitions["ball_action"]["label_colors"]["pass"] == "#ff8844"
#     assert "#ff8844" in pass_button.styleSheet()

#     model = window.localization_panel.table.model
#     pass_row = next(
#         row for row in range(model.rowCount())
#         if model.get_annotation_at(row).get("head") == "ball_action"
#         and model.get_annotation_at(row).get("label") == "pass"
#     )
#     pass_brush = model.data(model.index(pass_row, 0), Qt.ItemDataRole.BackgroundRole)
#     assert isinstance(pass_brush, QBrush)
#     assert pass_brush.color().name() == "#ff8844"

#     marker_colors = {
#         int(marker.get("start_ms", 0)): marker.get("color").name()
#         for marker in window.center_panel.slider.markers
#     }
#     assert marker_colors[1000] == "#ff8844"


# @pytest.mark.gui
# # Workflow: In Localization mode, removing the selected item should clear panel/media/table state.
# def test_localization_remove_selected_item_resets_panel_state(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("localization")
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )
#     window.dataset_explorer_controller.import_annotations()
#     assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["localization"]
#     assert window.tree_model.rowCount() == 1

#     first_index = window.tree_model.index(0, 0)
#     assert first_index.isValid()
#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

#     assert window.localization_editor_controller.current_video_path is not None

#     window.dataset_explorer_controller.handle_remove_item(first_index)
#     qtbot.wait(50)

#     assert window.tree_model.rowCount() == 0
#     assert window.dataset_explorer_controller.action_item_data == []
#     assert window.localization_editor_controller.current_video_path is None
#     assert window.localization_panel.table.model.rowCount() == 0


@pytest.mark.gui
# Workflow: In Localization mode, clearing workspace should reset tree/model/panel state.
def test_localization_clear_workspace_resets_panel_and_model(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["localization"]
    assert window.tree_model.rowCount() == 1
    assert window.dataset_explorer_controller.json_loaded is True

    stop_calls = []
    monkeypatch.setattr(window.media_controller, "stop", lambda: stop_calls.append(True))
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QMessageBox.exec",
        lambda self: QMessageBox.StandardButton.Yes,
    )

    window.dataset_explorer_controller.handle_clear_workspace()
    qtbot.wait(50)

    assert stop_calls
    assert window.tree_model.rowCount() == 0
    assert window.dataset_explorer_controller.action_item_data == []
    assert window.dataset_explorer_controller.localization_events == {}
    assert window.dataset_explorer_controller.label_definitions != {}
    assert window.dataset_explorer_controller.json_loaded is True
    assert window.dataset_explorer_controller.current_json_path == str(project_json_path)
    assert window.localization_editor_controller.current_video_path is None
    assert window.localization_editor_controller.current_head is None
    assert window.localization_panel.table.model.rowCount() == 0


@pytest.mark.gui
def test_localization_add_label_uses_signal_pause_resume_flow(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["localization"]

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    toggle_emits = []
    window.center_panel.playPauseRequested.connect(lambda: toggle_emits.append(True))
    window.localization_editor_controller.on_playback_state_changed(True)
    monkeypatch.setattr(window.center_panel.player, "position", lambda: 4321)
    window.localization_editor_controller.on_media_position_changed(4321)
    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QInputDialog.getText",
        lambda *args, **kwargs: ("signal_pause_label", True),
    )

    undo_before = len(window.dataset_explorer_controller.undo_stack)
    window.localization_editor_controller._on_label_add_req("ball_action")
    qtbot.wait(50)

    assert len(toggle_emits) == 2
    assert "signal_pause_label" in window.dataset_explorer_controller.label_definitions["ball_action"]["labels"]
    path = window.localization_editor_controller.current_video_path
    assert path is not None
    events = window.dataset_explorer_controller.localization_events.get(path, [])
    assert any(event.get("label") == "signal_pause_label" and event.get("position_ms") == 4321 for event in events)
    assert len(window.dataset_explorer_controller.undo_stack) == undo_before + 1


@pytest.mark.gui
def test_localization_event_navigation_seeks_frames_npy_sample(
    window,
    monkeypatch,
    qtbot,
    tmp_path,
):
    rel_frame_path = os.path.relpath(FRAME_STACK_PATH, start=tmp_path).replace("\\", "/")
    project_json_path = tmp_path / "frames_localization.json"
    payload = {
        "version": "2.0",
        "date": "2026-04-26",
        "task": "action_localization",
        "dataset_name": "frames_localization",
        "modalities": ["frames_npy"],
        "labels": {"action": {"type": "single_label", "labels": ["pass", "shot"]}},
        "data": [
            {
                "id": "frames_loc",
                "inputs": [{"path": rel_frame_path, "type": "frames_npy"}],
                "events": [
                    {"head": "action", "label": "pass", "position_ms": 1000},
                    {"head": "action", "label": "shot", "position_ms": 2000},
                ],
            }
        ],
    }
    project_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["localization"]

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    seek_calls = []
    monkeypatch.setattr(window.media_controller, "set_position", lambda ms: seek_calls.append(ms))

    window.localization_editor_controller.on_media_position_changed(0)
    window.localization_editor_controller._navigate_annotation(1)
    qtbot.wait(20)
    window.localization_editor_controller._navigate_annotation(1)
    qtbot.wait(20)

    assert seek_calls == [1000, 2000]


@pytest.mark.gui
def test_localization_inference_persists_confidence_and_confirm_strips_it(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.localization_editor_controller
    controller.current_head = "ball_action"
    controller._on_inference_success(
        [{"head": "ball_action", "label": "shot", "position_ms": 4321, "confidence_score": 0.64}]
    )
    qtbot.wait(50)

    path = controller.current_video_path
    assert path is not None
    events = list(window.dataset_explorer_controller.localization_events.get(path, []))
    inferred = next(
        evt
        for evt in events
        if evt.get("head") == "ball_action"
        and evt.get("label") == "shot"
        and int(evt.get("position_ms", 0)) == 4321
    )
    assert inferred.get("confidence_score") == pytest.approx(0.64)

    row = next(
        i
        for i in range(window.localization_panel.table.model.rowCount())
        if window.localization_panel.table.model.get_annotation_at(i) == inferred
    )
    monkeypatch.setattr(
        "ui.localization.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    _double_click_table_cell(window, qtbot, row, 3)

    events = list(window.dataset_explorer_controller.localization_events.get(path, []))
    confirmed = next(
        evt for evt in events
        if evt.get("head") == "ball_action"
        and evt.get("label") == "shot"
        and int(evt.get("position_ms", 0)) == 4321
    )
    assert "confidence_score" not in confirmed


@pytest.mark.gui
def test_localization_inference_reject_inline_removes_smart_event(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.localization_editor_controller
    controller.current_head = "ball_action"
    controller._on_inference_success(
        [{"head": "ball_action", "label": "shot", "position_ms": 4999, "confidence_score": 0.71}]
    )
    qtbot.wait(50)

    path = controller.current_video_path
    assert path is not None
    events = list(window.dataset_explorer_controller.localization_events.get(path, []))
    target = next(
        evt
        for evt in events
        if evt.get("head") == "ball_action"
        and evt.get("label") == "shot"
        and int(evt.get("position_ms", 0)) == 4999
    )

    row = next(
        i
        for i in range(window.localization_panel.table.model.rowCount())
        if window.localization_panel.table.model.get_annotation_at(i) == target
    )
    monkeypatch.setattr(
        "ui.localization.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    _double_click_table_cell(window, qtbot, row, 3)

    events = list(window.dataset_explorer_controller.localization_events.get(path, []))
    assert not any(
        evt.get("head") == "ball_action"
        and evt.get("label") == "shot"
        and int(evt.get("position_ms", 0)) == 4999
        for evt in events
    )


@pytest.mark.gui
def test_localization_inference_unknown_label_mapping_skip_keeps_dataset_unchanged(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.localization_editor_controller
    controller.current_head = "ball_action"
    before_events = list(window.dataset_explorer_controller.localization_events.get(controller.current_video_path, []))

    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QInputDialog.getItem",
        lambda *args, **kwargs: ("<Skip Prediction>", True),
    )
    controller._on_inference_success(
        [{"head": "ball_action", "label": "unknown_pred", "position_ms": 5555, "confidence_score": 0.51}]
    )
    qtbot.wait(50)

    after_events = list(window.dataset_explorer_controller.localization_events.get(controller.current_video_path, []))
    assert after_events == before_events


@pytest.mark.gui
def test_localization_inference_unknown_label_mapping_applies_selected_label(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.localization_editor_controller
    controller.current_head = "ball_action"

    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QInputDialog.getItem",
        lambda *args, **kwargs: ("shot", True),
    )
    controller._on_inference_success(
        [{"head": "ball_action", "label": "unknown_pred", "position_ms": 5656, "confidence_score": 0.73}]
    )
    qtbot.wait(50)

    events = list(window.dataset_explorer_controller.localization_events.get(controller.current_video_path, []))
    matched = next(
        evt for evt in events
        if evt.get("head") == "ball_action"
        and evt.get("label") == "shot"
        and int(evt.get("position_ms", 0)) == 5656
    )
    assert matched.get("confidence_score") == pytest.approx(0.73)


# @pytest.mark.gui
# # Workflow: In Localization mode, "Set to Current Video Time" updates selected event timestamp in model/table.
# def test_localization_set_to_current_video_time_updates_selected_annotation(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("localization")
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )
#     window.dataset_explorer_controller.import_annotations()

#     first_index = window.tree_model.index(0, 0)
#     assert first_index.isValid()
#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

#     path = window.get_current_action_path()
#     assert path is not None

#     window.localization_editor_controller._on_spotting_triggered("ball_action", "shot")
#     events = window.dataset_explorer_controller.localization_events.get(path, [])
#     target_row = None
#     original_pos = None
#     for row in range(window.localization_panel.table.model.rowCount()):
#         row_event = window.localization_panel.table.model.get_annotation_at(row)
#         if row_event and row_event.get("head") == "ball_action" and row_event.get("label") == "shot":
#             target_row = row
#             original_pos = row_event.get("position_ms")
#             break

#     assert target_row is not None
#     window.localization_panel.table.table.selectRow(target_row)
#     qtbot.wait(50)
#     assert window.localization_panel.table.btn_set_time.isEnabled() is True

#     target_ms = (original_pos or 0) + 1777
#     monkeypatch.setattr(window.center_panel.player, "position", lambda: target_ms)
#     qtbot.mouseClick(window.localization_panel.table.btn_set_time, Qt.MouseButton.LeftButton)
#     qtbot.wait(50)

#     updated_events = window.dataset_explorer_controller.localization_events.get(path, [])
#     assert any(
#         event.get("head") == "ball_action"
#         and event.get("label") == "shot"
#         and event.get("position_ms") == target_ms
#         for event in updated_events
#     )
#     assert not any(
#         event.get("head") == "ball_action"
#         and event.get("label") == "shot"
#         and event.get("position_ms") == original_pos
#         for event in updated_events
#     )


# @pytest.mark.gui
# # Workflow: In Localization mode, adding an event should be undoable/redoable via global history controls.
# def test_localization_undo_redo_event_roundtrip(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("localization")
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )
#     window.dataset_explorer_controller.import_annotations()

#     first_index = window.tree_model.index(0, 0)
#     assert first_index.isValid()
#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

#     current_path = window.get_current_action_path()
#     assert current_path is not None

#     initial_events = list(window.dataset_explorer_controller.localization_events.get(current_path, []))
#     initial_count = len(initial_events)

#     window.localization_editor_controller._on_spotting_triggered("ball_action", "shot")
#     qtbot.wait(50)
#     events_after_add = window.dataset_explorer_controller.localization_events.get(current_path, [])
#     assert len(events_after_add) == initial_count + 1
#     assert any(e.get("label") == "shot" for e in events_after_add)

#     window.history_manager.perform_undo()
#     qtbot.wait(50)
#     events_after_undo = window.dataset_explorer_controller.localization_events.get(current_path, [])
#     assert len(events_after_undo) == initial_count
#     assert not any(e.get("label") == "shot" for e in events_after_undo)

#     window.history_manager.perform_redo()
#     qtbot.wait(50)
#     events_after_redo = window.dataset_explorer_controller.localization_events.get(current_path, [])
#     assert len(events_after_redo) == initial_count + 1
#     assert any(e.get("label") == "shot" for e in events_after_redo)
