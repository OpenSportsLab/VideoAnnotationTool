"""
Description mode workflows.
"""

import json
from pathlib import Path

import pytest
from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtWidgets import QMessageBox


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
}


@pytest.mark.gui
# Workflow: In Description mode, selecting a tree item should load media and refresh editor text.
def test_description_selection_loads_media_and_refreshes_editor(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("description")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()

    load_calls = []
    monkeypatch.setattr(
        window.media_controller,
        "load_and_play",
        lambda file_path, auto_play=True: load_calls.append(file_path),
    )

    # Force a real selection transition: invalid -> first item.
    window.dataset_explorer_panel.tree.setCurrentIndex(QModelIndex())
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert len(load_calls) == 1
    assert Path(load_calls[0]).name == "test_video_1.mp4"
    assert window.description_panel.caption_edit.toPlainText().strip() == "A short test caption."


@pytest.mark.gui
# Workflow: Description annotation round-trip with edit:
# 1) update caption text + save + reopen, then 2) edit caption again + save + reopen and verify final text.
def test_description_annotate_save_reload_edit_and_persist(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("description")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    # 1) Open description JSON and select first item.
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    first_path = window.get_current_action_path()
    assert first_path is not None

    # 2) Write first caption text and confirm.
    first_text = "Description v1 from GUI test."
    window.description_panel.caption_edit.setPlainText(first_text)
    qtbot.mouseClick(window.description_panel.confirm_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    target_item = next(
        item
        for item in window.model.action_item_data
        if item.get("metadata", {}).get("path") == first_path
    )
    assert target_item["captions"][0]["text"] == first_text

    # 3) Save + close + reopen and verify first text persisted.
    window.dataset_explorer_controller.save_project()
    saved_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry = saved_data.get("data", [])[0]
    assert saved_entry["captions"][0]["text"] == first_text

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
    assert window.description_panel.caption_edit.toPlainText().strip() == first_text

    # 4) Edit caption again, save, reload, and verify edited text persisted.
    second_text = "Description v2 edited after reload."
    window.description_panel.caption_edit.setPlainText(second_text)
    qtbot.mouseClick(window.description_panel.confirm_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry_after_edit = saved_data_after_edit.get("data", [])[0]
    assert saved_entry_after_edit["captions"][0]["text"] == second_text

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
    assert window.description_panel.caption_edit.toPlainText().strip() == second_text


@pytest.mark.gui
# Workflow: In Description mode, removing the currently selected item should clear/disable editor state.
def test_description_remove_selected_item_clears_editor_state(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("description")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert window.description_panel.caption_edit.isEnabled() is True
    assert window.desc_editor_controller.current_action_path is not None

    # Simulate user confirming the remove action.
    # For some reason, testing get stuck there, so we patch QMessageBox.exec to auto-confirm.
    monkeypatch.setattr(
        "controllers.description.desc_editor_controller.QMessageBox.exec",
        lambda self: QMessageBox.StandardButton.Yes,
    )
    window.dataset_explorer_controller.handle_remove_item(first_index)
    qtbot.wait(50)
    
    assert window.tree_model.rowCount() == 0
    assert window.model.action_item_data == []
    assert window.desc_editor_controller.current_action_path is None
    assert window.description_panel.caption_edit.toPlainText() == ""
    assert window.description_panel.caption_edit.isEnabled() is False


@pytest.mark.gui
# Workflow: In Description mode, clearing workspace from Dataset Explorer should reset model/tree/editor state.
def test_description_clear_workspace_resets_editor_and_model(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("description")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
    assert window.tree_model.rowCount() == 1
    assert window.model.json_loaded is True

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    stop_calls = []
    monkeypatch.setattr(window.media_controller, "stop", lambda: stop_calls.append(True))
    monkeypatch.setattr(
        "controllers.description.desc_editor_controller.QMessageBox.exec",
        lambda self: QMessageBox.StandardButton.Yes,
    )

    window.dataset_explorer_controller.handle_clear_workspace()
    qtbot.wait(50)

    assert stop_calls
    assert window.tree_model.rowCount() == 0
    assert window.model.json_loaded is False
    assert window.model.action_item_data == []
    assert window.model.desc_global_metadata == {}
    assert window.desc_editor_controller.current_action_path is None
    assert window.description_panel.caption_edit.toPlainText() == ""
    assert window.description_panel.caption_edit.isEnabled() is False
