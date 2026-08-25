"""
Undo/redo contract coverage:
- every dataset_json mutation adds exactly one undo step
- non-mutating actions add no undo steps
"""

import copy
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QMessageBox
from inference_types import InferenceResult


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
    "question_answer": 4,
}


def _open_project(window, monkeypatch, project_json_path: Path):
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()


def _select_top_row(window, qtbot, row: int = 0):
    index = window.tree_model.index(row, 0)
    assert index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(index)
    qtbot.wait(50)
    return index


def _json_snapshot(window):
    return copy.deepcopy(window.dataset_explorer_controller.dataset_json)


def _stack_sizes(window):
    return len(window.dataset_explorer_controller.undo_stack), len(window.dataset_explorer_controller.redo_stack)


def _assert_mutating_action_creates_single_history_entry(window, qtbot, action):
    before_json = _json_snapshot(window)
    undo_before, redo_before = _stack_sizes(window)

    action()
    qtbot.wait(50)

    after_json = _json_snapshot(window)
    assert after_json != before_json
    undo_after, redo_after = _stack_sizes(window)
    assert undo_after == undo_before + 1
    assert redo_after == 0

    window.history_manager.perform_undo()
    qtbot.wait(50)
    assert _json_snapshot(window) == before_json

    window.history_manager.perform_redo()
    qtbot.wait(50)
    assert _json_snapshot(window) == after_json


def _assert_non_mutating_action_keeps_history_unchanged(window, qtbot, action, assert_json_unchanged=True):
    before_json = _json_snapshot(window)
    undo_before, redo_before = _stack_sizes(window)

    action()
    qtbot.wait(50)

    if assert_json_unchanged:
        assert _json_snapshot(window) == before_json
    undo_after, redo_after = _stack_sizes(window)
    assert undo_after == undo_before
    assert redo_after == redo_before


@pytest.mark.gui
def test_history_contract_classification_mutations(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("classification")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["classification"])
    qtbot.wait(50)

    controller = window.classification_editor_controller
    monkeypatch.setattr(controller, "_prompt_head_type", lambda _name: "single_label")
    monkeypatch.setattr(
        "controllers.classification.classification_editor_controller.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: controller.handle_add_label_head("history_head"),
    )

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: controller.handle_rename_label_head("history_head", "history_head_renamed"),
    )

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: controller.handle_remove_label_head("history_head_renamed"),
    )

    def _select_shot_label():
        panel = window.classification_panel
        group = panel.label_groups["action"]
        shot_btn = next(btn for btn in group.radio_group.buttons() if btn.text() == "shot")
        shot_btn.click()

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _select_shot_label)

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        window.classification_editor_controller.clear_current_manual_annotation,
    )

    result = InferenceResult(
        "request", "classification", "model",
        ({"sample_id": controller.current_sample_id, "labels": {"action": {"label": "pass", "confidence_score": 0.9}}},),
    )
    _assert_non_mutating_action_keeps_history_unchanged(
        window, qtbot, lambda: controller.apply_shared_inference_result(result, {"head": "action"})
    )

    _assert_non_mutating_action_keeps_history_unchanged(
        window, qtbot, lambda: controller.reject_smart_annotation_head("action")
    )

    _assert_non_mutating_action_keeps_history_unchanged(
        window, qtbot, lambda: controller.apply_shared_inference_result(result, {"head": "action"})
    )

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        window.classification_editor_controller.confirm_smart_annotation_as_manual,
    )

    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        window.classification_editor_controller.clear_current_smart_annotation,
    )

@pytest.mark.gui
def test_history_contract_localization_event_and_schema_mutations(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"])
    qtbot.wait(50)

    controller = window.localization_editor_controller

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: controller._on_spotting_triggered("ball_action", "shot"),
    )

    def _modify_first_event():
        path = controller.current_video_path
        events = list(window.dataset_explorer_controller.localization_events.get(path, []))
        assert events
        old_event = copy.deepcopy(events[0])
        new_event = copy.deepcopy(old_event)
        new_event["position_ms"] = int(old_event.get("position_ms", 0)) + 111
        controller._on_annotation_modified(old_event, new_event)

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _modify_first_event)

    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    def _delete_first_event():
        path = controller.current_video_path
        events = list(window.dataset_explorer_controller.localization_events.get(path, []))
        assert events
        controller._on_delete_single_annotation(copy.deepcopy(events[0]))

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _delete_first_event)

    _assert_mutating_action_creates_single_history_entry(window, qtbot, lambda: controller._on_head_added("history_head"))
    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: controller._on_head_renamed("history_head", "history_head_renamed"),
    )

    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QMessageBox.warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: controller._on_head_deleted("history_head_renamed"),
    )

    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QInputDialog.getText",
        lambda *args, **kwargs: ("history_label", True),
    )

    def _add_label_without_event_injection():
        # Keep the action to a pure schema mutation for strict single-step expectations.
        original_path = controller.current_video_path
        controller.current_video_path = None
        try:
            controller._on_label_add_req("ball_action")
        finally:
            controller.current_video_path = original_path

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _add_label_without_event_injection)

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: controller._on_label_color_req("ball_action", "pass", QColor("#ff8844").name()),
    )

    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QInputDialog.getText",
        lambda *args, **kwargs: ("history_label_renamed", True),
    )
    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: controller._on_label_rename_req("ball_action", "history_label"),
    )

    monkeypatch.setattr(
        "controllers.localization.localization_editor_controller.QMessageBox.warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: controller._on_label_delete_req("ball_action", "history_label_renamed"),
    )


@pytest.mark.gui
def test_history_contract_localization_smart_mutations(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"])
    qtbot.wait(50)

    controller = window.localization_editor_controller

    controller.current_head = "ball_action"
    def result(label, position, confidence):
        return InferenceResult(
            f"request-{position}", "localization", "model",
            ({"sample_id": controller.current_sample_id, "events": [{"head": "ball_action", "label": label, "position_ms": position, "confidence_score": confidence}]},),
        )

    _assert_non_mutating_action_keeps_history_unchanged(
        window, qtbot, lambda: controller.apply_shared_inference_result(result("pass", 3500, 0.9), {"head": "ball_action"})
    )

    def _confirm_first_smart_event():
        pending = controller._pending_predictions[controller.current_sample_id]
        assert pending
        controller._on_confirm_single_annotation(copy.deepcopy(pending[0]))

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        _confirm_first_smart_event,
    )

    _assert_non_mutating_action_keeps_history_unchanged(
        window, qtbot, lambda: controller.apply_shared_inference_result(result("shot", 3600, 0.85), {"head": "ball_action"})
    )

    def _reject_first_smart_event():
        pending = controller._pending_predictions[controller.current_sample_id]
        assert pending
        controller._on_reject_single_annotation(copy.deepcopy(pending[0]))

    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        _reject_first_smart_event,
    )


@pytest.mark.gui
def test_localization_review_shortcuts_accept_reject_and_select_adjacent(
    window, monkeypatch, qtbot, synthetic_project_json
):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"])
    qtbot.wait(50)

    controller = window.localization_editor_controller
    controller.current_head = "ball_action"
    result = InferenceResult(
        "shortcut-review",
        "localization",
        "model",
        ({
            "sample_id": controller.current_sample_id,
            "events": [
                {"head": "ball_action", "label": "pass", "position_ms": 2000, "confidence_score": 0.9},
                {"head": "ball_action", "label": "pass", "position_ms": 3000, "confidence_score": 0.8},
            ],
        },),
    )
    controller.apply_shared_inference_result(result, {"head": "ball_action"})
    table = window.localization_panel.table.table
    model = window.localization_panel.table.model
    assert model.rowCount() == 3
    table.selectRow(1)

    undo_before = len(window.dataset_explorer_controller.undo_stack)
    window.shortcut_localization_accept.activated.emit()
    qtbot.wait(20)

    assert len(window.dataset_explorer_controller.undo_stack) == undo_before + 1
    accepted = model.get_annotation_at(1)
    assert accepted["position_ms"] == 2000
    assert "confidence_score" not in accepted
    assert table.currentIndex().row() == 2
    assert model.get_annotation_at(2)["confidence_score"] == pytest.approx(0.8)

    window.shortcut_localization_reject.activated.emit()
    qtbot.wait(20)

    assert len(window.dataset_explorer_controller.undo_stack) == undo_before + 1
    assert model.rowCount() == 2
    assert table.currentIndex().row() == 1
    assert model.get_annotation_at(1)["position_ms"] == 2000


@pytest.mark.gui
def test_localization_review_shortcut_rejects_persisted_inference_with_undo_redo(
    window, monkeypatch, qtbot, synthetic_project_json
):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"])
    qtbot.wait(50)

    controller = window.localization_editor_controller
    inferred = {
        "head": "ball_action",
        "label": "pass",
        "position_ms": 2500,
        "confidence_score": 0.75,
    }
    window.history_manager.execute_localization_event_add(
        controller.current_sample_id, inferred
    )
    controller.on_selected_sample_changed(
        window.dataset_explorer_controller.get_sample(controller.current_sample_id)
    )
    model = window.localization_panel.table.model
    table = window.localization_panel.table.table
    inferred_row = next(
        row
        for row in range(model.rowCount())
        if "confidence_score" in model.get_annotation_at(row)
    )
    table.selectRow(inferred_row)
    before_reject = _json_snapshot(window)
    undo_before = len(window.dataset_explorer_controller.undo_stack)

    window.shortcut_localization_reject.activated.emit()
    qtbot.wait(20)
    after_reject = _json_snapshot(window)
    assert len(window.dataset_explorer_controller.undo_stack) == undo_before + 1
    assert not any(
        "confidence_score" in (model.get_annotation_at(row) or {})
        for row in range(model.rowCount())
    )

    window.history_manager.perform_undo()
    qtbot.wait(20)
    assert _json_snapshot(window) == before_reject
    window.history_manager.perform_redo()
    qtbot.wait(20)
    assert _json_snapshot(window) == after_reject


@pytest.mark.gui
def test_localization_review_shortcut_accepts_persisted_inference_with_undo_redo(
    window, monkeypatch, qtbot, synthetic_project_json
):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"])
    qtbot.wait(50)

    controller = window.localization_editor_controller
    inferred = {
        "head": "ball_action",
        "label": "pass",
        "position_ms": 2500,
        "confidence_score": 0.75,
        "inference_model_id": "test-model",
    }
    window.history_manager.execute_localization_event_add(
        controller.current_sample_id, inferred
    )
    controller.on_selected_sample_changed(
        window.dataset_explorer_controller.get_sample(controller.current_sample_id)
    )
    model = window.localization_panel.table.model
    table = window.localization_panel.table.table
    inferred_row = next(
        row
        for row in range(model.rowCount())
        if "confidence_score" in model.get_annotation_at(row)
    )
    table.selectRow(inferred_row)
    before_accept = _json_snapshot(window)
    undo_before = len(window.dataset_explorer_controller.undo_stack)

    window.shortcut_localization_accept.activated.emit()
    qtbot.wait(20)
    after_accept = _json_snapshot(window)
    accepted = next(
        model.get_annotation_at(row)
        for row in range(model.rowCount())
        if model.get_annotation_at(row)["position_ms"] == 2500
    )
    assert len(window.dataset_explorer_controller.undo_stack) == undo_before + 1
    assert "confidence_score" not in accepted
    assert "inference_model_id" not in accepted

    window.history_manager.perform_undo()
    qtbot.wait(20)
    assert _json_snapshot(window) == before_accept
    window.history_manager.perform_redo()
    qtbot.wait(20)
    assert _json_snapshot(window) == after_accept


@pytest.mark.gui
def test_localization_review_shortcut_requires_active_mode_and_inferred_selection(
    window, monkeypatch, qtbot, synthetic_project_json
):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    table = window.localization_panel.table.table
    table.selectRow(0)
    before = _json_snapshot(window)

    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["classification"])
    window.shortcut_localization_reject.activated.emit()
    assert _json_snapshot(window) == before

    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"])
    window.shortcut_localization_reject.activated.emit()
    assert _json_snapshot(window) == before
    assert "confidence score" in window.statusBar().currentMessage()


@pytest.mark.gui
def test_localization_review_shortcut_rejects_only_row_and_clears_selection(
    window, monkeypatch, qtbot, synthetic_project_json
):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"])

    controller = window.localization_editor_controller
    sample_id = controller.current_sample_id
    controller._current_sample_snapshot["events"] = []
    controller.apply_shared_inference_result(
        InferenceResult(
            "only-row",
            "localization",
            "model",
            ({
                "sample_id": sample_id,
                "events": [{
                    "head": "ball_action",
                    "label": "pass",
                    "position_ms": 500,
                    "confidence_score": 0.6,
                }],
            },),
        ),
        {"head": "ball_action"},
    )
    model = window.localization_panel.table.model
    table = window.localization_panel.table.table
    assert model.rowCount() == 1
    table.selectRow(0)

    window.shortcut_localization_reject.activated.emit()
    qtbot.wait(20)
    assert model.rowCount() == 0
    assert not table.selectionModel().selectedRows()


@pytest.mark.gui
def test_history_contract_description_mutation(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("description")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["description"])
    qtbot.wait(50)

    def _edit_caption():
        window.description_panel.caption_edit.setPlainText("History contract description edit.")
        window.desc_editor_controller.save_current_annotation()
        qtbot.wait(350)

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _edit_caption)

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        window.desc_editor_controller.add_caption,
    )

    def _delete_last_caption():
        panel = window.description_panel
        panel.descCaptionsList.setCurrentRow(panel.descCaptionsList.count() - 1)
        window.desc_editor_controller.delete_selected_caption()

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _delete_last_caption)

    result = InferenceResult(
        "description-request",
        "description",
        "caption-model",
        ({"sample_id": "clip_1", "captions": [{"lang": "en", "text": "Predicted"}]},),
    )
    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        lambda: window.desc_editor_controller.apply_shared_inference_result(result),
    )
    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        window.desc_editor_controller.reject_smart_inference,
    )
    window.desc_editor_controller.apply_shared_inference_result(result)
    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        window.desc_editor_controller.confirm_smart_inference,
    )


@pytest.mark.gui
def test_history_contract_dense_mutations(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("dense_description")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["dense_description"])
    qtbot.wait(50)

    controller = window.dense_editor_controller
    monkeypatch.setattr(window.media_controller, "current_position_ms", lambda: 5500)
    monkeypatch.setattr(
        "controllers.dense_description.dense_editor_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: ("Dense history event", True),
    )

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        controller._on_add_event_requested,
    )

    def _edit_dense_text():
        events = list(window.dataset_explorer_controller.dense_description_events.get(controller.current_video_path, []))
        assert events
        old_event = copy.deepcopy(events[0])
        new_event = copy.deepcopy(old_event)
        new_event["text"] = "Dense history event (edited)"
        controller._on_annotation_modified(old_event, new_event)

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _edit_dense_text)

    def _delete_dense_event():
        events = list(window.dataset_explorer_controller.dense_description_events.get(controller.current_video_path, []))
        assert events
        controller._on_delete_single_annotation(copy.deepcopy(events[0]))

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _delete_dense_event)


@pytest.mark.gui
def test_history_contract_question_answer_mutations(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("question_answer")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["question_answer"])
    qtbot.wait(50)

    controller = window.qa_editor_controller
    panel = window.qa_panel

    def _edit_answer():
        monkeypatch.setattr(
            "controllers.question_answer.qa_editor_controller.QInputDialog.getMultiLineText",
            lambda *args, **kwargs: ("History contract Q/A edit.", True),
        )
        panel._on_answer_item_double_clicked(panel.answer_list.item(0))
        controller.save_current_answers()
        qtbot.wait(300)

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _edit_answer)

    def _add_second_answer():
        monkeypatch.setattr(
            "controllers.question_answer.qa_editor_controller.QInputDialog.getMultiLineText",
            lambda *args, **kwargs: ("Second grouped answer.", True),
        )
        panel.add_answer_button.click()
        controller.save_current_answers()
        qtbot.wait(300)

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _add_second_answer)


@pytest.mark.gui
def test_history_contract_dataset_explorer_mutations(window, monkeypatch, qtbot, synthetic_project_json, tmp_path):
    project_json_path = synthetic_project_json("mixed", item_count=2)
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    controller = window.dataset_explorer_controller

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: controller._on_header_draft_changed({"description": "History header update"}),
    )

    def _rename_first_sample():
        idx = window.tree_model.index(0, 0)
        assert window.tree_model.setData(idx, "clip_1_history", Qt.ItemDataRole.EditRole)

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _rename_first_sample)

    repo_root = Path(__file__).resolve().parents[2]
    source_video = repo_root / "tests" / "data" / "test_video_3.mp4"
    assert source_video.exists()
    added_video = tmp_path / "history_added.mp4"
    added_video.write_bytes(source_video.read_bytes())
    monkeypatch.setattr(
        controller,
        "_pick_files_or_folders_for_add_data",
        lambda _start_dir: [str(added_video)],
    )
    _assert_mutating_action_creates_single_history_entry(window, qtbot, controller.handle_add_sample)

    def _remove_selected_sample():
        idx = window.dataset_explorer_panel.tree.currentIndex()
        if not idx.isValid():
            idx = window.tree_model.index(0, 0)
        controller.handle_remove_item(idx)

    _assert_mutating_action_creates_single_history_entry(window, qtbot, _remove_selected_sample)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QMessageBox.exec",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    _assert_mutating_action_creates_single_history_entry(window, qtbot, controller.handle_clear_workspace)


@pytest.mark.gui
def test_history_contract_dataset_explorer_remove_input_mutation(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("multiview")
    _open_project(window, monkeypatch, project_json_path)

    parent_idx = _select_top_row(window, qtbot, 0)
    child_idx = window.tree_model.index(0, 0, parent_idx)
    assert child_idx.isValid()

    _assert_mutating_action_creates_single_history_entry(
        window,
        qtbot,
        lambda: window.dataset_explorer_controller.handle_remove_item(child_idx),
    )


@pytest.mark.gui
def test_history_contract_non_mutating_navigation_actions(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("mixed", item_count=2)
    _open_project(window, monkeypatch, project_json_path)
    first_idx = _select_top_row(window, qtbot, 0)
    second_idx = window.tree_model.index(1, 0)
    assert first_idx.isValid() and second_idx.isValid()

    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        lambda: window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"]),
    )
    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        lambda: window.dataset_explorer_panel.tree.setCurrentIndex(second_idx),
    )
    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        lambda: window.dataset_explorer_panel.filter_combo.setCurrentIndex(1),
    )
    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        lambda: window.dataset_explorer_controller.navigate_samples(-1),
    )

    panel = window.dataset_explorer_panel
    if hasattr(panel, "header_tabs"):
        json_tab = None
        for idx in range(panel.header_tabs.count()):
            if panel.header_tabs.tabText(idx).strip().lower() == "json":
                json_tab = idx
                break
        if json_tab is not None:
            _assert_non_mutating_action_keeps_history_unchanged(
                window,
                qtbot,
                lambda: panel.header_tabs.setCurrentIndex(json_tab),
            )


@pytest.mark.gui
def test_history_contract_save_and_export_do_not_touch_stack(window, monkeypatch, qtbot, synthetic_project_json, tmp_path):
    project_json_path = synthetic_project_json("classification")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    export_path = tmp_path / "history_export.json"
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "JSON (*.json)"),
    )

    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        window.dataset_explorer_controller.save_project,
        assert_json_unchanged=False,
    )
    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        window.dataset_explorer_controller.export_project,
        assert_json_unchanged=False,
    )


@pytest.mark.gui
def test_history_contract_noop_edits_do_not_touch_stack(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("classification")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    window.classification_editor_controller.save_manual_annotation({"action": "pass"})
    qtbot.wait(50)

    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        lambda: window.classification_editor_controller.save_manual_annotation({"action": "pass"}),
    )

    current_desc = window.dataset_explorer_controller.dataset_json.get("description")
    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        lambda: window.dataset_explorer_controller._on_header_draft_changed({"description": current_desc}),
    )

    def _rename_same_id():
        idx = window.tree_model.index(0, 0)
        same_id = str(idx.data(window.tree_model.DataIdRole) or idx.data())
        assert not window.tree_model.setData(idx, same_id, Qt.ItemDataRole.EditRole)

    _assert_non_mutating_action_keeps_history_unchanged(window, qtbot, _rename_same_id)


@pytest.mark.gui
def test_history_contract_noop_description_event_and_dense_edits_do_not_touch_stack(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    # Description no-op
    description_json = synthetic_project_json("description")
    _open_project(window, monkeypatch, description_json)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["description"])
    qtbot.wait(50)

    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        window.desc_editor_controller.save_current_annotation,
    )

    # Localization no-op event modification
    window.dataset_explorer_controller.close_project()
    localization_json = synthetic_project_json("localization")
    _open_project(window, monkeypatch, localization_json)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"])
    qtbot.wait(50)
    loc_controller = window.localization_editor_controller

    def _localization_noop_modify():
        events = list(window.dataset_explorer_controller.localization_events.get(loc_controller.current_video_path, []))
        assert events
        old_event = copy.deepcopy(events[0])
        loc_controller._on_annotation_modified(old_event, copy.deepcopy(old_event))

    _assert_non_mutating_action_keeps_history_unchanged(window, qtbot, _localization_noop_modify)

    # Dense no-op event modification
    window.dataset_explorer_controller.close_project()
    dense_json = synthetic_project_json("dense_description")
    _open_project(window, monkeypatch, dense_json)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["dense_description"])
    qtbot.wait(50)
    dense_controller = window.dense_editor_controller

    def _dense_noop_modify():
        events = list(window.dataset_explorer_controller.dense_description_events.get(dense_controller.current_video_path, []))
        assert events
        old_event = copy.deepcopy(events[0])
        dense_controller._on_annotation_modified(old_event, copy.deepcopy(old_event))

    _assert_non_mutating_action_keeps_history_unchanged(window, qtbot, _dense_noop_modify)

    monkeypatch.setattr(
        "controllers.dense_description.dense_editor_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: ("", False),
    )
    _assert_non_mutating_action_keeps_history_unchanged(window, qtbot, dense_controller._on_add_event_requested)

    monkeypatch.setattr(
        "controllers.dense_description.dense_editor_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: ("   ", True),
    )
    _assert_non_mutating_action_keeps_history_unchanged(window, qtbot, dense_controller._on_add_event_requested)

    # Q/A no-op answer save
    window.dataset_explorer_controller.close_project()
    qa_json = synthetic_project_json("question_answer")
    _open_project(window, monkeypatch, qa_json)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["question_answer"])
    qtbot.wait(50)

    _assert_non_mutating_action_keeps_history_unchanged(
        window,
        qtbot,
        window.qa_editor_controller.save_current_answers,
    )


@pytest.mark.gui
def test_history_contract_empty_stack_undo_redo_is_noop(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("classification")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    window.dataset_explorer_controller.undo_stack.clear()
    window.dataset_explorer_controller.redo_stack.clear()

    _assert_non_mutating_action_keeps_history_unchanged(window, qtbot, window.history_manager.perform_undo)
    _assert_non_mutating_action_keeps_history_unchanged(window, qtbot, window.history_manager.perform_redo)


@pytest.mark.gui
def test_input_utc_start_update_is_one_undoable_semantic_mutation(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    model = window.dataset_explorer_controller
    sample_id = model.current_selected_sample_id
    source = model.get_media_sources_by_id(sample_id)[0]
    input_path = source["path"]
    model.get_sample(sample_id)["dense_captions"] = [
        {"position_ms": 1500, "lang": "en", "text": "Absolute-time caption"}
    ]
    model._rebuild_runtime_index()

    before_json = _json_snapshot(window)
    assert window.history_manager.execute_input_utc_start_update(
        sample_id,
        input_path,
        "2022-12-03T15:27:59.461000+02:00",
    )
    after_json = _json_snapshot(window)
    assert after_json != before_json
    assert after_json["data"][0]["inputs"][0]["UTC_time_start"] == (
        "2022-12-03 13:27:59.461000"
    )
    assert _stack_sizes(window) == (1, 0)

    # An equivalent instant, expressed differently, is a semantic no-op.
    assert not window.history_manager.execute_input_utc_start_update(
        sample_id,
        input_path,
        "2022-12-03 13:27:59.461Z",
        999,
    )
    assert _json_snapshot(window) == after_json
    assert _stack_sizes(window) == (1, 0)

    window.history_manager.perform_undo()
    qtbot.wait(50)
    assert _json_snapshot(window) == before_json
    assert _stack_sizes(window) == (0, 1)

    # A new synchronization after undo clears the previous redo branch.
    assert window.history_manager.execute_input_utc_start_update(
        sample_id,
        input_path,
        "2022-12-03 13:28:01.000000",
        "2022-12-03 13:27:59.461000",
    )
    replacement_json = _json_snapshot(window)
    assert replacement_json["data"][0]["events"][0]["position_ms"] == -539
    assert replacement_json["data"][0]["events"][0]["timestamp_utc"] == (
        "2022-12-03 13:28:00.461000"
    )
    assert replacement_json["data"][0]["dense_captions"][0]["position_ms"] == -39
    assert replacement_json["data"][0]["dense_captions"][0]["timestamp_utc"] == (
        "2022-12-03 13:28:00.961000"
    )
    assert _stack_sizes(window) == (1, 0)

    window.history_manager.perform_undo()
    qtbot.wait(50)
    assert _json_snapshot(window) == before_json
    window.history_manager.perform_redo()
    qtbot.wait(50)
    assert _json_snapshot(window) == replacement_json


@pytest.mark.gui
def test_temporal_mutations_write_absolute_and_compatibility_times(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    model = window.dataset_explorer_controller
    sample_id = model.current_selected_sample_id
    window.history_manager.on_timeline_origin_changed(
        sample_id, "2026-01-01 12:00:00.000000"
    )
    new_event = {
        "head": "ball_action",
        "label": "shot",
        "position_ms": 2250,
    }

    window.history_manager.execute_localization_event_add(sample_id, new_event)
    saved_event = model.get_sample(sample_id)["events"][-1]
    assert saved_event["position_ms"] == 2250
    assert saved_event["timestamp_utc"] == "2026-01-01 12:00:02.250000"

    moved = copy.deepcopy(saved_event)
    moved["position_ms"] = 3250
    window.history_manager.execute_localization_event_mod(sample_id, saved_event, moved)
    moved_event = next(
        event
        for event in model.get_sample(sample_id)["events"]
        if event.get("label") == "shot"
    )
    assert moved_event["timestamp_utc"] == "2026-01-01 12:00:03.250000"


@pytest.mark.gui
def test_explicit_input_utc_removal_is_one_undoable_absolute_time_mutation(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    model = window.dataset_explorer_controller
    sample_id = model.current_selected_sample_id
    sample = model.get_sample(sample_id)
    source = model.get_media_sources_by_id(sample_id)[0]
    sample["inputs"][0]["UTC_time_start"] = "2026-01-01 12:00:00.000000"
    sample["events"][0]["timestamp_utc"] = "2026-01-01 12:00:01.000000"
    model._rebuild_runtime_index()
    model.undo_stack.clear()
    model.redo_stack.clear()

    before_json = _json_snapshot(window)
    assert window.history_manager.execute_input_utc_start_removal(
        sample_id,
        source["path"],
        "2026-01-01 12:00:00.000000",
    )
    after_json = _json_snapshot(window)
    assert "UTC_time_start" not in after_json["data"][0]["inputs"][0]
    assert after_json["data"][0]["events"][0]["timestamp_utc"] == (
        "2026-01-01 12:00:01.000000"
    )
    assert _stack_sizes(window) == (1, 0)

    window.history_manager.perform_undo()
    qtbot.wait(20)
    assert _json_snapshot(window) == before_json
    window.history_manager.perform_redo()
    qtbot.wait(20)
    assert _json_snapshot(window) == after_json
