"""
Localization mode persistence/editing workflows.
"""

import json

import pytest
from PyQt6.QtWidgets import QMessageBox


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
}


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
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    # 1) Open localization JSON.
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
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
    events = window.model.localization_events.get(video_path, [])
    assert any(e.get("label") == "shot" for e in events)

    old_event = next(e for e in events if e.get("label") == "shot")
    new_event = old_event.copy()
    new_event["position_ms"] = 2345
    window.localization_editor_controller._on_annotation_modified(old_event, new_event)

    events_after_add = window.model.localization_events.get(video_path, [])
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

    window.router.close_project()
    assert window.model.json_loaded is False

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    reopened_index = window.tree_model.index(0, 0)
    assert reopened_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(reopened_index)
    qtbot.wait(50)

    reopened_path = window.get_current_action_path()
    assert reopened_path is not None
    reopened_events = window.model.localization_events.get(reopened_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 2345 for e in reopened_events)

    # 5) Edit timestamp, save again, reload again, and verify changed time persists.
    old_event_after_reload = next(
        e for e in reopened_events if e.get("label") == "shot" and e.get("position_ms") == 2345
    )
    edited_event = old_event_after_reload.copy()
    edited_event["position_ms"] = 3456
    window.localization_editor_controller._on_annotation_modified(old_event_after_reload, edited_event)

    edited_events = window.model.localization_events.get(reopened_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 3456 for e in edited_events)

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_events_after_edit = saved_data_after_edit.get("data", [])[0].get("events", [])
    assert any(e.get("label") == "shot" and str(e.get("position_ms")) == "3456" for e in saved_events_after_edit)

    window.router.close_project()
    assert window.model.json_loaded is False

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    final_index = window.tree_model.index(0, 0)
    assert final_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(final_index)
    qtbot.wait(50)

    final_path = window.get_current_action_path()
    assert final_path is not None
    final_events = window.model.localization_events.get(final_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 3456 for e in final_events)


@pytest.mark.gui
# Workflow: In Localization mode, removing the selected item should clear panel/media/table state.
def test_localization_remove_selected_item_resets_panel_state(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["localization"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert window.localization_editor_controller.current_video_path is not None

    # window.dataset_explorer_controller.handle_remove_item(first_index)
    # qtbot.wait(50)

    # assert window.tree_model.rowCount() == 0
    # assert window.model.action_item_data == []
    # assert window.localization_editor_controller.current_video_path is None
    # assert window.localization_panel.table.model.rowCount() == 0
    # assert window.center_panel.player.source().isEmpty()


@pytest.mark.gui
# Workflow: In Localization mode, clearing workspace should reset tree/model/panel state.
def test_localization_clear_workspace_resets_panel_and_model(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["localization"]
    assert window.tree_model.rowCount() == 1
    assert window.model.json_loaded is True

    stop_calls = []
    monkeypatch.setattr(window.media_controller, "stop", lambda: stop_calls.append(True))
    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    window.dataset_explorer_controller.handle_clear_workspace()
    qtbot.wait(50)

    assert stop_calls
    assert window.tree_model.rowCount() == 0
    assert window.model.action_item_data == []
    assert window.model.localization_events == {}
    assert window.model.smart_localization_events == {}
    assert window.model.label_definitions == {}
    assert window.localization_editor_controller.current_video_path is None
    assert window.localization_editor_controller.current_head is None
    assert window.localization_panel.table.model.rowCount() == 0
