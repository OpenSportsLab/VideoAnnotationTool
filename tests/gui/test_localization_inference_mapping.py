"""Run-level class mapping and atomic localization inference commits."""

import copy

import pytest
from PyQt6.QtWidgets import QDialog, QDialogButtonBox

from inference_types import InferenceResult
from ui.localization.label_mapping_dialog import LocalizationClassMappingDialog


def _open_localization_project(window, monkeypatch, project_path):
    monkeypatch.setattr(
        window.dataset_explorer_controller,
        "check_and_close_current_project",
        lambda: True,
    )
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    window.right_tabs.setCurrentIndex(1)
    window.localization_panel.annot_mgmt.tabs.set_current_head("ball_action")


def _result(request_id="mapping-request"):
    return InferenceResult(
        request_id,
        "localization",
        "model-one",
        (
            {
                "item_id": "item-1",
                "sample_id": "clip_1",
                "events": [
                    {"label": "pass", "position_ms": 1100, "confidence_score": 0.8},
                    {"label": "whistle", "position_ms": 1200, "confidence_score": 0.6},
                    {"label": "whistle", "position_ms": 1300, "confidence_score": 0.7},
                    {"label": "ignore-me", "position_ms": 1400, "confidence_score": 0.5},
                ],
            },
            {
                "item_id": "item-2",
                "sample_id": "clip_2",
                "events": [
                    {"label": "whistle", "position_ms": 2200, "confidence_score": 0.9},
                ],
            },
        ),
    )


def _complete_shared_result(window, result, backend):
    window._pending_inference_requests[result.request_id] = {
        "task": "localization",
        "sample_ids": ("clip_1", "clip_2"),
        "request_items": {"item-1": "clip_1", "item-2": "clip_2"},
        "project_generation": window.dataset_explorer_controller.project_generation,
        "context": {"head": "ball_action"},
        "backend": backend,
        "model_id": result.model_id,
        "invalidated": False,
    }
    window._on_shared_inference_completed(result.request_id, result)


@pytest.mark.gui
def test_class_mapping_dialog_defaults_and_new_head_validation(qtbot):
    dialog = LocalizationClassMappingDialog(
        ["pass", "whistle"],
        "ball_action",
        ["pass", "shot"],
        {
            "ball_action": {"labels": ["pass", "shot"]},
            "other_head": {"labels": ["whistle", "header"]},
        },
    )
    qtbot.addWidget(dialog)

    assert dialog._combos["pass"].currentData() == "pass"
    assert dialog._combos["whistle"].currentData() is None
    assert dialog.target_head_combo.currentData() == "ball_action"
    assert dialog.decision() == (
        "ball_action", None, {"pass": "pass", "whistle": None}
    )

    dialog.target_head_combo.setCurrentIndex(
        dialog.target_head_combo.findData("other_head")
    )
    assert dialog._combos["pass"].currentData() is None
    assert dialog._combos["whistle"].currentData() == "whistle"
    assert dialog.decision() == (
        "other_head", None, {"pass": None, "whistle": "whistle"}
    )

    dialog.new_head_radio.setChecked(True)
    assert not dialog.mapping_table.isEnabled()
    assert dialog.new_head_name.isEnabled()
    apply_button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    dialog.new_head_name.setText("  ")
    assert not apply_button.isEnabled()
    dialog.new_head_name.setText("OTHER_HEAD")
    assert not apply_button.isEnabled()
    dialog.new_head_name.setText("new_actions")
    assert apply_button.isEnabled()
    assert dialog.decision() == (
        "new_actions", ["pass", "whistle"],
        {"pass": "pass", "whistle": "whistle"},
    )


@pytest.mark.gui
def test_inference_can_target_a_different_existing_head(qtbot, monkeypatch):
    from controllers.localization import LocalizationEditorController
    from ui.localization import LocalizationAnnotationPanel

    panel = LocalizationAnnotationPanel()
    qtbot.addWidget(panel)
    controller = LocalizationEditorController(panel)
    controller.setup_connections()
    controller.on_schema_context_changed({
        "ball_action": {"type": "single_label", "labels": ["pass"]},
        "official_action": {"type": "single_label", "labels": ["whistle"]},
    })
    commits = []
    controller.locInferenceCommitRequested.connect(lambda *args: commits.append(args))

    def choose_other_head(dialog):
        dialog.target_head_combo.setCurrentIndex(
            dialog.target_head_combo.findData("official_action")
        )
        dialog._combos["PASS"].setCurrentText("whistle")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LocalizationClassMappingDialog, "exec", choose_other_head)
    result = InferenceResult(
        "other-head", "localization", "model-one",
        ({"sample_id": "clip", "events": [
            {"label": "PASS", "position_ms": 2500, "confidence_score": 0.8}
        ]},),
    )

    assert controller.apply_shared_inference_result(
        result, {"head": "ball_action"}
    ) is True
    assert len(commits) == 1
    target_head, new_labels, events_by_sample = commits[0]
    assert target_head == "official_action"
    assert new_labels is None
    assert events_by_sample["clip"][0]["head"] == "official_action"
    assert events_by_sample["clip"][0]["label"] == "whistle"


@pytest.mark.gui
@pytest.mark.parametrize("backend", ["local", "remote"])
def test_shared_completion_maps_once_across_samples_and_undoes_atomically(
    window, monkeypatch, qtbot, synthetic_project_json, backend
):
    _open_localization_project(
        window, monkeypatch, synthetic_project_json("localization", item_count=2)
    )
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(1, 0))
    qtbot.wait(20)
    media_loads = []
    monkeypatch.setattr(
        window.media_controller,
        "load_and_play",
        lambda *args, **kwargs: media_loads.append((args, kwargs)),
    )
    before = copy.deepcopy(window.dataset_explorer_controller.dataset_json)
    undo_before = len(window.dataset_explorer_controller.undo_stack)
    dialogs = []

    def choose_mapping(dialog):
        dialogs.append(dialog)
        assert list(dialog._combos) == ["pass", "whistle", "ignore-me"]
        assert dialog._combos["pass"].currentData() == "pass"
        assert dialog._combos["whistle"].currentData() is None
        assert dialog._combos["ignore-me"].currentData() is None
        dialog._combos["whistle"].setCurrentText("shot")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LocalizationClassMappingDialog, "exec", choose_mapping)
    _complete_shared_result(window, _result(), backend)

    assert len(dialogs) == 1
    assert window.right_tabs.currentIndex() == 1
    assert window.localization_panel.annot_mgmt.tabs.get_current_head() == "ball_action"
    assert media_loads == []
    sample_1 = window.dataset_explorer_controller.get_sample("clip_1")
    sample_2 = window.dataset_explorer_controller.get_sample("clip_2")
    predicted_1 = [event for event in sample_1["events"] if "confidence_score" in event]
    predicted_2 = [event for event in sample_2["events"] if "confidence_score" in event]
    assert [(event["label"], event["position_ms"]) for event in predicted_1] == [
        ("pass", 1100), ("shot", 1200), ("shot", 1300)
    ]
    assert [(event["label"], event["position_ms"]) for event in predicted_2] == [
        ("shot", 2200)
    ]
    assert all(event["inference_model_id"] == "model-one" for event in predicted_1 + predicted_2)
    assert window.localization_editor_controller._pending_prediction_sample_ids == {"clip_1", "clip_2"}
    assert len(window.dataset_explorer_controller.undo_stack) == undo_before + 1
    after = copy.deepcopy(window.dataset_explorer_controller.dataset_json)

    window.history_manager.perform_undo()
    assert window.dataset_explorer_controller.dataset_json == before
    assert window.localization_editor_controller._pending_prediction_sample_ids == set()
    window.history_manager.perform_redo()
    assert window.dataset_explorer_controller.dataset_json == after
    assert window.localization_editor_controller._pending_prediction_sample_ids == {"clip_1", "clip_2"}


@pytest.mark.gui
def test_mapping_cancel_keeps_dataset_and_history_unchanged(
    window, monkeypatch, synthetic_project_json
):
    _open_localization_project(window, monkeypatch, synthetic_project_json("localization"))
    before = copy.deepcopy(window.dataset_explorer_controller.dataset_json)
    undo_before = len(window.dataset_explorer_controller.undo_stack)
    monkeypatch.setattr(
        LocalizationClassMappingDialog,
        "exec",
        lambda _dialog: QDialog.DialogCode.Rejected,
    )

    window.localization_editor_controller.apply_shared_inference_result(
        _result(), {"head": "ball_action"}
    )

    assert window.dataset_explorer_controller.dataset_json == before
    assert len(window.dataset_explorer_controller.undo_stack) == undo_before


@pytest.mark.gui
def test_create_head_moves_all_run_predictions_and_undoes_schema_with_events(
    window, monkeypatch, synthetic_project_json
):
    _open_localization_project(
        window, monkeypatch, synthetic_project_json("localization", item_count=2)
    )
    before = copy.deepcopy(window.dataset_explorer_controller.dataset_json)
    undo_before = len(window.dataset_explorer_controller.undo_stack)

    def create_head(dialog):
        dialog.new_head_radio.setChecked(True)
        dialog.new_head_name.setText("model_actions")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LocalizationClassMappingDialog, "exec", create_head)
    _complete_shared_result(window, _result(), "local")

    assert window.dataset_explorer_controller.label_definitions["model_actions"] == {
        "type": "single_label",
        "labels": ["pass", "whistle", "ignore-me"],
    }
    for sample_id, expected_count in (("clip_1", 4), ("clip_2", 1)):
        sample = window.dataset_explorer_controller.get_sample(sample_id)
        new_events = [event for event in sample["events"] if event["head"] == "model_actions"]
        assert len(new_events) == expected_count
        assert all("confidence_score" in event for event in new_events)
    assert window.localization_panel.annot_mgmt.tabs.get_current_head() == "ball_action"
    assert len(window.dataset_explorer_controller.undo_stack) == undo_before + 1
    after = copy.deepcopy(window.dataset_explorer_controller.dataset_json)

    window.history_manager.perform_undo()
    assert window.dataset_explorer_controller.dataset_json == before
    window.history_manager.perform_redo()
    assert window.dataset_explorer_controller.dataset_json == after


@pytest.mark.gui
def test_known_classes_still_require_destination_confirmation(
    window, monkeypatch, synthetic_project_json
):
    _open_localization_project(window, monkeypatch, synthetic_project_json("localization"))
    dialogs = []

    def accept_dialog(dialog):
        dialogs.append(dialog)
        assert dialog.target_head_combo.currentData() == "ball_action"
        assert dialog._combos["shot"].currentData() == "shot"
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LocalizationClassMappingDialog, "exec", accept_dialog)
    result = InferenceResult(
        "known-result", "localization", "model-one",
        ({"sample_id": "clip_1", "events": [{"label": "shot", "position_ms": 2500}]},),
    )
    before = len(window.dataset_explorer_controller.undo_stack)

    window.localization_editor_controller.apply_shared_inference_result(
        result, {"head": "ball_action"}
    )

    assert len(dialogs) == 1
    assert len(window.dataset_explorer_controller.undo_stack) == before + 1
    sample = window.dataset_explorer_controller.get_sample("clip_1")
    assert any(
        event["label"] == "shot" and event["position_ms"] == 2500
        for event in sample["events"]
    )


@pytest.mark.gui
def test_duplicate_prediction_is_noop_without_undo_entry(
    window, monkeypatch, synthetic_project_json
):
    _open_localization_project(window, monkeypatch, synthetic_project_json("localization"))
    before = copy.deepcopy(window.dataset_explorer_controller.dataset_json)
    undo_before = len(window.dataset_explorer_controller.undo_stack)
    result = InferenceResult(
        "duplicate", "localization", "model-one",
        ({"sample_id": "clip_1", "events": [{"label": "pass", "position_ms": 1000}]},),
    )
    monkeypatch.setattr(
        LocalizationClassMappingDialog,
        "exec",
        lambda _dialog: QDialog.DialogCode.Accepted,
    )

    window.localization_editor_controller.apply_shared_inference_result(
        result, {"head": "ball_action"}
    )

    assert window.dataset_explorer_controller.dataset_json == before
    assert len(window.dataset_explorer_controller.undo_stack) == undo_before
