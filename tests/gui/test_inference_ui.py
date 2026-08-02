import pytest

from controllers.dense_description import DenseEditorController
from controllers.description import DescEditorController
from controllers.question_answer import QAEditorController
from inference_types import InferenceInput, InferenceResult, ModelDescriptor
from ui.dense_description import DenseAnnotationPanel
from ui.description import DescriptionAnnotationPanel
from ui.dialogs import ApplicationSettingsDialog, InferenceRunDialog
from ui.question_answer import QuestionAnswerAnnotationPanel


@pytest.mark.gui
def test_inference_run_dialog_filters_unavailable_model_and_validates_question(qtbot):
    dialog = InferenceRunDialog(
        "question_answer",
        [InferenceInput("/tmp/video.mp4")],
        {"question": "What happened?"},
    )
    qtbot.addWidget(dialog)
    dialog.set_models([
        ModelDescriptor("vqa", "VQA", "question_answer", available=True),
    ])
    assert dialog.payload()["model_id"] == "vqa"
    assert dialog.payload()["question"] == "What happened?"
    assert dialog.run_buttons.button(dialog.run_buttons.StandardButton.Ok).isEnabled()


@pytest.mark.gui
def test_inference_settings_payload_round_trip(qtbot, tmp_path):
    dialog = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(dialog)
    dialog.inference_backend_combo.setCurrentIndex(1)
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
    assert payload["backend"] == "remote"
    assert payload["server_url"] == "http://127.0.0.1:9000"
    assert payload["shared_mappings"][0]["root_id"] == "datasets"
    assert payload["local_models"][0]["task"] == "question_answer"


@pytest.mark.gui
def test_run_dialog_uses_draft_configuration_without_remembering(qtbot, tmp_path):
    dialog = InferenceRunDialog(
        "classification",
        [InferenceInput(str(tmp_path / "video.mp4"))],
        provider_config={
            "server_url": "http://server-a:5000",
            "shared_mappings": [{"local_root": str(tmp_path), "root_id": "draft"}],
            "local_models": [],
        },
    )
    qtbot.addWidget(dialog)
    dialog.configuration_widget.server_url_edit.setText("http://server-b:5000")
    payload = dialog.payload()
    assert payload["provider_config"]["server_url"] == "http://server-b:5000"
    assert payload["provider_config"]["shared_mappings"][0]["root_id"] == "draft"
    assert payload["remember_defaults"] is False


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
