"""Annotation metadata dialog, signal routing, history, and persistence."""

import copy
import json
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QDialog, QTableView

from ui.dataset_explorer_panel import DatasetExplorerPanel
from ui.json_value_dialog import JsonValueDialog
from ui.localization import _TableAdapter


pytestmark = pytest.mark.gui


def _accept_json(monkeypatch, value, *, initial_values=None, raw=None):
    def accept(dialog):
        if initial_values is not None:
            initial_values.append(dialog.editor.toPlainText())
        dialog.editor.setPlainText(json.dumps(value, ensure_ascii=False) if raw is None else raw)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(JsonValueDialog, "exec", accept)


def _open_project(window, monkeypatch, qtbot, synthetic_project_json, events, *, absolute=False):
    path = synthetic_project_json("localization")
    payload = json.loads(path.read_text())
    payload["data"][0]["events"] = copy.deepcopy(events)
    if absolute:
        payload["data"][0]["inputs"][0]["UTC_time_start"] = "2026-01-01 12:00:00.000000"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    qtbot.wait(50)
    return path


def _event(**fields):
    return {"head": "ball_action", "label": "pass", "position_ms": 1000, **fields}


def _canonical_event(window):
    return window.dataset_explorer_controller.dataset_json["data"][0]["events"][0]


@pytest.mark.parametrize("value", [{"source": "é", "nested": [1, None, True]}, {}])
def test_metadata_dialog_prefills_and_accepts_objects(qtbot, value):
    dialog = JsonValueDialog("metadata", value, objects_only=True)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Edit JSON: metadata"
    assert (dialog.width(), dialog.height()) == (520, 360)
    assert dialog.editor.toPlainText() == json.dumps(value, indent=2, ensure_ascii=False)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.value == value


@pytest.mark.parametrize(
    "raw",
    ["{broken", "", "  ", "[]", '"text"', "42", "true", "null",
     '{"nested": [NaN]}', '{"nested": {"score": Infinity}}',
     '{"score": -Infinity}', '{"score": 1e400}', '{"score": NaN, "score": 0}'],
)
def test_metadata_dialog_rejects_invalid_values_and_retains_text(qtbot, monkeypatch, raw):
    warnings = Mock()
    monkeypatch.setattr("ui.json_value_dialog.QMessageBox.warning", warnings)
    dialog = JsonValueDialog("metadata", {}, objects_only=True)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.editor.setPlainText(raw)
    dialog.accept()
    assert dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.editor.toPlainText() == raw
    assert dialog.value is None
    warnings.assert_called_once()

    dialog.editor.setPlainText('{"corrected": [null, true, {"value": 1.5}]}')
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.value == {"corrected": [None, True, {"value": 1.5}]}


@pytest.mark.parametrize("value", [{"source": "manifest"}, [1, {"nested": True}]])
def test_manifest_uses_shared_dialog_and_keeps_array_support(qtbot, monkeypatch, value):
    panel = DatasetExplorerPanel()
    qtbot.addWidget(panel)
    initial_values = []
    _accept_json(monkeypatch, value, initial_values=initial_values)
    assert panel._open_json_value_dialog("metadata", {"old": True}) == value
    assert json.loads(initial_values[0]) == {"old": True}


def test_context_menu_edits_clicked_event_without_mutating_table(qtbot, monkeypatch):
    table = QTableView()
    qtbot.addWidget(table)
    adapter = _TableAdapter(table)
    events = [_event(), _event(label="shot", position_ms=2000, metadata={"old": "é"})]
    adapter.set_data(copy.deepcopy(events))
    table.resize(600, 300)
    table.show()
    table.selectRow(0)
    changes = QSignalSpy(adapter.annotationMetadataEdited)
    initial_values = []
    _accept_json(monkeypatch, {"new": [1, True]}, initial_values=initial_values)

    def choose_metadata(menu, _pos):
        return next(action for action in menu.actions() if action.text() == "Edit Metadata…")

    monkeypatch.setattr("ui.localization.QMenu.exec", choose_metadata)
    adapter._show_context_menu(table.visualRect(adapter.model.index(1, 0)).center())
    assert len(changes) == 1
    assert changes[0] == [events[1], {"new": [1, True]}]
    assert json.loads(initial_values[0]) == events[1]["metadata"]
    assert adapter.model.get_annotation_at(1) == events[1]

    # Empty space must never open a menu or editor.
    initial_values.clear()
    adapter._show_context_menu(QPoint(5, table.viewport().height() - 5))
    assert initial_values == []
    assert len(changes) == 1


@pytest.mark.parametrize("predicted", [False, True])
def test_metadata_commit_is_atomic_and_preserves_event_and_playback(
    window, monkeypatch, qtbot, synthetic_project_json, predicted,
):
    event = _event(
        timestamp_utc="2026-01-01 12:00:01.123456",
        metadata={"old": {"value": 1}},
        custom_field="preserved",
    )
    if predicted:
        event.update(confidence_score=0.84, inference_model_id="test-model")
    _open_project(window, monkeypatch, qtbot, synthetic_project_json, [event], absolute=True)
    explorer = window.dataset_explorer_controller
    before = copy.deepcopy(explorer.dataset_json)
    undo_before = len(explorer.undo_stack)
    controller = window.localization_editor_controller
    adapter = window.localization_panel.table
    seeks = QSignalSpy(controller.mediaSeekRequested)
    markers = QSignalSpy(controller.markersUpdateRequested)
    populate = Mock(wraps=explorer.populate_tree)
    reload_media = Mock(wraps=window.media_controller.load_and_play)
    monkeypatch.setattr(explorer, "populate_tree", populate)
    monkeypatch.setattr(window.media_controller, "load_and_play", reload_media)
    metadata = {"team": "équipe", "details": {"tags": ["pass", None], "reviewed": True}}
    _accept_json(monkeypatch, metadata)
    adapter._edit_metadata(adapter.model.get_annotation_at(0))
    qtbot.wait(50)

    expected = copy.deepcopy(event)
    expected["metadata"] = metadata
    assert _canonical_event(window) == expected
    assert len(explorer.undo_stack) == undo_before + 1
    assert len(explorer.redo_stack) == 0
    assert explorer.is_data_dirty
    assert adapter.model.get_annotation_at(0)["metadata"] == metadata
    assert adapter.table.selectionModel().selectedRows()[0].row() == 0
    assert bool(controller._pending_prediction_sample_ids) == predicted
    assert len(seeks) == len(markers) == 0
    populate.assert_not_called()
    reload_media.assert_not_called()
    after = copy.deepcopy(explorer.dataset_json)

    window.history_manager.perform_undo()
    assert explorer.dataset_json == before
    window.history_manager.perform_redo()
    assert explorer.dataset_json == after
    assert adapter.model.get_annotation_at(0)["metadata"] == metadata
    populate.assert_not_called()
    reload_media.assert_not_called()

    window.history_manager.perform_undo()
    _accept_json(monkeypatch, {"replacement": True})
    adapter._edit_metadata(adapter.model.get_annotation_at(0))
    assert len(explorer.redo_stack) == 0
    assert len(explorer.undo_stack) == undo_before + 1


def test_metadata_edit_keeps_same_time_events_distinct_and_selected(
    window, monkeypatch, qtbot, synthetic_project_json,
):
    first = _event(timestamp_utc="2026-01-01 12:00:01.123456", metadata={"player": 1})
    second = _event(timestamp_utc=first["timestamp_utc"], metadata={"player": 2})
    _open_project(window, monkeypatch, qtbot, synthetic_project_json, [first, second], absolute=True)
    adapter = window.localization_panel.table
    _accept_json(monkeypatch, {"player": 22})
    adapter._edit_metadata(adapter.model.get_annotation_at(1))
    events = window.dataset_explorer_controller.dataset_json["data"][0]["events"]
    assert events == [first, dict(second, metadata={"player": 22})]
    assert adapter.table.selectionModel().selectedRows()[0].row() == 1
    window.history_manager.perform_undo()
    assert window.dataset_explorer_controller.dataset_json["data"][0]["events"] == [first, second]


@pytest.mark.parametrize("existing", [None, {"nested": [1, True]}])
@pytest.mark.parametrize("empty_text", ["{}", "", " \n\t"])
def test_metadata_cancel_and_noop_leave_document_and_history_unchanged(
    window, monkeypatch, qtbot, synthetic_project_json, existing, empty_text,
):
    event = _event()
    if existing is not None:
        event["metadata"] = existing
    _open_project(window, monkeypatch, qtbot, synthetic_project_json, [event])
    explorer = window.dataset_explorer_controller
    before = copy.deepcopy(explorer.dataset_json)
    adapter = window.localization_panel.table
    # Keep a redo entry so a no-op must preserve both stacks.
    window.history_manager.execute_localization_event_metadata_set("clip_1", event, {"temporary": True})
    window.history_manager.perform_undo()
    stacks = (copy.deepcopy(explorer.undo_stack), copy.deepcopy(explorer.redo_stack))
    dirty_before = explorer.is_data_dirty

    def cancel(dialog):
        dialog.editor.setPlainText('{"unsaved": true}')
        dialog.reject()
        return dialog.result()

    monkeypatch.setattr(JsonValueDialog, "exec", cancel)
    adapter._edit_metadata(adapter.model.get_annotation_at(0))
    _accept_json(monkeypatch, existing or {}, raw=empty_text if existing is None else None)
    adapter._edit_metadata(adapter.model.get_annotation_at(0))
    # Exercise the owner guard as well as the UI/controller no-op guards.
    window.history_manager.execute_localization_event_metadata_set("clip_1", event, existing or {})
    assert explorer.dataset_json == before
    assert (explorer.undo_stack, explorer.redo_stack) == stacks
    assert explorer.is_data_dirty == dirty_before


@pytest.mark.parametrize("existing", [{}, {"old": True}, ["legacy-invalid"], None])
@pytest.mark.parametrize("empty_text", ["{}", "", " \n\t"])
def test_metadata_empty_and_legacy_replacement_roundtrip(
    window, monkeypatch, qtbot, synthetic_project_json, tmp_path, existing, empty_text,
):
    # Explicit null and arrays in old files remain unchanged until replacement.
    event = _event(metadata=existing, confidence_score=0.7, inference_model_id="model")
    path = _open_project(window, monkeypatch, qtbot, synthetic_project_json, [event])
    assert _canonical_event(window)["metadata"] == existing
    explorer = window.dataset_explorer_controller
    before = copy.deepcopy(explorer.dataset_json)
    undo_before = len(explorer.undo_stack)
    adapter = window.localization_panel.table

    def cancel(dialog):
        dialog.editor.clear()
        dialog.reject()
        return dialog.result()

    monkeypatch.setattr(JsonValueDialog, "exec", cancel)
    adapter._edit_metadata(adapter.model.get_annotation_at(0))
    assert explorer.dataset_json == before
    assert len(explorer.undo_stack) == undo_before

    _accept_json(monkeypatch, {}, raw=empty_text)
    adapter._edit_metadata(adapter.model.get_annotation_at(0))
    expected_event = {key: value for key, value in event.items() if key != "metadata"}
    assert _canonical_event(window) == expected_event
    assert "metadata" not in adapter.model.get_annotation_at(0)
    assert len(explorer.undo_stack) == undo_before + 1
    after = copy.deepcopy(explorer.dataset_json)
    window.history_manager.perform_undo()
    assert explorer.dataset_json == before
    window.history_manager.perform_redo()
    assert explorer.dataset_json == after

    initial_values = []
    _accept_json(monkeypatch, {}, initial_values=initial_values, raw=empty_text)
    adapter._edit_metadata(adapter.model.get_annotation_at(0))
    assert initial_values == ["{}"]
    assert len(explorer.undo_stack) == undo_before + 1
    assert explorer.save_project()
    assert "metadata" not in json.loads(path.read_text())["data"][0]["events"][0]

    export_path = tmp_path / "metadata_export.json"
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "JSON (*.json)"),
    )
    assert explorer.export_project()
    assert "metadata" not in json.loads(export_path.read_text())["data"][0]["events"][0]
    explorer.close_project()
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(export_path), "JSON Files (*.json)"),
    )
    explorer.import_annotations()
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    assert "metadata" not in _canonical_event(window)

    # Ordinary event edits and confirmation must retain the custom metadata.
    metadata = {"player": {"id": 7}, "tags": ["reviewed"]}
    _accept_json(monkeypatch, metadata)
    adapter._edit_metadata(adapter.model.get_annotation_at(0))
    window.localization_editor_controller._on_confirm_single_annotation(
        adapter.model.get_annotation_at(0)
    )
    assert _canonical_event(window)["metadata"] == metadata
    assert "confidence_score" not in _canonical_event(window)
    assert adapter.model.setData(adapter.model.index(0, 0), "00:02.000", Qt.ItemDataRole.EditRole)
    assert _canonical_event(window)["metadata"] == metadata
    assert window.dataset_explorer_controller.save_project()
    assert json.loads(export_path.read_text())["data"][0]["events"][0]["metadata"] == metadata

    assert window.dataset_explorer_controller.export_project()
    assert json.loads(export_path.read_text())["data"][0]["events"][0]["metadata"] == metadata
    window.dataset_explorer_controller.close_project()
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(export_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    assert _canonical_event(window)["metadata"] == metadata
