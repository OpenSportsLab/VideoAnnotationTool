"""
Classification mode persistence/editing workflows.
"""

import json

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
}


@pytest.mark.gui
# Workflow: Classification annotation round-trip with edit:
# 1) annotate + save + reopen (label persists), then 2) modify label + save + reopen (new label persists).
def test_classification_annotate_save_reload_edit_labels_and_persist(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    # 1) Open classification JSON.
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["classification"]
    assert window.tree_model.rowCount() == 1

    # 2) Select the first data item in the list.
    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    first_path = window.get_current_action_path()
    assert first_path is not None

    # 3) Annotate with a hand label.
    panel = window.classification_panel
    panel.tabs.setCurrentIndex(0)
    assert "action" in panel.label_groups
    action_group = panel.label_groups["action"]
    pass_btn = next(btn for btn in action_group.radio_group.buttons() if btn.text() == "pass")
    qtbot.mouseClick(pass_btn, Qt.MouseButton.LeftButton)
    assert panel.get_annotation().get("action") == "pass"

    # Manual annotation is now saved immediately on selection.
    qtbot.wait(50)
    assert window.model.manual_annotations[first_path]["action"] == "pass"

    # 4) Save JSON and verify label is written.
    window.dataset_explorer_controller.save_project()
    saved_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry = next(item for item in saved_data.get("data", []) if item.get("id") == "clip_1")
    assert saved_entry["labels"]["action"]["label"] == "pass"

    # 5) Close dataset.
    window.router.close_project()
    assert window.model.json_loaded is False
    assert window.center_stack.currentIndex() == 0

    # 6) Reopen and verify label persistence in model and UI.
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    reopened_index = window.tree_model.index(0, 0)
    assert reopened_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(reopened_index)
    qtbot.wait(50)

    reopened_path = window.get_current_action_path()
    assert reopened_path is not None
    assert window.model.manual_annotations[reopened_path]["action"] == "pass"
    assert window.classification_panel.get_annotation().get("action") == "pass"

    # 7) Edit the label after reload, save again, and verify persistence again.
    reopened_panel = window.classification_panel
    reopened_panel.tabs.setCurrentIndex(0)
    reopened_group = reopened_panel.label_groups["action"]
    shot_btn = next(btn for btn in reopened_group.radio_group.buttons() if btn.text() == "shot")
    qtbot.mouseClick(shot_btn, Qt.MouseButton.LeftButton)
    assert reopened_panel.get_annotation().get("action") == "shot"

    # Manual annotation is now saved immediately on selection.
    qtbot.wait(50)
    assert window.model.manual_annotations[reopened_path]["action"] == "shot"

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry_after_edit = next(item for item in saved_data_after_edit.get("data", []) if item.get("id") == "clip_1")
    assert saved_entry_after_edit["labels"]["action"]["label"] == "shot"

    window.router.close_project()
    assert window.model.json_loaded is False
    assert window.center_stack.currentIndex() == 0

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    final_index = window.tree_model.index(0, 0)
    assert final_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(final_index)
    qtbot.wait(50)

    final_path = window.get_current_action_path()
    assert final_path is not None
    assert window.model.manual_annotations[final_path]["action"] == "shot"
    assert window.classification_panel.get_annotation().get("action") == "shot"


# @pytest.mark.gui
# # Workflow: Import classification JSON, remove the selected dataset item from the explorer,
# # and verify tree/model/editor/media state is reset for classification mode.
# def test_classification_remove_selected_item_resets_state(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("classification")
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )
#     window.router.import_annotations()
#     assert window.tree_model.rowCount() == 1

#     first_index = window.tree_model.index(0, 0)
#     assert first_index.isValid()
#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

    # window.dataset_explorer_controller.handle_remove_item(first_index)
    # qtbot.wait(50)

    # assert window.tree_model.rowCount() == 0
    # assert window.model.action_item_data == []
    # assert window.model.action_item_map == {}
    # assert window.classification_panel.manual_box.isEnabled() is False


@pytest.mark.gui
# Workflow: Import classification JSON, trigger explorer clear-workspace for classification,
# confirm dialog, and verify project/model/editor state is fully reset.
def test_classification_clear_workspace_resets_state(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.tree_model.rowCount() == 1

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QMessageBox.exec",
        lambda self: QMessageBox.StandardButton.Yes,
    )

    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["classification"])
    window.dataset_explorer_controller.handle_clear_workspace()
    qtbot.wait(50)

    assert window.tree_model.rowCount() == 0
    assert window.model.action_item_data == []
    assert window.model.json_loaded is True
    assert window.model.current_json_path == str(project_json_path)
    assert window.classification_panel.manual_box.isEnabled() is False


# @pytest.mark.gui
# # Workflow: In Classification mode, save an annotation then verify undo/redo toggles it in model and editor.
# def test_classification_undo_redo_manual_annotation_roundtrip(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("classification")
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )
#     window.router.import_annotations()

#     first_index = window.tree_model.index(0, 0)
#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

#     current_path = window.get_current_action_path()
#     assert current_path is not None

#     panel = window.classification_panel
#     panel.tabs.setCurrentIndex(0)
#     group = panel.label_groups["action"]
#     shot_btn = next(btn for btn in group.radio_group.buttons() if btn.text() == "shot")
#     qtbot.mouseClick(shot_btn, Qt.MouseButton.LeftButton)
#     qtbot.mouseClick(panel.confirm_btn, Qt.MouseButton.LeftButton)
#     qtbot.wait(50)

#     assert window.model.manual_annotations[current_path]["action"] == "shot"

#     window.history_manager.perform_undo()
#     qtbot.wait(50)
#     assert current_path not in window.model.manual_annotations
#     assert window.classification_panel.get_annotation().get("action") in (None, "")

#     window.history_manager.perform_redo()
#     qtbot.wait(50)
#     assert window.model.manual_annotations[current_path]["action"] == "shot"
#     assert window.classification_panel.get_annotation().get("action") == "shot"


# @pytest.mark.gui
# # Workflow: In Classification mode, done/not-done filter should hide unannotated rows and keep annotated rows visible.
# def test_classification_filter_done_hides_unannotated_rows(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("classification", item_count=2)
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )
#     window.router.import_annotations()
#     assert window.tree_model.rowCount() == 2

#     first_index = window.tree_model.index(0, 0)
#     second_index = window.tree_model.index(1, 0)
#     assert first_index.isValid() and second_index.isValid()

#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

#     panel = window.classification_panel
#     panel.tabs.setCurrentIndex(0)
#     group = panel.label_groups["action"]
#     pass_btn = next(btn for btn in group.radio_group.buttons() if btn.text() == "pass")
#     qtbot.mouseClick(pass_btn, Qt.MouseButton.LeftButton)
#     qtbot.mouseClick(panel.confirm_btn, Qt.MouseButton.LeftButton)
#     qtbot.wait(50)

#     window.dataset_explorer_panel.filter_combo.setCurrentIndex(1)
#     qtbot.wait(50)

#     assert window.dataset_explorer_panel.tree.isRowHidden(0, first_index.parent()) is False
#     assert window.dataset_explorer_panel.tree.isRowHidden(1, second_index.parent()) is True
