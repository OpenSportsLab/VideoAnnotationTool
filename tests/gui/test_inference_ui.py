import pytest
from PyQt6.QtWidgets import QAbstractItemView, QPushButton

from controllers.dense_description import DenseEditorController
from controllers.description import DescEditorController
from controllers.question_answer import QAEditorController
from inference_types import (
    InferenceInput,
    InferenceModelChoice,
    InferenceResult,
    ModelDescriptor,
)
from ui.dense_description import DenseAnnotationPanel
from ui.description import DescriptionAnnotationPanel
from ui.dialogs import ApplicationSettingsDialog, InferenceRunDialog
from ui.classification import ClassificationAnnotationPanel
from ui.localization import LocalizationAnnotationPanel
from ui.question_answer import QuestionAnswerAnnotationPanel
from ui.inference_review_bar import InferenceReviewBar


@pytest.mark.gui
@pytest.mark.parametrize(
    "panel_type",
    [
        ClassificationAnnotationPanel,
        LocalizationAnnotationPanel,
        DescriptionAnnotationPanel,
        DenseAnnotationPanel,
        QuestionAnswerAnnotationPanel,
    ],
)
def test_every_annotation_panel_uses_one_bottom_inference_footer(qtbot, panel_type):
    panel = panel_type()
    qtbot.addWidget(panel)

    footer = panel.findChild(InferenceReviewBar, "inferenceReviewBar")
    assert footer is panel.inference_review_bar
    assert panel.layout().itemAt(panel.layout().count() - 1).widget() is footer
    assert footer.run_button.text() == "Run Inference…"
    assert footer.run_button.objectName() == "runInferenceButton"

    run_buttons = [
        button
        for button in panel.findChildren(QPushButton)
        if button.text() == "Run Inference…"
    ]
    assert run_buttons == [footer.run_button]
    assert not any("smart inference" in button.text().lower() for button in panel.findChildren(QPushButton))


@pytest.mark.gui
@pytest.mark.parametrize(
    ("panel_type", "signal_name"),
    [
        (ClassificationAnnotationPanel, "sharedInferenceRequested"),
        (LocalizationAnnotationPanel, "sharedInferenceRequested"),
        (DescriptionAnnotationPanel, "inferenceRequested"),
        (DenseAnnotationPanel, "inferenceRequested"),
        (QuestionAnswerAnnotationPanel, "inferenceRequested"),
    ],
)
def test_every_bottom_footer_dispatches_the_shared_inference_intent(
    qtbot, panel_type, signal_name
):
    panel = panel_type()
    qtbot.addWidget(panel)
    with qtbot.waitSignal(getattr(panel, signal_name), timeout=500):
        panel.inference_review_bar.run_button.click()


@pytest.mark.gui
def test_inference_run_dialog_filters_unavailable_model_and_validates_question(qtbot):
    dialog = InferenceRunDialog(
        "question_answer",
        [InferenceInput("/tmp/video.mp4")],
        {"question": "What happened?"},
    )
    qtbot.addWidget(dialog)
    dialog.set_models([
        InferenceModelChoice(
            "local",
            ModelDescriptor("vqa", "VQA", "question_answer", available=True),
        ),
    ])
    assert dialog.payload()["backend"] == "local"
    assert dialog.payload()["model_id"] == "vqa"
    assert dialog.payload()["question"] == "What happened?"
    assert dialog.run_buttons.button(dialog.run_buttons.StandardButton.Ok).isEnabled()


@pytest.mark.gui
def test_inference_settings_payload_round_trip(qtbot, tmp_path):
    dialog = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(dialog)
    dialog.inference_remote_enabled_checkbox.setChecked(True)
    dialog.inference_server_url_edit.setText("http://127.0.0.1:9000/")
    dialog._append_mapping(str(tmp_path), "datasets")
    dialog._append_local_model({
        "task": "question_answer",
        "id": "vqa",
        "display_name": "VQA",
        "config_path": "/tmp/vqa.yaml",
        "weights": "weights",
    })
    payload = dialog.inference_payload()
    assert payload["remote_enabled"] is True
    assert payload["server_url"] == "http://127.0.0.1:9000"
    assert payload["shared_mappings"][0]["root_id"] == "datasets"
    assert any(model["task"] == "question_answer" for model in payload["local_models"])


@pytest.mark.gui
def test_remote_setup_controls_are_settings_only_and_follow_enablement(qtbot):
    dialog = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(dialog)

    assert not dialog.inference_remote_enabled_checkbox.isChecked()
    assert not dialog.inference_server_url_edit.isEnabled()
    assert not dialog.inference_test_button.isEnabled()
    assert not dialog.inference_refresh_models_button.isEnabled()
    assert (
        dialog.remote_model_table.editTriggers()
        == QAbstractItemView.EditTrigger.NoEditTriggers
    )

    dialog.inference_remote_enabled_checkbox.setChecked(True)
    assert dialog.inference_server_url_edit.isEnabled()
    assert dialog.inference_test_button.isEnabled()
    assert dialog.inference_refresh_models_button.isEnabled()


@pytest.mark.gui
def test_fresh_settings_show_known_working_local_model_defaults(qtbot):
    dialog = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(dialog)
    payload = dialog.inference_payload()
    assert [(model["task"], model["id"]) for model in payload["local_models"]] == [
        ("classification", "jeetv/snpro-classification-mvit"),
        ("localization", "jeetv/snpro-snbas-2024"),
    ]


@pytest.mark.gui
def test_run_dialog_contains_execution_controls_only(qtbot, tmp_path):
    dialog = InferenceRunDialog(
        "classification",
        [InferenceInput(str(tmp_path / "video.mp4"))],
    )
    qtbot.addWidget(dialog)
    dialog.set_models([
        InferenceModelChoice(
            "remote",
            ModelDescriptor("classifier", "Classifier", "classification"),
        )
    ])
    payload = dialog.payload()
    assert payload["backend"] == "remote"
    assert payload["model_id"] == "classifier"
    assert "provider_config" not in payload
    assert "remember_defaults" not in payload
    assert "head" not in payload
    assert not hasattr(dialog, "configuration_widget")
    assert not hasattr(dialog, "backend_combo")


@pytest.mark.gui
def test_run_dialog_distinguishes_duplicate_ids_and_restores_provider_choice(qtbot):
    descriptor = ModelDescriptor("shared-id", "Shared model", "description")
    dialog = InferenceRunDialog(
        "description",
        [InferenceInput("/tmp/video.mp4")],
        preferred_model=("remote", "shared-id"),
    )
    qtbot.addWidget(dialog)
    dialog.set_models([
        InferenceModelChoice("local", descriptor),
        InferenceModelChoice("remote", descriptor),
    ])

    assert dialog.model_combo.itemText(0) == "Local — Shared model"
    assert dialog.model_combo.itemText(1) == "Remote — Shared model"
    assert dialog.payload()["backend"] == "remote"


@pytest.mark.gui
def test_run_dialog_range_controls_follow_model_capability(qtbot):
    dialog = InferenceRunDialog(
        "localization",
        [InferenceInput("/tmp/video.mp4")],
    )
    qtbot.addWidget(dialog)
    dialog.set_models([
        InferenceModelChoice(
            "local",
            ModelDescriptor("full", "Full clip", "localization"),
        )
    ])
    assert not dialog.runtime_form.isRowVisible(dialog.start_spin)
    assert not dialog.runtime_form.isRowVisible(dialog.end_spin)

    dialog.set_models([
        InferenceModelChoice(
            "remote",
            ModelDescriptor(
                "range", "Range model", "localization", supports_time_range=True
            ),
        )
    ])
    assert dialog.runtime_form.isRowVisible(dialog.start_spin)
    assert dialog.runtime_form.isRowVisible(dialog.end_spin)


@pytest.mark.gui
def test_description_smart_result_apply_confirm_and_reject_are_single_mutations(qtbot):
    panel = DescriptionAnnotationPanel()
    qtbot.addWidget(panel)
    controller = DescEditorController(panel)
    controller.setup_connections()
    controller.on_selected_sample_changed({
        "id": "sample",
        "inputs": [{"path": "clip.mp4", "type": "video"}],
        "captions": [{"lang": "en", "text": "Manual"}],
    })
    mutations = []
    controller.captionsUpdateRequested.connect(lambda sample_id, value: mutations.append((sample_id, value)))
    result = InferenceResult(
        "request", "description", "caption-model",
        ({"captions": [{"lang": "en", "text": "Predicted", "confidence_score": 0.8}]},),
    )
    controller.apply_shared_inference_result(result)
    assert mutations == []
    assert panel.inference_candidate_label.text() == "Candidate: Predicted"
    controller.confirm_smart_inference()
    assert len(mutations) == 1
    assert mutations[-1][1] == [{"lang": "en", "text": "Predicted"}]

    controller.on_selected_sample_changed({
        "id": "sample", "inputs": [{"path": "clip.mp4"}],
        "captions": [{"lang": "en", "text": "Manual"}],
    })
    controller.apply_shared_inference_result(result)
    controller.reject_smart_inference()
    assert len(mutations) == 1


@pytest.mark.gui
def test_dense_smart_result_batches_predictions_and_selected_confirm(qtbot):
    panel = DenseAnnotationPanel()
    qtbot.addWidget(panel)
    controller = DenseEditorController(panel)
    controller.setup_connections()
    controller.on_selected_sample_changed(
        {"id": "sample", "inputs": [{"path": "clip.mp4"}], "dense_captions": []},
        "clip.mp4",
    )
    mutations = []
    controller.denseEventsSetRequested.connect(lambda sample_id, value: mutations.append((sample_id, value)))
    result = InferenceResult(
        "request", "dense_description", "dense-model",
        ({"dense_captions": [
            {"position_ms": 100, "lang": "en", "text": "First", "confidence_score": 0.9},
            {"position_ms": 200, "lang": "en", "text": "Second", "confidence_score": 0.7},
        ]},),
    )
    controller.apply_shared_inference_result(result)
    assert mutations == []
    assert panel.dense_model.rowCount() == 2
    pending = panel.dense_model.get_annotation_at(0)
    panel.select_event(pending)
    controller.confirm_selected_smart_prediction()
    assert len(mutations) == 1
    assert mutations[-1][1] == [{"position_ms": 100, "lang": "en", "text": "First"}]


@pytest.mark.gui
def test_qa_smart_answer_object_round_trip_and_confirm(qtbot):
    panel = QuestionAnswerAnnotationPanel()
    qtbot.addWidget(panel)
    controller = QAEditorController(panel)
    controller.setup_connections()
    controller.on_selected_sample_changed({
        "id": "sample",
        "inputs": [{"path": "clip.mp4"}],
        "answers": [{"question": "What happened?", "answers": ["A pass."]}],
    })
    mutations = []
    controller.qaAnswersUpdateRequested.connect(lambda sample_id, value: mutations.append((sample_id, value)))
    result = InferenceResult(
        "request", "question_answer", "vqa-model",
        ({"answer": {"text": "A shot.", "confidence_score": 0.75}},),
    )
    controller.apply_shared_inference_result(result)
    assert mutations == []
    smart = controller._answer_groups[0]["answers"][-1]
    assert smart["text"] == "A shot."
    assert smart["_pending_prediction"] is True
    controller.confirm_selected_smart_answer()
    assert mutations[-1][1][0]["answers"][-1] == "A shot."
