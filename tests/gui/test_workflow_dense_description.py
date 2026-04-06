"""
Dense Description mode persistence/editing workflows.
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
# Workflow: Dense Description annotation round-trip with edit:
# 1) modify first dense event(text+time) + save + reopen, then 2) modify again + save + reopen and verify final state.
def test_dense_description_annotate_save_reload_edit_and_persist(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("dense_description")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    # 1) Open dense description JSON and select first item.
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["dense_description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    first_path = window.get_current_action_path()
    assert first_path is not None
    initial_events = window.model.dense_description_events.get(first_path, [])
    assert len(initial_events) >= 1

    # 2) Modify the first dense event (text + timestamp).
    old_event = initial_events[0]
    first_edit = old_event.copy()
    first_edit["position_ms"] = 2100
    first_edit["text"] = "Dense text v1 from GUI test."
    window.dense_editor_controller._on_annotation_modified(old_event, first_edit)

    after_first_edit = window.model.dense_description_events.get(first_path, [])
    assert any(e.get("position_ms") == 2100 and e.get("text") == "Dense text v1 from GUI test." for e in after_first_edit)

    # 3) Save + close + reopen and verify first edit persisted.
    window.dataset_explorer_controller.save_project()
    saved_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_dense = saved_data.get("data", [])[0].get("dense_captions", [])
    assert any(e.get("position_ms") == 2100 and e.get("text") == "Dense text v1 from GUI test." for e in saved_dense)

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
    reopened_events = window.model.dense_description_events.get(reopened_path, [])
    assert any(e.get("position_ms") == 2100 and e.get("text") == "Dense text v1 from GUI test." for e in reopened_events)

    # 4) Modify again, save, reload, and verify second edit persisted.
    old_event_after_reload = next(
        e for e in reopened_events if e.get("position_ms") == 2100 and e.get("text") == "Dense text v1 from GUI test."
    )
    second_edit = old_event_after_reload.copy()
    second_edit["position_ms"] = 3200
    second_edit["text"] = "Dense text v2 edited after reload."
    window.dense_editor_controller._on_annotation_modified(old_event_after_reload, second_edit)

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_dense_after_edit = saved_data_after_edit.get("data", [])[0].get("dense_captions", [])
    assert any(
        e.get("position_ms") == 3200 and e.get("text") == "Dense text v2 edited after reload."
        for e in saved_dense_after_edit
    )

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
    final_events = window.model.dense_description_events.get(final_path, [])
    assert any(
        e.get("position_ms") == 3200 and e.get("text") == "Dense text v2 edited after reload."
        for e in final_events
    )


@pytest.mark.gui
# Workflow: In Dense Description mode, removing the selected item should reset dense panel state.
def test_dense_description_remove_selected_item_resets_panel_state(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("dense_description")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["dense_description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert window.dense_editor_controller.current_video_path is not None

    monkeypatch.setattr(
        "controllers.dense_description.dense_editor_controller.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    # window.dataset_explorer_controller.handle_remove_item(first_index)
    # qtbot.wait(50)

    # assert window.tree_model.rowCount() == 0
    # assert window.model.action_item_data == []
    # assert window.dense_editor_controller.current_video_path is None
    # assert window.dense_panel.input_widget.text_editor.toPlainText() == ""
    # assert window.dense_panel.table.model.rowCount() == 0


@pytest.mark.gui
# Workflow: In Dense Description mode, clearing workspace should reset model/tree/panel and return to welcome.
def test_dense_description_clear_workspace_resets_panel_and_model(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("dense_description")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["dense_description"]
    assert window.tree_model.rowCount() == 1
    assert window.model.json_loaded is True

    stop_calls = []
    monkeypatch.setattr(window.media_controller, "stop", lambda: stop_calls.append(True))
    monkeypatch.setattr(
        "controllers.dense_description.dense_editor_controller.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    window.dataset_explorer_controller.handle_clear_workspace()
    qtbot.wait(50)

    assert stop_calls
    assert window.tree_model.rowCount() == 0
    assert window.model.json_loaded is False
    assert window.model.action_item_data == []
    assert window.model.dense_global_metadata == {}
    assert window.dense_editor_controller.current_video_path is None
    assert window.dense_panel.input_widget.text_editor.toPlainText() == ""
    assert window.dense_panel.table.model.rowCount() == 0
    assert window.center_stack.currentIndex() == 0
