import json
import os
import threading

import pytest
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QAbstractItemView, QPushButton

from controllers.classification import ClassificationEditorController
from controllers.dense_description import DenseEditorController
from controllers.description import DescEditorController
from controllers.inference_controller import InferenceController
from controllers.localization import LocalizationEditorController
from controllers.question_answer import QAEditorController
from inference_settings import LOCAL_MODELS_KEY
from inference_types import (
    InferenceInput,
    InferenceItem,
    InferenceLogEvent,
    InferenceModelChoice,
    InferenceQueueEntry,
    InferenceRequest,
    InferenceResult,
    ModelDescriptor,
)
from ui.dense_description import DenseAnnotationPanel
from ui.description import DescriptionAnnotationPanel
from ui.dialogs import ApplicationSettingsDialog, HfLocalModelDialog, InferenceRunDialog
from ui.classification import ClassificationAnnotationPanel
from ui.localization import LocalizationAnnotationPanel
from ui.question_answer import QuestionAnswerAnnotationPanel
from ui.inference_review_bar import InferenceReviewBar
from ui.inference_jobs_widget import InferenceJobsWidget


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
def test_every_annotation_panel_uses_one_bottom_prediction_review_footer(qtbot, panel_type):
    panel = panel_type()
    qtbot.addWidget(panel)

    footer = panel.findChild(InferenceReviewBar, "inferenceReviewBar")
    assert footer is panel.inference_review_bar
    assert panel.layout().itemAt(panel.layout().count() - 1).widget() is footer
    run_buttons = [
        button
        for button in panel.findChildren(QPushButton)
        if button.text() == "Run Inference…"
    ]
    assert run_buttons == []
    assert not hasattr(footer, "run_button")
    assert not any("smart inference" in button.text().lower() for button in panel.findChildren(QPushButton))


@pytest.mark.gui
def test_jobs_widget_exposes_shared_run_action(qtbot):
    action = QAction("Run Inference…")
    widget = InferenceJobsWidget(action)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(action.triggered, timeout=500):
        widget.run_button.click()


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
def test_fresh_settings_registry_is_empty(qtbot):
    dialog = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(dialog)
    payload = dialog.inference_payload()
    assert payload["local_models"] == []
    dialog._append_local_model({
        "task": "classification",
        "id": "custom/model",
        "display_name": "Custom",
        "config_path": "/tmp/config.yaml",
    })
    dialog._restore_defaults()
    assert dialog.inference_payload()["local_models"] == []


@pytest.mark.gui
def test_hf_model_dialog_has_known_suggestions_and_payload(qtbot):
    dialog = HfLocalModelDialog()
    qtbot.addWidget(dialog)
    suggestions = [
        dialog.repository_combo.itemText(index)
        for index in range(dialog.repository_combo.count())
    ]
    assert suggestions == [
        "OpenSportsLab/OSL-cls-action-mvitv2",
        "OpenSportsLab/OSL-loc-snbas-2025-e2e",
        "OpenSportsLab/OSL-loc-snbas-2023-e2e",
    ]
    dialog.repository_combo.setCurrentText("owner/custom-model")
    dialog.revision_edit.setText("v2")
    dialog.token_edit.setText("hf_secret")
    assert not dialog.force_download_checkbox.isChecked()
    dialog.force_download_checkbox.setChecked(True)
    assert dialog.payload() == {
        "repo_id": "owner/custom-model",
        "revision": "v2",
        "token": "hf_secret",
        "force_download": True,
    }


@pytest.mark.gui
def test_settings_routes_hf_model_intents_as_signals(qtbot):
    dialog = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(dialog)
    requested = []
    cancelled = []
    dialog.inferenceHfModelRequested.connect(requested.append)
    dialog.inferenceHfModelCancelRequested.connect(lambda: cancelled.append(True))
    payload = {
        "repo_id": "owner/model",
        "revision": "main",
        "token": None,
        "force_download": True,
    }
    dialog.inference_setup_widget.huggingFaceModelRequested.emit(payload)
    dialog.inference_setup_widget.huggingFaceModelCancelRequested.emit()
    assert requested == [payload]
    assert cancelled == [True]


@pytest.mark.gui
def test_hf_downloaded_model_upserts_and_preserves_hidden_metadata(qtbot, tmp_path):
    dialog = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(dialog)
    dialog.set_hf_model_import_busy(True, "Downloading…")
    assert not dialog.ok_button.isEnabled()
    assert not dialog.apply_button.isEnabled()
    descriptor = {
        "task": "localization",
        "id": "OpenSportsLab/OSL-loc-snbas-2025-e2e",
        "display_name": "Downloaded 2025",
        "config_path": str(tmp_path / "config.yaml"),
        "weights": str(tmp_path / "model.pt"),
        "hf_repo_id": "OpenSportsLab/OSL-loc-snbas-2025-e2e",
        "hf_revision": "main",
        "hf_checkpoint_filename": "model.pt",
        "trusted_legacy": True,
    }
    before = dialog.local_model_table.rowCount()
    dialog.add_downloaded_hf_model(descriptor)
    assert dialog.ok_button.isEnabled()
    assert dialog.apply_button.isEnabled()
    assert dialog.restore_defaults_button.isEnabled()
    assert dialog.local_model_table.rowCount() == before + 1
    dialog.add_downloaded_hf_model({**descriptor, "display_name": "Updated 2025"})
    assert dialog.local_model_table.rowCount() == before + 1
    model = next(
        model
        for model in dialog.inference_payload()["local_models"]
        if model["id"] == descriptor["id"]
    )
    assert model["weights"] == descriptor["weights"]
    assert model["hf_revision"] == "main"
    assert model["hf_checkpoint_filename"] == "model.pt"
    assert model["trusted_legacy"] is True

    row = next(
        row
        for row in range(dialog.local_model_table.rowCount())
        if dialog.local_model_table.item(row, 1).text() == descriptor["id"]
    )
    dialog.local_model_table.item(row, 4).setText(str(tmp_path / "other.pt"))
    edited = next(
        model
        for model in dialog.inference_payload()["local_models"]
        if model["id"] == descriptor["id"]
    )
    assert edited["trusted_legacy"] is False


@pytest.mark.gui
def test_arbitrary_hf_model_never_receives_legacy_trust(qtbot, tmp_path):
    dialog = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(dialog)
    dialog.add_downloaded_hf_model({
        "task": "localization",
        "id": "someone/legacy-model",
        "display_name": "Untrusted",
        "config_path": str(tmp_path / "config.yaml"),
        "weights": str(tmp_path / "model.pt"),
        "hf_repo_id": "someone/legacy-model",
        "hf_revision": "main",
        "hf_checkpoint_filename": "model.pt",
        "trusted_legacy": True,
    })
    model = next(
        model
        for model in dialog.inference_payload()["local_models"]
        if model["id"] == "someone/legacy-model"
    )
    assert model["trusted_legacy"] is False


@pytest.mark.gui
def test_downloaded_model_is_staged_until_settings_apply(qtbot, tmp_path):
    descriptor = {
        "task": "classification",
        "id": "owner/downloaded",
        "display_name": "Downloaded",
        "config_path": str(tmp_path / "config.yaml"),
        "weights": str(tmp_path / "model.safetensors"),
        "hf_repo_id": "owner/downloaded",
        "hf_revision": "main",
        "hf_checkpoint_filename": "model.safetensors",
    }
    cancelled = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(cancelled)
    cancelled_payloads = []
    cancelled.inferenceSettingsApplyRequested.connect(cancelled_payloads.append)
    cancelled.add_downloaded_hf_model(descriptor)
    cancelled.reject()
    assert cancelled_payloads == []

    applied = ApplicationSettingsDialog("2,4", "1,5")
    qtbot.addWidget(applied)
    applied_payloads = []
    applied.inferenceSettingsApplyRequested.connect(applied_payloads.append)
    applied.add_downloaded_hf_model(descriptor)
    applied._apply(close_after=False)
    assert any(
        model["id"] == "owner/downloaded"
        for model in applied_payloads[-1]["local_models"]
    )


@pytest.mark.gui
def test_removing_any_local_model_persists_as_an_empty_registry(qtbot, tmp_path):
    settings = QSettings(
        str(tmp_path / "inference.ini"), QSettings.Format.IniFormat
    )
    model = {
        "task": "classification",
        "id": "OpenSportsLab/OSL-cls-action-mvitv2",
        "display_name": "OSL Classification",
        "config_path": str(tmp_path / "config.yaml"),
        "weights": str(tmp_path / "model.pth.tar"),
        "hf_repo_id": "OpenSportsLab/OSL-cls-action-mvitv2",
        "hf_revision": "main",
    }
    settings.setValue(LOCAL_MODELS_KEY, json.dumps([model]))

    dialog = ApplicationSettingsDialog("2,4", "1,5", settings=settings)
    qtbot.addWidget(dialog)
    assert dialog.local_model_table.rowCount() == 1
    dialog.local_model_table.selectRow(0)
    dialog.remove_local_model_button.click()
    assert dialog.inference_payload()["local_models"] == []
    dialog.inferenceSettingsApplyRequested.connect(
        lambda payload: settings.setValue(
            LOCAL_MODELS_KEY, json.dumps(payload["local_models"])
        )
    )
    dialog._apply(close_after=False)

    reopened = ApplicationSettingsDialog("2,4", "1,5", settings=settings)
    qtbot.addWidget(reopened)
    assert reopened.local_model_table.rowCount() == 0
    assert reopened.inference_payload()["local_models"] == []


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
def test_inference_jobs_widget_renders_queues_history_logs_and_actions(qtbot):
    widget = InferenceJobsWidget(QAction("Run Inference…"))
    qtbot.addWidget(widget)
    active = InferenceQueueEntry(
        request_id="request",
        backend="local",
        task="localization",
        model_id="model",
        sample_ids=("sample",),
        state="running",
        message="Running inference",
        current=2,
        total=5,
        queue_position=0,
        log_events=(
            InferenceLogEvent(1.0, "queued", "Queued"),
            InferenceLogEvent(2.0, "running", "Running inference", current=2, total=5),
        ),
    )
    queued = InferenceQueueEntry(
        request_id="queued",
        backend="local",
        task="localization",
        model_id="next-model",
        sample_ids=("sample",),
        state="queued",
        queue_position=1,
    )
    widget.set_entries((active, queued))

    assert "Local: Running 2/5, 1 queued" in widget.summary_label.text()
    assert widget.local_table.rowCount() == 2
    with qtbot.waitSignal(widget.cancelRequested, timeout=500):
        widget.local_table.cellWidget(0, 3).click()
    with qtbot.waitSignal(widget.cancelAllRequested, timeout=500):
        widget.cancel_all_button.click()
    widget.local_table.cellWidget(0, 2).click()
    assert "Running inference" in widget.details_view.toPlainText()

    failed = InferenceQueueEntry(
        request_id="failed",
        backend="remote",
        task="description",
        model_id="remote-model",
        sample_ids=("sample",),
        state="failed",
        message="Server failed",
        error_code="server_error",
        error_details={"job_id": "job-1"},
        log_events=(
            InferenceLogEvent(
                3.0, "failed", "Server failed", level="error", details={"job_id": "job-1"}
            ),
        ),
    )
    widget.set_entries((failed,))
    assert widget.history_table.rowCount() == 1
    widget.history_table.cellWidget(0, 4).click()
    assert "job-1" in widget.details_view.toPlainText()
    with qtbot.waitSignal(widget.clearHistoryRequested, timeout=500):
        widget.clear_history_button.click()

    widget.set_entries(())
    assert widget.summary_label.text() == "Local: Idle | Remote: Idle"


@pytest.mark.gui
def test_main_window_jobs_dock_preserves_status_messages_and_toggles(
    qtbot, window
):
    assert window.dockWidgetArea(window.inference_jobs_dock).name == "RightDockWidgetArea"
    assert window.inference_jobs_dock.isHidden()
    assert window.statusBar().findChildren(InferenceJobsWidget) == []

    window.statusBar().showMessage("Ordinary status information")
    window.inference_jobs_widget.set_entries(
        (
            InferenceQueueEntry(
                request_id="queued",
                backend="local",
                task="description",
                model_id="model",
                sample_ids=("sample",),
                state="queued",
                queue_position=1,
            ),
        )
    )
    assert window.statusBar().currentMessage() == "Ordinary status information"

    window.show_workspace()
    window._show_inference_jobs()
    assert window.inference_jobs_dock.isVisible()
    assert window._inference_jobs_dock_preferred_visible is True
    window.show_welcome_view()
    assert window.inference_jobs_dock.isHidden()
    assert not window.action_show_inference_jobs.isEnabled()
    assert window._inference_jobs_dock_preferred_visible is True

    window.show_workspace()
    assert window.action_show_inference_jobs.isEnabled()
    assert window.inference_jobs_dock.isVisible()
    window.action_show_inference_jobs.trigger()
    assert window.inference_jobs_dock.isHidden()
    assert window._inference_jobs_dock_preferred_visible is False


@pytest.mark.gui
@pytest.mark.parametrize(
    ("tab_index", "controller_name"),
    [
        (0, "classification_editor_controller"),
        (1, "localization_editor_controller"),
        (2, "desc_editor_controller"),
        (3, "dense_editor_controller"),
        (4, "qa_editor_controller"),
    ],
)
def test_run_action_routes_to_every_active_mode(
    window, monkeypatch, tab_index, controller_name
):
    requested = []
    controller = getattr(window, controller_name)
    monkeypatch.setattr(
        controller, "request_inference", lambda: requested.append(tab_index)
    )
    window.right_tabs.setCurrentIndex(tab_index)
    window.action_run_inference.setEnabled(True)
    window.action_run_inference.trigger()
    assert requested == [tab_index]


@pytest.mark.gui
def test_localization_run_uses_visible_active_head(qtbot):
    panel = LocalizationAnnotationPanel()
    qtbot.addWidget(panel)
    controller = LocalizationEditorController(panel)
    controller.setup_connections()
    controller.on_schema_context_changed(
        {
            "first": {"type": "single_label", "labels": ["a"]},
            "active": {"type": "single_label", "labels": ["b", "c"]},
        }
    )
    controller.current_sample_id = "sample"
    controller.current_video_path = "/tmp/sample.mp4"
    panel.annot_mgmt.tabs.set_current_head("active")
    controller.current_head = None

    with qtbot.waitSignal(controller.inferenceRunRequested, timeout=500) as signal:
        controller.request_inference()

    assert signal.args == [
        "localization",
        {"head": "active", "labels": ["b", "c"], "start_ms": 0, "end_ms": 0},
    ]


@pytest.mark.gui
def test_localization_request_captures_selected_input_timeline_offset(
    window,
    synthetic_project_json,
    monkeypatch,
):
    project_path = synthetic_project_json("localization", item_count=1)
    assert window.dataset_explorer_controller.open_project_from_path(str(project_path))
    sample = window.dataset_explorer_controller.dataset_json["data"][0]
    sample["inputs"] = [
        {
            "path": "match.mp4",
            "type": "video",
            "UTC_time_start": "2026-01-01 12:00:00.000000",
        },
        {
            "path": "tracking.h5",
            "type": "player_joints_h5",
            "UTC_time_start": "2026-01-01 12:05:00.000000",
        },
    ]
    window.dataset_explorer_controller.current_selected_sample_id = str(sample["id"])
    captured = {}

    class DraftSignal:
        def connect(self, _slot):
            pass

    class Label:
        def setText(self, _text):
            pass

    class FakeDialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, _task, inputs, _context, **_kwargs):
            captured["inputs"] = list(inputs)
            self.refreshModelsRequested = DraftSignal()
            self.availability_label = Label()

        def set_models(self, *_args):
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def payload(self):
            return {
                "backend": "local",
                "model_id": "header-spotter",
                "inputs": [captured["inputs"][1]],
                "start_ms": 0,
                "end_ms": 0,
            }

    monkeypatch.setattr("main_window.InferenceRunDialog", FakeDialog)
    monkeypatch.setattr(
        window.inference_controller,
        "request_model_catalog",
        lambda _task: True,
    )

    def enqueue(request):
        captured["request"] = request
        return InferenceQueueEntry(
            request.request_id,
            request.backend,
            request.task,
            request.model_id,
            tuple(item.sample_id for item in request.items),
            "running",
        )

    monkeypatch.setattr(window.inference_controller, "enqueue_inference", enqueue)
    window._open_inference_run_dialog(
        "localization",
        {"head": "Actions", "labels": ["header"]},
    )

    assert captured["request"].items[0].timeline_offset_ms == 300_000


@pytest.mark.gui
def test_classification_dialog_lists_selected_sample_inputs_only_and_reuses_selection_for_batch(
    window, synthetic_project_json, monkeypatch
):
    project_path = synthetic_project_json("classification", item_count=2)
    assert window.dataset_explorer_controller.open_project_from_path(str(project_path))
    samples = window.dataset_explorer_controller.dataset_json["data"]
    for index, sample in enumerate(samples):
        sample["inputs"] = [
            {"path": f"sample-{index}-main.mp4", "type": "video"},
            {"path": f"sample-{index}-aux.mp4", "type": "video"},
        ]
    current_id = str(samples[0]["id"])
    window.dataset_explorer_controller.current_selected_sample_id = current_id
    captured = {}

    class DraftSignal:
        def connect(self, _slot):
            pass

    class Label:
        def setText(self, _text):
            pass

    class FakeDialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, task, inputs, context, **_kwargs):
            captured["dialog_inputs"] = list(inputs)
            self.refreshModelsRequested = DraftSignal()
            self.availability_label = Label()

        def set_models(self, *_args):
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def payload(self):
            return {
                "backend": "local",
                "model_id": "classifier",
                "inputs": [captured["dialog_inputs"][1]],
                "scope": "all",
                "start_ms": 0,
                "end_ms": 0,
                "language": "en",
                "question": "",
            }

    monkeypatch.setattr("main_window.InferenceRunDialog", FakeDialog)
    monkeypatch.setattr(
        window.inference_controller, "request_model_catalog", lambda _task: True
    )

    def enqueue(request):
        captured["request"] = request
        return InferenceQueueEntry(
            request.request_id,
            request.backend,
            request.task,
            request.model_id,
            tuple(item.sample_id for item in request.items),
            "running",
        )

    monkeypatch.setattr(window.inference_controller, "enqueue_inference", enqueue)
    window._open_inference_run_dialog("classification", {"head": "action"})

    assert len(captured["dialog_inputs"]) == 2
    assert {source.sample_id for source in captured["dialog_inputs"]} == {current_id}
    request = captured["request"]
    assert request.dataset_root == str(project_path.parent)
    assert len(request.items) == 2
    assert [len(item.inputs) for item in request.items] == [1, 1]
    assert [os.path.basename(item.inputs[0].path) for item in request.items] == [
        "sample-0-aux.mp4",
        "sample-1-aux.mp4",
    ]


@pytest.mark.gui
def test_inference_worker_does_not_block_gui_and_suppresses_cancelled_result(
    qtbot, monkeypatch, tmp_path
):
    controller = InferenceController()
    entered = threading.Event()
    release = threading.Event()

    class BlockingProvider:
        def run(self, request, progress, _cancel_event):
            entered.set()
            progress("Running model", 0, 0)
            release.wait(2)
            return InferenceResult(
                request.request_id,
                request.task,
                request.model_id,
                ({"sample_id": "sample", "captions": [{"text": "Late"}]},),
            )

        def close(self):
            pass

    monkeypatch.setattr(controller, "_provider", lambda *_args, **_kwargs: BlockingProvider())
    request = InferenceRequest(
        task="description",
        model_id="model",
        backend="local",
        items=[InferenceItem("sample", [InferenceInput(str(tmp_path / "clip.mp4"))])],
    )
    completed = []
    controller.inferenceCompleted.connect(lambda *_args: completed.append(True))
    button = QPushButton("Still interactive")
    qtbot.addWidget(button)
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))

    assert controller.enqueue_inference(request) is not None
    qtbot.waitUntil(entered.is_set, timeout=1000)
    button.click()
    assert clicks == [True]
    with qtbot.waitSignal(controller.inferenceCancelled, timeout=2000):
        controller.cancel_request(request.request_id)
        release.set()
    assert completed == []
    assert controller.shutdown()


@pytest.mark.gui
def test_classification_result_stays_with_original_sample_after_navigation(qtbot):
    panel = ClassificationAnnotationPanel()
    qtbot.addWidget(panel)
    controller = ClassificationEditorController(panel)
    controller.setup_connections()
    controller.on_schema_context_changed({
        "action": {"type": "single_label", "labels": ["pass", "shot"]}
    })
    sample_a = {"id": "sample-a", "inputs": [{"path": "a.mp4", "type": "video"}]}
    sample_b = {"id": "sample-b", "inputs": [{"path": "b.mp4", "type": "video"}]}
    controller.on_selected_sample_changed(sample_b)
    result = InferenceResult(
        "request", "classification", "model",
        ({"sample_id": "sample-a", "labels": {"action": {"label": "shot"}}},),
    )

    controller.apply_shared_inference_result(result, {"head": "action"})

    assert ("sample-a", "action") in controller._pending_predictions
    assert ("sample-b", "action") not in controller._pending_predictions
    controller.on_selected_sample_changed(sample_a)
    _confidence, accept, reject = panel.get_head_row_smart_widgets("action", "shot")
    assert not accept.isHidden()
    assert not reject.isHidden()


@pytest.mark.gui
def test_localization_result_stays_with_original_sample_after_navigation(qtbot):
    panel = LocalizationAnnotationPanel()
    qtbot.addWidget(panel)
    controller = LocalizationEditorController(panel)
    controller.setup_connections()
    controller.on_schema_context_changed({
        "ball_action": {"type": "single_label", "labels": ["pass"]}
    })
    samples = {
        "sample-a": {"id": "sample-a", "inputs": [{"path": "a.mp4", "type": "video"}], "events": []},
        "sample-b": {"id": "sample-b", "inputs": [{"path": "b.mp4", "type": "video"}], "events": []},
    }
    # Predictions are persisted via locEventsSetRequested now (not staged in
    # a session-only dict); stand in for what main_window.py's history
    # manager wiring would do with it.
    controller.locEventsSetRequested.connect(
        lambda sample_id, events: samples[sample_id].__setitem__("events", list(events))
    )
    controller.on_selected_sample_changed(samples["sample-b"])
    result = InferenceResult(
        "request", "localization", "model",
        ({"sample_id": "sample-a", "events": [{"label": "pass", "position_ms": 100}]},),
    )

    controller.apply_shared_inference_result(
        result,
        {
            "head": "ball_action",
            "existing_events_by_sample": {"sample-a": samples["sample-a"]["events"]},
        },
    )

    assert panel.table.model.rowCount() == 0
    assert len(samples["sample-a"]["events"]) == 1
    assert "confidence_score" in samples["sample-a"]["events"][0]
    controller.on_selected_sample_changed(samples["sample-a"])
    assert panel.table.model.rowCount() == 1


@pytest.mark.gui
def test_description_result_stays_with_original_sample_after_navigation(qtbot):
    panel = DescriptionAnnotationPanel()
    qtbot.addWidget(panel)
    controller = DescEditorController(panel)
    controller.setup_connections()
    sample_a = {"id": "sample-a", "inputs": [{"path": "a.mp4"}], "captions": []}
    sample_b = {"id": "sample-b", "inputs": [{"path": "b.mp4"}], "captions": []}
    controller.on_selected_sample_changed(sample_b)
    result = InferenceResult(
        "request", "description", "model",
        ({"sample_id": "sample-a", "captions": [{"text": "Original sample"}]},),
    )

    controller.apply_shared_inference_result(result)

    assert panel.inference_candidate_label.text() == ""
    controller.on_selected_sample_changed(sample_a)
    assert panel.inference_candidate_label.text() == "Candidate: Original sample"


@pytest.mark.gui
def test_dense_result_stays_with_original_sample_after_navigation(qtbot):
    panel = DenseAnnotationPanel()
    qtbot.addWidget(panel)
    controller = DenseEditorController(panel)
    controller.setup_connections()
    sample_a = {"id": "sample-a", "inputs": [{"path": "a.mp4"}], "dense_captions": []}
    sample_b = {"id": "sample-b", "inputs": [{"path": "b.mp4"}], "dense_captions": []}
    controller.on_selected_sample_changed(sample_b, "b.mp4")
    result = InferenceResult(
        "request", "dense_description", "model",
        ({"sample_id": "sample-a", "dense_captions": [{"text": "Original", "position_ms": 100}]},),
    )

    controller.apply_shared_inference_result(result)

    assert panel.dense_model.rowCount() == 0
    controller.on_selected_sample_changed(sample_a, "a.mp4")
    assert panel.dense_model.rowCount() == 1


@pytest.mark.gui
def test_qa_result_stays_with_original_sample_after_navigation(qtbot):
    panel = QuestionAnswerAnnotationPanel()
    qtbot.addWidget(panel)
    controller = QAEditorController(panel)
    controller.setup_connections()
    sample_a = {"id": "sample-a", "inputs": [{"path": "a.mp4"}], "answers": []}
    sample_b = {"id": "sample-b", "inputs": [{"path": "b.mp4"}], "answers": []}
    controller.on_selected_sample_changed(sample_b)
    result = InferenceResult(
        "request", "question_answer", "model",
        ({"sample_id": "sample-a", "answer": {"text": "Original answer"}},),
    )

    controller.apply_shared_inference_result(result, {"question": "What happened?"})

    assert controller._answer_groups == []
    controller.on_selected_sample_changed(sample_a)
    assert controller._answer_groups[0]["answers"][0]["text"] == "Original answer"


@pytest.mark.gui
def test_main_window_filters_deleted_samples_from_completed_queue_job(
    window, synthetic_project_json
):
    project_path = synthetic_project_json("description", item_count=2)
    assert window.dataset_explorer_controller.open_project_from_path(str(project_path))
    samples = window.dataset_explorer_controller.dataset_json["data"]
    sample_a, sample_b = str(samples[0]["id"]), str(samples[1]["id"])
    window.desc_editor_controller.on_selected_sample_changed(samples[1])
    request_id = "background-request"
    window._pending_inference_requests[request_id] = {
        "task": "description",
        "sample_ids": (sample_a, sample_b),
        "request_items": {"item-a": sample_a, "item-b": sample_b},
        "project_generation": window.dataset_explorer_controller.project_generation,
        "context": {"language": "en"},
        "backend": "local",
        "model_id": "model",
        "invalidated": False,
    }
    assert window.data_dock.isEnabled()
    assert window.editor_dock.isEnabled()
    assert window.action_run_inference.text() == "Run Inference…"
    assert not any(
        panel.findChildren(QPushButton, "runInferenceButton")
        for panel in (
            window.classification_panel,
            window.localization_panel,
            window.description_panel,
            window.dense_panel,
            window.qa_panel,
        )
    )

    window.dataset_explorer_controller.dataset_json["data"] = [samples[1]]
    window.dataset_explorer_controller._rebuild_runtime_index()
    result = InferenceResult(
        request_id,
        "description",
        "model",
        (
                {"item_id": "item-a", "sample_id": sample_a, "captions": [{"text": "Removed"}]},
                {"item_id": "item-b", "sample_id": sample_b, "captions": [{"text": "Surviving"}]},
        ),
    )
    window._on_shared_inference_completed(request_id, result)

    assert sample_a not in window.desc_editor_controller._pending_predictions
    assert window.desc_editor_controller._pending_predictions[sample_b]["text"] == "Surviving"


@pytest.mark.gui
def test_completed_inference_does_not_change_current_annotation_tab(
    window, synthetic_project_json, monkeypatch
):
    project_path = synthetic_project_json("description", item_count=1)
    assert window.dataset_explorer_controller.open_project_from_path(str(project_path))
    sample = window.dataset_explorer_controller.dataset_json["data"][0]
    sample_id = str(sample["id"])
    request_id = "tab-stability"
    window._pending_inference_requests[request_id] = {
        "task": "description",
        "sample_ids": (sample_id,),
        "request_items": {"item": sample_id},
        "project_generation": window.dataset_explorer_controller.project_generation,
        "context": {"language": "en"},
        "backend": "local",
        "model_id": "model",
        "invalidated": False,
    }
    window.right_tabs.setCurrentIndex(4)

    def apply_result(_result, _context):
        window.right_tabs.setCurrentIndex(2)

    monkeypatch.setattr(
        window.desc_editor_controller, "apply_shared_inference_result", apply_result
    )
    window._on_shared_inference_completed(
        request_id,
        InferenceResult(
            request_id,
            "description",
            "model",
            (
                {
                    "item_id": "item",
                    "sample_id": sample_id,
                    "captions": [{"text": "Prediction"}],
                },
            ),
        ),
    )

    assert window.right_tabs.currentIndex() == 4


@pytest.mark.gui
def test_project_generation_change_invalidates_late_inference_result(
    window, synthetic_project_json, monkeypatch
):
    project_path = synthetic_project_json("description")
    assert window.dataset_explorer_controller.open_project_from_path(str(project_path))
    sample_id = str(window.dataset_explorer_controller.dataset_json["data"][0]["id"])
    request_id = "old-project-request"
    window._pending_inference_requests[request_id] = {
        "task": "description",
        "sample_ids": (sample_id,),
        "request_items": {"item": sample_id},
        "project_generation": window.dataset_explorer_controller.project_generation,
        "context": {"language": "en"},
        "backend": "local",
        "model_id": "model",
        "invalidated": False,
    }
    monkeypatch.setattr(window.inference_controller, "cancel_all", lambda: 1)

    window.dataset_explorer_controller.reset(full_reset=True)

    assert window._pending_inference_requests[request_id]["invalidated"] is True
    late_result = InferenceResult(
        request_id,
        "description",
        "model",
        ({"item_id": "item", "sample_id": sample_id, "captions": [{"text": "Late"}]},),
    )
    window._on_shared_inference_completed(request_id, late_result)
    assert window.desc_editor_controller._pending_predictions == {}


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
        ({"sample_id": "sample", "captions": [{"lang": "en", "text": "Predicted", "confidence_score": 0.8}]},),
    )
    controller.apply_shared_inference_result(result)
    assert mutations == []
    assert panel.inference_candidate_label.text() == "Candidate: Predicted"
    controller.confirm_smart_inference()
    assert len(mutations) == 1
    assert mutations[-1][1] == [
        {"lang": "en", "text": "Manual"},
        {"lang": "en", "text": "Predicted"},
    ]

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
        ({"sample_id": "sample", "dense_captions": [
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
        ({"sample_id": "sample", "answer": {"text": "A shot.", "confidence_score": 0.75}},),
    )
    controller.apply_shared_inference_result(result, {"question": "What happened?"})
    assert mutations == []
    smart = controller._answer_groups[0]["answers"][-1]
    assert smart["text"] == "A shot."
    assert smart["_pending_prediction"] is True
    controller.confirm_selected_smart_answer()
    assert mutations[-1][1][0]["answers"][-1] == "A shot."
