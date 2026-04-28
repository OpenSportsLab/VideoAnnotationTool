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
    "question_answer": 4,
}


@pytest.mark.gui
def test_classification_train_tab_is_hidden(
    window,
    monkeypatch,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    window.dataset_explorer_controller.import_annotations()

    panel = window.classification_panel
    tab_labels = [panel.tabs.tabText(idx).strip().lower() for idx in range(panel.tabs.count())]
    assert "train" not in tab_labels


@pytest.mark.gui
def test_classification_head_tabs_manage_schema(
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
    window.dataset_explorer_controller.import_annotations()

    controller = window.classification_editor_controller
    panel = window.classification_panel
    monkeypatch.setattr(controller, "_prompt_head_type", lambda _name: "single_label")
    monkeypatch.setattr(
        "ui.classification.QInputDialog.getText",
        lambda *args, **kwargs: ("Game Phase", True),
    )
    monkeypatch.setattr(
        "controllers.classification.classification_editor_controller.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    assert panel.schema_box.isVisible() is False
    assert panel.head_tabs_widget.tabText(panel.head_tabs_widget.count() - 1) == "+"
    assert panel.get_current_head() == "action"

    panel._on_head_tab_bar_clicked(panel._plus_tab_index)
    qtbot.wait(50)

    assert "game_phase" in window.dataset_explorer_controller.label_definitions
    assert panel.get_current_head() == "game_phase"

    panel.head_rename_requested.emit("game_phase", "Play Type")
    qtbot.wait(50)

    assert "play_type" in window.dataset_explorer_controller.label_definitions
    assert "game_phase" not in window.dataset_explorer_controller.label_definitions
    assert panel.get_current_head() == "play_type"

    panel.head_delete_requested.emit("play_type")
    qtbot.wait(50)

    assert "play_type" not in window.dataset_explorer_controller.label_definitions
    assert panel.head_tabs_widget.tabText(panel.head_tabs_widget.count() - 1) == "+"


@pytest.mark.gui
def test_classification_removing_last_head_clears_sample_labels_without_crash(
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
    monkeypatch.setattr(
        "controllers.classification.classification_editor_controller.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    sample_path = window.get_current_action_path()
    assert sample_path is not None

    panel = window.classification_panel
    action_group = panel.label_groups["action"]
    pass_btn = next(btn for btn in action_group.radio_group.buttons() if btn.text() == "pass")
    qtbot.mouseClick(pass_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    assert window.dataset_explorer_controller.manual_annotations[sample_path]["action"] == "pass"

    panel.head_delete_requested.emit("action")
    qtbot.wait(50)

    assert "action" not in window.dataset_explorer_controller.label_definitions
    assert sample_path not in window.dataset_explorer_controller.manual_annotations
    assert panel.head_tabs_widget.tabText(panel.head_tabs_widget.count() - 1) == "+"


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
    window.dataset_explorer_controller.import_annotations()
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
    assert window.dataset_explorer_controller.manual_annotations[first_path]["action"] == "pass"

    # 4) Save JSON and verify label is written.
    window.dataset_explorer_controller.save_project()
    saved_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry = next(item for item in saved_data.get("data", []) if item.get("id") == "clip_1")
    assert saved_entry["labels"]["action"]["label"] == "pass"

    # 5) Close dataset.
    window.dataset_explorer_controller.close_project()
    assert window.dataset_explorer_controller.json_loaded is False
    assert window.center_stack.currentIndex() == 0

    # 6) Reopen and verify label persistence in model and UI.
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
    assert window.dataset_explorer_controller.manual_annotations[reopened_path]["action"] == "pass"
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
    assert window.dataset_explorer_controller.manual_annotations[reopened_path]["action"] == "shot"

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry_after_edit = next(item for item in saved_data_after_edit.get("data", []) if item.get("id") == "clip_1")
    assert saved_entry_after_edit["labels"]["action"]["label"] == "shot"

    window.dataset_explorer_controller.close_project()
    assert window.dataset_explorer_controller.json_loaded is False
    assert window.center_stack.currentIndex() == 0

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
    assert window.dataset_explorer_controller.manual_annotations[final_path]["action"] == "shot"
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
#     window.dataset_explorer_controller.import_annotations()
#     assert window.tree_model.rowCount() == 1

#     first_index = window.tree_model.index(0, 0)
#     assert first_index.isValid()
#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

    # window.dataset_explorer_controller.handle_remove_item(first_index)
    # qtbot.wait(50)

    # assert window.tree_model.rowCount() == 0
    # assert window.dataset_explorer_controller.action_item_data == []
    # assert window.dataset_explorer_controller.action_item_map == {}
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
    window.dataset_explorer_controller.import_annotations()
    assert window.tree_model.rowCount() == 1

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QMessageBox.exec",
        lambda self: QMessageBox.StandardButton.Yes,
    )

    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["classification"])
    window.dataset_explorer_controller.handle_clear_workspace()
    qtbot.wait(50)

    assert window.tree_model.rowCount() == 0
    assert window.dataset_explorer_controller.action_item_data == []
    assert window.dataset_explorer_controller.json_loaded is True
    assert window.dataset_explorer_controller.current_json_path == str(project_json_path)
    assert window.classification_panel.manual_box.isEnabled() is False


@pytest.mark.gui
def test_classification_smart_inference_persists_confidence_and_confirm_strips_it(
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
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.classification_editor_controller
    path = controller.get_current_action_path()
    assert path
    sample = window.dataset_explorer_controller.get_sample_by_path(path)
    assert isinstance(sample, dict)
    initial_labels = sample.get("labels", {})
    if "action" in initial_labels:
        assert "confidence_score" not in initial_labels["action"]

    controller.inference_manager._on_inference_success(
        "action",
        "shot",
        {"shot": 0.87, "Other Uncertainties": 0.13},
    )
    qtbot.wait(50)

    sample = window.dataset_explorer_controller.get_sample_by_path(path)
    assert isinstance(sample, dict)
    assert sample["labels"]["action"]["label"] == "shot"
    assert sample["labels"]["action"]["confidence_score"] == pytest.approx(0.87)
    tree_item = window.dataset_explorer_controller.action_item_map[
        window.dataset_explorer_controller.get_path_by_id("clip_1")
    ]
    assert tree_item.text() == "clip_1 (conf:0.87)"

    smart_widgets = window.classification_panel.get_head_row_smart_widgets("action", "shot")
    assert smart_widgets is not None
    conf_btn, accept_btn, reject_btn = smart_widgets
    assert conf_btn.isVisible()
    assert accept_btn.isVisible()
    assert reject_btn.isVisible()
    assert "87.0%" in conf_btn.text()

    qtbot.mouseClick(accept_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    sample = window.dataset_explorer_controller.get_sample_by_path(path)
    assert isinstance(sample, dict)
    assert sample["labels"]["action"]["label"] == "shot"
    assert "confidence_score" not in sample["labels"]["action"]
    assert tree_item.text() == "clip_1"


@pytest.mark.gui
def test_classification_inference_loading_cue_toggles_controls(
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
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    panel = window.classification_panel
    group = panel.label_groups["action"]

    panel.show_inference_loading(True)
    qtbot.wait(50)

    assert panel._inference_loading_dialog.isVisible() is True
    assert group.btn_smart_infer.isEnabled() is False
    assert group.btn_smart_infer.text() == "Loading..."
    assert panel.head_tabs_widget.isEnabled() is False

    panel.show_inference_loading(False)
    qtbot.wait(50)

    assert panel._inference_loading_dialog.isVisible() is False
    assert group.btn_smart_infer.isEnabled() is True
    assert group.btn_smart_infer.text() == "Smart Inference"
    assert panel.head_tabs_widget.isEnabled() is True


@pytest.mark.gui
def test_classification_inference_cancel_dispatches_to_manager(
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
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.classification_editor_controller
    panel = window.classification_panel

    calls = {"count": 0}
    monkeypatch.setattr(
        controller.inference_manager,
        "cancel_active_inference",
        lambda: calls.__setitem__("count", calls["count"] + 1) or True,
    )

    panel.inferenceCancelRequested.emit()
    qtbot.wait(20)
    assert calls["count"] == 1


@pytest.mark.gui
def test_classification_clear_smart_restores_manual_or_removes_label_when_no_manual(
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
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.classification_editor_controller
    path = controller.get_current_action_path()
    assert path

    # With manual baseline present, clear restores the previous manual label.
    panel = window.classification_panel
    group = panel.label_groups["action"]
    pass_btn = next(btn for btn in group.radio_group.buttons() if btn.text() == "pass")
    qtbot.mouseClick(pass_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    controller.inference_manager._on_inference_success(
        "action",
        "shot",
        {"shot": 0.91, "Other Uncertainties": 0.09},
    )
    qtbot.wait(50)
    smart_widgets = window.classification_panel.get_head_row_smart_widgets("action", "shot")
    assert smart_widgets is not None
    _conf_btn, _accept_btn, reject_btn = smart_widgets
    qtbot.mouseClick(reject_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    sample = window.dataset_explorer_controller.get_sample_by_path(path)
    assert isinstance(sample, dict)
    assert sample["labels"]["action"]["label"] == "pass"
    assert "confidence_score" not in sample["labels"]["action"]

    # Without manual baseline, clear removes the smart annotation head.
    controller.clear_current_manual_annotation()
    qtbot.wait(50)
    controller.inference_manager._on_inference_success(
        "action",
        "shot",
        {"shot": 0.91, "Other Uncertainties": 0.09},
    )
    qtbot.wait(50)
    smart_widgets = window.classification_panel.get_head_row_smart_widgets("action", "shot")
    assert smart_widgets is not None
    _conf_btn, _accept_btn, reject_btn = smart_widgets
    qtbot.mouseClick(reject_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    sample = window.dataset_explorer_controller.get_sample_by_path(path)
    assert isinstance(sample, dict)
    assert "labels" not in sample or "action" not in sample.get("labels", {})


@pytest.mark.gui
def test_classification_unknown_prediction_label_mapping_applies_selected_label(
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
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    monkeypatch.setattr(
        "controllers.classification.inference_manager.QInputDialog.getItem",
        lambda *args, **kwargs: ("pass", True),
    )
    controller = window.classification_editor_controller
    controller.inference_manager._on_inference_success(
        "action",
        "unknown_pred",
        {"unknown_pred": 0.83},
    )
    qtbot.wait(50)

    path = controller.get_current_action_path()
    assert path
    sample = window.dataset_explorer_controller.get_sample_by_path(path)
    assert isinstance(sample, dict)
    assert sample["labels"]["action"]["label"] == "pass"
    assert sample["labels"]["action"]["confidence_score"] == pytest.approx(0.83)

    controller.inference_manager._on_inference_success(
        "action",
        "shot",
        {"shot": 0.75, "Other Uncertainties": 0.25},
    )
    qtbot.wait(50)
    smart_widgets = window.classification_panel.get_head_row_smart_widgets("action", "shot")
    assert smart_widgets is not None
    _conf_btn, _accept_btn, reject_btn = smart_widgets
    qtbot.mouseClick(reject_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    sample = window.dataset_explorer_controller.get_sample_by_path(path)
    assert isinstance(sample, dict)
    assert "labels" not in sample or "action" not in sample.get("labels", {})


@pytest.mark.gui
def test_classification_schema_label_delete_allows_removing_last_label(
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
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    controller = window.classification_editor_controller
    controller.remove_custom_type("action", "pass")
    qtbot.wait(50)
    controller.remove_custom_type("action", "shot")
    qtbot.wait(50)

    labels = window.dataset_explorer_controller.label_definitions["action"]["labels"]
    assert labels == []


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
#     window.dataset_explorer_controller.import_annotations()

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

#     assert window.dataset_explorer_controller.manual_annotations[current_path]["action"] == "shot"

#     window.history_manager.perform_undo()
#     qtbot.wait(50)
#     assert current_path not in window.dataset_explorer_controller.manual_annotations
#     assert window.classification_panel.get_annotation().get("action") in (None, "")

#     window.history_manager.perform_redo()
#     qtbot.wait(50)
#     assert window.dataset_explorer_controller.manual_annotations[current_path]["action"] == "shot"
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
#     window.dataset_explorer_controller.import_annotations()
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
