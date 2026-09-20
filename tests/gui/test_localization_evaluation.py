"""Read-only localization evaluation and its Qt selection/report dialogs."""

import copy
from types import SimpleNamespace

import pytest

from controllers.localization import LocalizationEditorController
from localization_evaluation import (
    LocalizationEvaluationWorker, evaluate_localization_heads,
)
from ui.localization import LocalizationAnnotationPanel
from ui.localization.evaluation_dialog import (
    LocalizationEvaluationDialog, LocalizationEvaluationResultsDialog,
)


def _evaluate(samples, **overrides):
    options = {
        "scope": "project",
        "selected_sample_id": "one",
        "truth_head": "truth",
        "prediction_head": "prediction",
        "mapping": {"PASS": "pass"},
        "tolerances_ms": (1000, 2000, 3000),
        "truth_labels": ("pass", "shot"),
    }
    options.update(overrides)
    return evaluate_localization_heads(samples, **options)


def test_localization_evaluation_reports_tight_loose_and_multiple_ap_values():
    samples = [{
        "id": "one",
        "events": [
            {"head": "truth", "label": "pass", "position_ms": 1000},
            {"head": "prediction", "label": "PASS", "position_ms": 3000,
             "confidence_score": 0.9},
        ],
    }]
    original = copy.deepcopy(samples)
    report = _evaluate(samples)

    assert report["tolerances_ms"] == (1000, 2000, 3000)
    assert report["overall"]["ap"] == {1000: 0.0, 2000: 1.0, 3000: 1.0}
    assert report["overall"]["tight"] == pytest.approx(0.875)
    assert report["overall"]["loose"] == 1.0
    assert report["classes"]["pass"] == report["overall"]
    assert report["classes"]["shot"] is None
    assert (report["sample_count"], report["truth_count"], report["prediction_count"]) == (1, 1, 1)
    assert samples == original


def test_localization_evaluation_scope_status_intervals_and_unscored_predictions():
    samples = [
        {"id": "one", "metadata": {"intervals": [
            {"start_time_ms": 0, "end_time_ms": 1000},
            {"start_time_ms": 1000, "end_time_ms": 2000},
        ]}, "events": [
            {"head": "truth", "label": "pass", "position_ms": 950,
             "confidence_score": 0.2},
            {"head": "prediction", "label": "PASS", "position_ms": 1050},
        ]},
        {"id": "two", "metadata": {"annotation_status": "unlabeled"}, "events": [
            {"head": "truth", "label": "pass", "position_ms": 1000},
            {"head": "prediction", "label": "PASS", "position_ms": 1000},
        ]},
    ]
    report = _evaluate(samples, tolerances_ms=(200, 1000, 200))
    assert report["tolerances_ms"] == (200, 1000)
    assert report["overall"]["ap"][200] == 0.0
    assert report["overall"]["ap"][1000] == 0.0
    assert report["segment_count"] == 2
    assert report["sample_count"] == 1
    assert report["skipped_samples"] == 1
    assert report["truth_count"] == report["prediction_count"] == 1
    with pytest.raises(ValueError, match="No verified"):
        _evaluate(samples, scope="selected", selected_sample_id="two")


def test_localization_evaluation_maps_all_classes_and_handles_empty_results():
    samples = [{"id": "one", "events": [
        {"head": "truth", "label": "pass", "position_ms": 1000},
        {"head": "truth", "label": "pass", "position_ms": 2000},
        {"head": "prediction", "label": "PASS", "position_ms": 1000},
        {"head": "prediction", "label": "THROUGH_PASS", "position_ms": 2000,
         "confidence_score": "invalid"},
    ]}]
    report = _evaluate(samples, mapping={"PASS": "pass", "THROUGH_PASS": "pass"})
    assert report["overall"]["ap"][1000] == 1.0
    with pytest.raises(ValueError, match="Map every"):
        _evaluate(samples)

    no_predictions = [{"id": "one", "events": [
        {"head": "truth", "label": "pass", "position_ms": 1000}
    ]}]
    report = _evaluate(no_predictions, mapping={})
    assert report["overall"]["tight"] == 0.0
    assert report["prediction_count"] == 0
    with pytest.raises(ValueError, match="No ground-truth events"):
        _evaluate([{"id": "one", "events": [
            {"head": "prediction", "label": "PASS", "position_ms": 1000}
        ]}])


@pytest.mark.parametrize("confidence", [None, "invalid", float("nan")])
def test_localization_evaluation_unscored_prediction_ranks_at_full_confidence(confidence):
    correct = {"head": "prediction", "label": "PASS", "position_ms": 1000}
    if confidence is not None:
        correct["confidence_score"] = confidence
    samples = [{"id": "one", "events": [
        {"head": "truth", "label": "pass", "position_ms": 1000},
        {"head": "prediction", "label": "PASS", "position_ms": 10000,
         "confidence_score": 0.9},
        correct,
    ]}]
    report = _evaluate(samples, tolerances_ms=(0,))
    assert report["overall"]["ap"][0] == 1.0


def test_localization_evaluation_scope_and_tolerance_boundaries():
    samples = [
        {"id": "one", "events": [
            {"head": "truth", "label": "pass", "position_ms": 1000},
            {"head": "prediction", "label": "PASS", "position_ms": 1000},
        ]},
        {"id": "two", "events": [
            {"head": "truth", "label": "pass", "position_ms": 1000},
        ]},
        {"id": "three", "annotation_status": "excluded", "events": [
            {"head": "truth", "label": "pass", "position_ms": 1000},
        ]},
    ]
    selected = _evaluate(
        samples, scope="selected", tolerances_ms=(0, 60000)
    )
    project = _evaluate(samples, tolerances_ms=(0, 60000))
    assert selected["overall"]["ap"] == {0: 1.0, 60000: 1.0}
    assert project["overall"]["ap"] == {0: 0.5, 60000: 0.5}
    assert project["sample_count"] == 2
    assert project["skipped_samples"] == 1
    with pytest.raises(ValueError, match="0.0 and 60.0"):
        _evaluate(samples, tolerances_ms=(60100,))


def test_localization_evaluation_rejects_unscorable_selected_head_events():
    base = {"id": "one", "events": [
        {"head": "truth", "label": "pass", "position_ms": 1000},
    ]}
    blank_label = copy.deepcopy(base)
    blank_label["events"].append({
        "head": "prediction", "label": "", "position_ms": 1000,
    })
    with pytest.raises(ValueError, match="no label"):
        _evaluate([blank_label], mapping={})

    outside_interval = copy.deepcopy(base)
    outside_interval["metadata"] = {"intervals": [
        {"start_time_ms": 0, "end_time_ms": 1000},
    ]}
    with pytest.raises(ValueError, match="outside its declared intervals"):
        _evaluate([outside_interval], mapping={})


def test_localization_evaluation_stops_when_cancelled():
    samples = [{"id": "one", "events": [
        {"head": "truth", "label": "pass", "position_ms": 1000},
    ]}]
    with pytest.raises(InterruptedError, match="cancelled"):
        _evaluate(samples, mapping={}, should_cancel=lambda: True)


@pytest.mark.gui
def test_localization_evaluation_worker_emits_report(qtbot):
    samples = [{"id": "one", "events": [
        {"head": "truth", "label": "pass", "position_ms": 1000},
        {"head": "prediction", "label": "PASS", "position_ms": 1000},
    ]}]
    options = {
        "scope": "project", "selected_sample_id": "one",
        "truth_head": "truth", "prediction_head": "prediction",
        "mapping": {"PASS": "pass"}, "tolerances_ms": (1000, 2000),
        "truth_labels": ("pass",),
    }
    worker = LocalizationEvaluationWorker(copy.deepcopy(samples), options)
    with qtbot.waitSignal(worker.completed, timeout=10000) as signal:
        worker.start()
    assert worker.wait(10000)
    assert signal.args[0]["overall"]["ap"] == {1000: 1.0, 2000: 1.0}


@pytest.mark.gui
def test_localization_evaluation_dialog_maps_classes_and_edits_tolerances(qtbot):
    samples = [{"id": "one", "events": [
        {"head": "truth", "label": "pass", "position_ms": 1000},
        {"head": "prediction", "label": "PASS", "position_ms": 1000},
    ]}]
    dialog = LocalizationEvaluationDialog(
        samples,
        {"truth": {"labels": ["pass"]}, "prediction": {"labels": ["PASS"]}},
        "one", "prediction",
    )
    qtbot.addWidget(dialog)
    assert dialog.scope_combo.currentData() == "project"
    assert dialog.truth_combo.currentData() == "truth"
    assert dialog.prediction_combo.currentData() == "prediction"
    assert dialog.tolerances_ms() == (1000, 2000, 3000, 4000, 5000)
    assert dialog.mapping() == {"PASS": None}
    run_button = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    assert not run_button.isEnabled()

    mapping_combo = dialog.mapping_table.cellWidget(0, 1)
    mapping_combo.setCurrentIndex(mapping_combo.findData("pass"))
    assert run_button.isEnabled()
    dialog.tolerance_spin.setValue(2.2)
    dialog.add_tolerance_button.click()
    dialog.add_tolerance_button.click()
    assert dialog.tolerances_ms() == (1000, 2000, 2200, 3000, 4000, 5000)
    assert dialog.options()["mapping"] == {"PASS": "pass"}

    dialog.truth_combo.setCurrentIndex(dialog.truth_combo.findData("prediction"))
    assert not run_button.isEnabled()
    dialog.truth_combo.setCurrentIndex(dialog.truth_combo.findData("truth"))
    for index in reversed(range(dialog.tolerance_list.count())):
        dialog.tolerance_list.item(index).setSelected(True)
    dialog.remove_tolerance_button.click()
    assert dialog.tolerances_ms() == ()
    assert not run_button.isEnabled()


@pytest.mark.gui
def test_localization_evaluation_dialog_preselects_identical_labels_and_refreshes_scope(qtbot):
    samples = [
        {"id": "one", "events": [
            {"head": "truth", "label": "pass", "position_ms": 1000},
            {"head": "prediction", "label": "pass", "position_ms": 1000},
        ]},
        {"id": "two", "events": [
            {"head": "truth", "label": "shot", "position_ms": 1000},
            {"head": "prediction", "label": "SHOT", "position_ms": 1000},
        ]},
    ]
    dialog = LocalizationEvaluationDialog(
        samples, {"truth": {"labels": ["pass", "shot"]},
                  "prediction": {"labels": ["pass", "SHOT"]}},
        "one", "prediction",
    )
    qtbot.addWidget(dialog)
    assert dialog.mapping() == {"SHOT": None, "pass": "pass"}
    assert not dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()
    dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("selected"))
    assert dialog.mapping() == {"pass": "pass"}
    assert dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled()


@pytest.mark.gui
def test_localization_evaluation_result_columns_and_panel_intent(qtbot):
    sample = {"id": "one", "events": [
        {"head": "truth", "label": "pass", "position_ms": 1000},
        {"head": "prediction", "label": "PASS", "position_ms": 1000},
    ]}
    report = _evaluate([sample], tolerances_ms=(1000, 2200, 3000))
    dialog = LocalizationEvaluationResultsDialog(report)
    qtbot.addWidget(dialog)
    from PyQt6.QtWidgets import QTableWidget
    table = dialog.findChild(QTableWidget)
    assert [table.horizontalHeaderItem(column).text() for column in range(table.columnCount())] == [
        "Class", "Tight mAP", "Loose mAP", "AP@1 s", "AP@2.2 s", "AP@3 s",
    ]
    assert table.item(0, 3).text() == "100.00%"
    assert table.item(2, 3).text() == "N/A"

    panel = LocalizationAnnotationPanel()
    qtbot.addWidget(panel)
    controller = LocalizationEditorController(panel)
    controller.setup_connections()
    requested = []
    controller.evaluationRequested.connect(lambda: requested.append(True))
    panel.btn_evaluate.click()
    assert requested == [True]


@pytest.mark.gui
def test_stale_localization_evaluation_result_is_discarded(qtbot, monkeypatch):
    from main_window import VideoAnnotationWindow

    class Progress:
        closed = False

        def close(self):
            self.closed = True

    class Button:
        enabled = False

        def setEnabled(self, value):
            self.enabled = value

    worker = object()
    progress = Progress()
    button = Button()
    owner = SimpleNamespace(
        _active_localization_evaluation={
            "worker": worker, "progress": progress, "generation": 1, "discard": False,
        },
        dataset_explorer_controller=SimpleNamespace(project_generation=2),
        localization_panel=SimpleNamespace(btn_evaluate=button),
    )
    monkeypatch.setattr(
        "main_window.LocalizationEvaluationResultsDialog",
        lambda *_args: (_ for _ in ()).throw(AssertionError("stale report displayed")),
    )
    VideoAnnotationWindow._finish_localization_evaluation(owner, worker, report={})
    assert owner._active_localization_evaluation is None
    assert progress.closed
    assert button.enabled


@pytest.mark.gui
def test_edited_project_discards_localization_evaluation_result(qtbot, monkeypatch):
    from main_window import VideoAnnotationWindow

    class Progress:
        closed = False

        def close(self):
            self.closed = True

    class Button:
        enabled = False

        def setEnabled(self, value):
            self.enabled = value

    worker = object()
    progress = Progress()
    button = Button()
    owner = SimpleNamespace(
        _active_localization_evaluation={
            "worker": worker, "progress": progress, "generation": 1,
            "project_snapshot": {"data": [{"id": "one", "events": []}]},
            "discard": False,
        },
        dataset_explorer_controller=SimpleNamespace(
            project_generation=1,
            dataset_json={"data": [{"id": "one", "events": [{"label": "pass"}]}]},
        ),
        localization_panel=SimpleNamespace(btn_evaluate=button),
    )
    monkeypatch.setattr(
        "main_window.LocalizationEvaluationResultsDialog",
        lambda *_args: (_ for _ in ()).throw(AssertionError("edited report displayed")),
    )
    VideoAnnotationWindow._finish_localization_evaluation(owner, worker, report={})
    assert owner._active_localization_evaluation is None
    assert progress.closed
    assert button.enabled
