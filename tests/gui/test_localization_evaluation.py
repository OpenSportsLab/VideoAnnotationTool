"""Read-only localization evaluation and its Qt selection/report dialogs."""

import copy
from types import SimpleNamespace

import pytest

from controllers.localization import LocalizationEditorController
from localization_evaluation import (
    LocalizationEvaluationWorker, _fast_average_precision, evaluate_localization_heads,
    project_utc_events_for_evaluation,
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


def test_indexed_average_precision_matches_opensportslib():
    import random
    from opensportslib.metrics.localization_metric import compute_average_precision

    rng = random.Random(2026)
    for _case in range(250):
        truth = {
            f"video-{index}": [rng.randrange(20) for _ in range(rng.randrange(1, 10))]
            for index in range(3)
        }
        predictions = sorted(
            [
                (f"video-{rng.randrange(3)}", rng.randrange(20), rng.randrange(11) / 10)
                for _ in range(rng.randrange(30))
            ],
            key=lambda item: item[2], reverse=True,
        )
        tolerance = rng.randrange(7)
        assert _fast_average_precision(predictions, truth, tolerance) == pytest.approx(
            compute_average_precision(predictions, truth, tolerance=tolerance)
        )


def test_indexed_average_precision_can_cancel_during_scoring():
    calls = 0

    def should_cancel():
        nonlocal calls
        calls += 1
        return calls > 1

    predictions = [("video", index, 1.0) for index in range(600)]
    with pytest.raises(InterruptedError, match="cancelled"):
        _fast_average_precision(
            predictions, {"video": list(range(600))}, 0,
            should_cancel=should_cancel,
        )


def test_localization_evaluation_reports_scoring_progress(monkeypatch):
    monkeypatch.setattr("localization_evaluation.FAST_AP_COMPARISON_THRESHOLD", 0)
    samples = [{"id": "one", "events": [
        {"head": "truth", "label": "pass", "position_ms": 1000},
        {"head": "prediction", "label": "PASS", "position_ms": 1000},
    ]}]
    progress = []
    report = _evaluate(samples, on_progress=lambda value, text: progress.append((value, text)))
    assert report["overall"]["ap"][1000] == 1.0
    assert progress[0][0] == 20
    assert any("Scoring pass: AP@" in text for _value, text in progress)
    assert progress[-1] == (100, "Evaluation complete")
    assert [value for value, _text in progress] == sorted(value for value, _text in progress)


def test_localization_evaluation_projects_only_samples_and_heads_in_scope(
    tmp_path, monkeypatch
):
    from datetime import datetime

    for name in ("one.h5", "two.h5"):
        (tmp_path / name).write_bytes(b"placeholder")
    samples = [
        {"id": "one", "inputs": [{"type": "player_joints_h5", "path": "one.h5"}],
         "events": [
             {"head": "truth", "label": "pass",
              "timestamp_utc": "2025-01-01T00:00:01"},
             {"head": "other", "label": "shot",
              "timestamp_utc": "2025-01-01T00:00:01"},
         ]},
        {"id": "two", "inputs": [{"type": "player_joints_h5", "path": "two.h5"}],
         "events": [{"head": "truth", "label": "pass",
                     "timestamp_utc": "2025-01-01T00:00:01"}]},
    ]
    scanned = []

    def origin(path, _should_cancel, _on_progress):
        scanned.append(path)
        return datetime(2025, 1, 1)

    monkeypatch.setattr("localization_evaluation.earliest_h5_timestamp_utc", origin)
    project_utc_events_for_evaluation(
        samples, str(tmp_path), scope="selected", selected_sample_id="one",
        heads=("truth", "prediction"),
    )
    assert scanned == [str(tmp_path / "one.h5")]
    assert samples[0]["events"][0]["position_ms"] == 1000
    assert "position_ms" not in samples[0]["events"][1]
    assert "position_ms" not in samples[1]["events"][0]


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
    progress = []
    worker.progress.connect(lambda value, text: progress.append((value, text)))
    with qtbot.waitSignal(worker.completed, timeout=10000) as signal:
        worker.start()
    assert worker.wait(10000)
    assert signal.args[0]["overall"]["ap"] == {1000: 1.0, 2000: 1.0}
    assert progress[-1] == (100, "Evaluation complete")


@pytest.mark.gui
def test_localization_evaluation_progress_dialog_shows_stage_percent_and_elapsed(qtbot):
    import time
    from PyQt6.QtWidgets import QProgressDialog
    from main_window import VideoAnnotationWindow

    progress = QProgressDialog("Preparing…", "Cancel", 0, 100)
    qtbot.addWidget(progress)
    worker = object()
    owner = SimpleNamespace(_active_localization_evaluation={
        "worker": worker, "progress": progress, "discard": False,
        "progress_text": "Preparing…", "started_at": time.monotonic() - 65,
    })
    owner._refresh_localization_evaluation_progress = lambda: (
        VideoAnnotationWindow._refresh_localization_evaluation_progress(owner)
    )
    VideoAnnotationWindow._on_localization_evaluation_progress(
        owner, worker, 42, "Scoring pass: AP@2 s (3/17)"
    )
    assert progress.value() == 42
    assert "Scoring pass: AP@2 s (3/17)" in progress.labelText()
    assert "Elapsed: 01:05" in progress.labelText()


@pytest.mark.gui
def test_localization_evaluation_h5_projection_runs_in_worker(qtbot, tmp_path):
    import h5py

    h5_path = tmp_path / "tracking.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("timestamp_utc", data=[
            b"2025-01-01T00:00:00", b"2025-01-01T00:00:03",
        ])
    samples = [{"id": "one", "inputs": [{
        "type": "player_joints_h5", "path": "tracking.h5",
    }], "events": [
        {"head": "truth", "label": "pass", "position_ms": 90000,
         "timestamp_utc": "2025-01-01T00:00:02"},
        {"head": "prediction", "label": "PASS", "position_ms": 0,
         "timestamp_utc": "2025-01-01T00:00:02.100"},
    ]}]
    original = copy.deepcopy(samples)
    worker = LocalizationEvaluationWorker(samples, {
        "scope": "project", "selected_sample_id": "one",
        "truth_head": "truth", "prediction_head": "prediction",
        "mapping": {"PASS": "pass"}, "tolerances_ms": (0, 100),
        "truth_labels": ("pass",),
    }, str(tmp_path))
    progress = []
    worker.progress.connect(lambda _value, text: progress.append(text))
    with qtbot.waitSignal(worker.completed, timeout=10000) as signal:
        worker.start()
    assert worker.wait(10000)
    assert signal.args[0]["overall"]["ap"] == {0: 0.0, 100: 1.0}
    assert original[0]["events"][0]["position_ms"] == 90000
    assert samples[0]["events"][0]["position_ms"] == 2000
    assert any("Reading H5 timestamps" in text for text in progress)


@pytest.mark.gui
def test_localization_evaluation_keeps_qt_responsive_during_h5_read(
    qtbot, tmp_path, monkeypatch
):
    import time
    from datetime import datetime
    from PyQt6.QtCore import QTimer

    (tmp_path / "tracking.h5").write_bytes(b"placeholder")

    def slow_origin(_path, _should_cancel, _on_progress):
        time.sleep(0.2)
        return datetime(2025, 1, 1)

    monkeypatch.setattr("localization_evaluation.earliest_h5_timestamp_utc", slow_origin)
    samples = [{"id": "one", "inputs": [{
        "type": "player_joints_h5", "path": "tracking.h5",
    }], "events": [
        {"head": "truth", "label": "pass", "timestamp_utc": "2025-01-01T00:00:01"},
    ]}]
    worker = LocalizationEvaluationWorker(samples, {
        "scope": "project", "selected_sample_id": "one",
        "truth_head": "truth", "prediction_head": "prediction",
        "mapping": {}, "tolerances_ms": (1000,), "truth_labels": ("pass",),
    }, str(tmp_path))
    qt_responsive = []
    with qtbot.waitSignal(worker.completed, timeout=10000):
        worker.start()
        QTimer.singleShot(30, lambda: qt_responsive.append(worker.isRunning()))
    assert worker.wait(10000)
    assert qt_responsive == [True]


@pytest.mark.gui
def test_open_localization_evaluation_does_not_scan_timeline_before_dialog(monkeypatch):
    from main_window import VideoAnnotationWindow

    sample = {"id": "one", "events": [{
        "head": "truth", "label": "pass", "position_ms": 0,
        "timestamp_utc": "2025-01-01T00:00:00",
    }]}

    class Explorer:
        dataset_json = {"data": [sample], "labels": {"truth": {"labels": ["pass"]}}}
        project_generation = 1
        current_selected_sample_id = "one"

        def get_samples(self):
            return self.dataset_json["data"]

        def _timeline_origin_for_sample(self, _sample):
            raise AssertionError("Timeline scan ran on the UI thread")

    class Dialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, *_args):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr("main_window.LocalizationEvaluationDialog", Dialog)
    owner = SimpleNamespace(
        _active_localization_evaluation=None,
        dataset_explorer_controller=Explorer(),
        localization_panel=SimpleNamespace(
            annot_mgmt=SimpleNamespace(
                tabs=SimpleNamespace(get_current_head=lambda: "truth")
            )
        ),
    )
    VideoAnnotationWindow._open_localization_evaluation(owner)


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


@pytest.mark.gui
@pytest.mark.parametrize("discard", [False, True])
def test_completed_evaluation_passes_h5_origins_to_explorer_cache(monkeypatch, discard):
    from main_window import VideoAnnotationWindow

    class Progress:
        def close(self):
            pass

    class Button:
        def setEnabled(self, _value):
            pass

    class ResultsDialog:
        def __init__(self, *_args):
            pass

        def exec(self):
            return None

    monkeypatch.setattr("main_window.LocalizationEvaluationResultsDialog", ResultsDialog)
    project = {"data": []}
    records = {"/tmp/tracking.h5": ((1, 2), None)}
    worker = SimpleNamespace(h5_origin_records=records)
    cached = []
    owner = SimpleNamespace(
        _active_localization_evaluation={
            "worker": worker, "progress": Progress(), "generation": 1,
            "project_snapshot": project, "discard": discard,
        },
        dataset_explorer_controller=SimpleNamespace(
            project_generation=1, dataset_json=project,
            cache_h5_timeline_origins=lambda value: cached.append(value),
        ),
        localization_panel=SimpleNamespace(btn_evaluate=Button()),
    )
    VideoAnnotationWindow._finish_localization_evaluation(owner, worker, report={})
    assert cached == [records]
