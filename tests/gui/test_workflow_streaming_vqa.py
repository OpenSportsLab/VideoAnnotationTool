"""Streaming VQA authoring, persistence, history, and shared-timeline contracts."""

import copy
import inspect
import json
from uuid import UUID

import pytest
from PyQt6.QtWidgets import QDialog

from controllers.streaming_vqa import StreamingVQAEditorController
from streaming_vqa import entry_errors, has_valid_entries, normalize_for_write
from ui.streaming_vqa import StreamingVQADialog


def question(question_id="q1", position=1000):
    return {
        "id": question_id,
        "position_ms": position,
        "question": "Who passed before the last shot?",
        "options": [{"id": "a", "text": "Player 7"}, {"id": "b", "text": "Player 10"}],
        "correct_option_id": "b",
    }


@pytest.fixture
def streaming_project(window, monkeypatch, qtbot, synthetic_project_json):
    def open_project(entries=None, utc=False, count=1, multi=False):
        path = synthetic_project_json("classification", item_count=count)
        data = json.loads(path.read_text())
        for sample in data["data"]:
            sample.pop("labels", None)
            sample["streaming_vqa"] = copy.deepcopy(entries if entries is not None else [question()])
            if utc:
                sample["inputs"][0]["UTC_time_start"] = "2026-01-01 12:00:00.000000"
            if multi:
                second = copy.deepcopy(sample["inputs"][0])
                second["path"] = second["path"].replace("test_video_1.mp4", "test_video_2.mp4")
                second["UTC_time_start"] = "2026-01-01 12:00:01.000000"
                sample["inputs"].append(second)
        path.write_text(json.dumps(data))
        explorer = window.dataset_explorer_controller
        monkeypatch.setattr(explorer, "check_and_close_current_project", lambda: True)
        monkeypatch.setattr("controllers.dataset_explorer_controller.QFileDialog.getOpenFileName", lambda *a, **k: (str(path), "JSON"))
        explorer.import_annotations()
        window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
        qtbot.wait(30)
        window.right_tabs.setCurrentIndex(5)
        return path
    return open_project


def test_dialog_option_identity_validation_and_unknown_fields(qtbot):
    entry = question()
    entry["custom"] = {"source": "human"}
    entry["options"][1]["extra"] = 42
    dialog = StreamingVQADialog(entry)
    qtbot.addWidget(dialog)
    dialog.move_option(dialog.option_rows[1][0], -1)
    assert dialog.option_rows[0][2].isChecked()
    dialog.accept()
    assert dialog.result_entry["correct_option_id"] == "b"
    assert dialog.result_entry["options"][0] == entry["options"][1]
    assert dialog.result_entry["custom"] == entry["custom"]

    repair = StreamingVQADialog(dialog.result_entry)
    qtbot.addWidget(repair)
    repair.remove_option(repair.option_rows[0][0])
    repair.add_option({"id": "c", "text": "Player 9"})
    repair.accept()
    assert repair.result_entry is None
    assert "correct choice" in repair.error_label.text()
    repair.option_rows[1][2].setChecked(True)
    repair.accept()
    assert repair.result_entry["correct_option_id"] == "c"


def test_untouched_dialog_preserves_whitespace_and_utc_precision(qtbot):
    entry = dict(question(), question="  Who passed?  ", timestamp_utc="2026-01-01T12:00:01.123456Z")
    entry["options"][0]["text"] = " Player 7 "
    dialog = StreamingVQADialog(entry, "2026-01-01 12:00:00")
    qtbot.addWidget(dialog)
    assert dialog.time_edit.text() == "2026-01-01 12:00:01.123456 UTC"
    dialog.accept()
    assert dialog.result_entry == entry


@pytest.mark.parametrize("changes", [
    {"question": " "}, {"position_ms": -1}, {"position_ms": 1.5},
    {"position_ms": True}, {"options": []}, {"correct_option_id": "missing"},
    {"timestamp_utc": "bad-time"},
    {"options": [{"id": "a", "text": "same"}, {"id": "b", "text": " same "}]},
    {"options": [{"id": "b", "text": "one"}, {"id": "b", "text": "two"}]},
])
def test_incomplete_or_invalid_entries_are_not_annotated(changes):
    entry = dict(question(), **changes)
    assert entry_errors(entry)
    assert not has_valid_entries([entry])


def test_add_pause_capture_atomic_history_and_reopen(window, monkeypatch, qtbot, streaming_project):
    path = streaming_project([])
    explorer = window.dataset_explorer_controller
    panel = window.streaming_vqa_panel
    before = copy.deepcopy(explorer.dataset_json)
    monkeypatch.setattr(window.media_controller, "current_position_ms", lambda: 1500)

    def complete(dialog):
        assert window.media_controller.is_playing() is False
        assert dialog.time_edit.text() == "00:01.500"
        assert len(dialog.option_rows) == 4
        dialog.question_edit.setPlainText("Who passed?")
        for index, row in enumerate(dialog.option_rows):
            row[3].setText(f"Player {index + 1}")
        dialog.option_rows[2][2].setChecked(True)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(StreamingVQADialog, "exec", complete)
    window.media_controller.play()
    panel.add_button.click()
    assert len(explorer.undo_stack) == 1
    after = copy.deepcopy(explorer.dataset_json)
    added = after["data"][0]["streaming_vqa"][0]
    UUID(added["id"])
    for option in added["options"]:
        UUID(option["id"])
    assert added["position_ms"] == 1500
    assert not window.media_controller.is_playing()
    assert "timestamp_utc" not in added
    assert panel.table.rowCount() == 1
    window.history_manager.perform_undo()
    assert explorer.dataset_json == before
    assert panel.table.rowCount() == 0
    window.history_manager.perform_redo()
    assert explorer.dataset_json == after
    assert panel.table.rowCount() == 1

    explorer.save_project()
    assert json.loads(path.read_text())["data"][0]["streaming_vqa"] == [added]
    exported = path.with_name("exported.json")
    monkeypatch.setattr("controllers.dataset_explorer_controller.QFileDialog.getSaveFileName", lambda *a, **k: (str(exported), "JSON"))
    explorer.export_project()
    assert json.loads(exported.read_text())["data"][0]["streaming_vqa"] == [added]
    explorer.close_project()
    assert panel.table.rowCount() == 0
    explorer.import_annotations()
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    assert panel.table.rowCount() == 1
    assert explorer.get_sample("clip_1")["streaming_vqa"] == [added]


def test_edit_delete_cancel_noop_and_redo(window, monkeypatch, streaming_project):
    streaming_project()
    explorer = window.dataset_explorer_controller
    panel = window.streaming_vqa_panel
    panel.table.selectRow(0)
    before = copy.deepcopy(explorer.dataset_json)
    monkeypatch.setattr(StreamingVQADialog, "exec", lambda dialog: QDialog.DialogCode.Rejected)
    panel.edit_button.click()
    panel.add_button.click()
    assert explorer.dataset_json == before
    assert not explorer.undo_stack

    def no_change(dialog):
        dialog.accept()
        return dialog.result()
    monkeypatch.setattr(StreamingVQADialog, "exec", no_change)
    panel.edit_button.click()
    assert not explorer.undo_stack

    def edit(dialog):
        dialog.time_edit.setText("00:02.250")
        dialog.question_edit.setPlainText("How many passes happened?")
        dialog.accept()
        return dialog.result()
    monkeypatch.setattr(StreamingVQADialog, "exec", edit)
    panel.edit_button.click()
    after_edit = copy.deepcopy(explorer.dataset_json)
    assert after_edit["data"][0]["streaming_vqa"][0]["position_ms"] == 2250
    assert len(explorer.undo_stack) == 1
    window.history_manager.perform_undo()
    assert explorer.dataset_json == before
    window.history_manager.perform_redo()
    assert explorer.dataset_json == after_edit
    panel.delete_button.click()
    assert "streaming_vqa" not in explorer.get_sample("clip_1")
    assert len(explorer.undo_stack) == 2
    window.history_manager.perform_undo()
    assert explorer.dataset_json == after_edit
    window.history_manager.execute_streaming_vqa_update("clip_1", [question("new")])
    assert not explorer.redo_stack


def test_duplicate_text_chronology_selection_and_tab_switch(window, monkeypatch, streaming_project):
    streaming_project([question("late", 2000), question("early", 500), question("same", 2000)])
    panel = window.streaming_vqa_panel
    explorer = window.dataset_explorer_controller
    assert panel.table.item(0, 0).text() == "00:00.500"
    assert panel.table.rowCount() == 3
    seeks = []
    window.streaming_vqa_editor_controller.mediaSeekRequested.connect(seeks.append)
    panel.table.selectRow(0)
    assert seeks == [500]
    panel.go_button.click()
    assert seeks == [500, 500]
    original = copy.deepcopy(explorer.dataset_json)
    monkeypatch.setattr(explorer, "populate_tree", lambda *a, **k: pytest.fail("Tab switch rebuilt tree"))
    routed = []
    explorer.mediaRouteRequested.connect(lambda *args: routed.append(args))
    seeks.clear()
    window.right_tabs.setCurrentIndex(4)
    assert not window.center_panel.slider.markers
    window.right_tabs.setCurrentIndex(5)
    assert len(window.center_panel.slider.markers) == 3
    assert not window.action_run_inference.isEnabled()
    assert not seeks and not routed
    assert explorer.dataset_json == original
    assert not explorer.undo_stack
    # Question selection must not install a playback cutoff.
    window.media_controller.set_position(2500)
    assert window.media_controller.current_position_ms() == 2500


def test_utc_projection_edit_and_origin_change(window, monkeypatch, streaming_project):
    entry = dict(question(), timestamp_utc="2026-01-01T14:00:02.500000+02:00")
    path = streaming_project([entry], utc=True)
    panel = window.streaming_vqa_panel
    explorer = window.dataset_explorer_controller
    sample = explorer.get_sample("clip_1")
    assert panel.table.item(0, 0).text() == "2026-01-01 12:00:02.500 UTC"
    assert sample["streaming_vqa"][0] == entry
    panel.table.selectRow(0)
    assert window.media_controller.current_position_ms() == 2500
    window.streaming_vqa_editor_controller.on_timeline_origin_changed("clip_1", "2026-01-01 12:00:01")
    seeks = []
    window.streaming_vqa_editor_controller.mediaSeekRequested.connect(seeks.append)
    panel.go_button.click()
    assert seeks == [1500]
    assert sample["streaming_vqa"][0] == entry

    def edit(dialog):
        dialog.time_edit.setText("2026-01-01T14:00:03.250+02:00")
        dialog.accept()
        return dialog.result()
    monkeypatch.setattr(StreamingVQADialog, "exec", edit)
    panel.edit_button.click()
    saved = sample["streaming_vqa"][0]
    assert saved["timestamp_utc"] == "2026-01-01 12:00:03.250000"
    assert saved["position_ms"] == 2250
    explorer.save_project()
    # Persistence resolves the real sample origin (12:00:00).
    written = json.loads(path.read_text())["data"][0]["streaming_vqa"][0]
    assert written["position_ms"] == 3250


def test_legacy_utc_noop_and_invalid_import_preservation(window, monkeypatch, streaming_project):
    rows = [question(), {"id": "broken", "timestamp_utc": "bad"}, "bad-row"]
    path = streaming_project(rows, utc=True)
    panel = window.streaming_vqa_panel
    explorer = window.dataset_explorer_controller
    panel.table.selectRow(2)
    # Select the valid question by its raw index, irrespective of display sorting.
    for row in range(panel.table.rowCount()):
        panel.table.selectRow(row)
        if panel.selected_index() == 0:
            break
    def unchanged(dialog):
        dialog.accept()
        return dialog.result()
    monkeypatch.setattr(StreamingVQADialog, "exec", unchanged)
    panel.edit_button.click()
    assert not explorer.undo_stack
    explorer.save_project()
    saved = json.loads(path.read_text())["data"][0]["streaming_vqa"]
    assert saved[0]["timestamp_utc"] == "2026-01-01 12:00:01.000000"
    assert saved[1:] == rows[1:]
    assert any(panel.table.item(row, 1).text().startswith("⚠") for row in range(3))


def test_completion_filter_clear_selection_and_reset(window, qtbot, streaming_project):
    streaming_project(count=2)
    explorer = window.dataset_explorer_controller
    assert explorer._label_state_for_sample(explorer.get_sample("clip_1")) == (True, False)
    # Show Done; deleting the selected sample's only question must not select clip_2.
    window.dataset_explorer_panel.filter_combo.setCurrentIndex(1)
    window.streaming_vqa_panel.table.selectRow(0)
    window.streaming_vqa_panel.delete_button.click()
    qtbot.wait(200)
    assert not explorer.current_selected_sample_id
    assert window.streaming_vqa_panel.table.rowCount() == 0
    assert not window.streaming_vqa_panel.add_button.isEnabled()
    explorer.close_project()
    assert not window.streaming_vqa_editor_controller._origins


def test_invalid_rows_ids_and_temporal_preservation():
    rows = [question(), question(), "broken"]
    assert not has_valid_entries(rows)
    assert normalize_for_write(rows, "2026-01-01") == rows
    entry = dict(question(), timestamp_utc="2026-01-01 12:00:01")
    projected = normalize_for_write([entry], "2026-01-01 12:00:05")[0]
    assert projected["position_ms"] == -4000
    assert projected["timestamp_utc"] == "2026-01-01 12:00:01.000000"
    assert not entry_errors(projected)


def test_multiview_focus_and_utc_alignment_history(window, qtbot, streaming_project):
    streaming_project([question(position=2500)], utc=True, multi=True)
    explorer = window.dataset_explorer_controller
    panel = window.streaming_vqa_panel
    parent = window.tree_model.index(0, 0)
    assert window.tree_model.rowCount(parent) == 2
    panel.table.selectRow(0)
    before = copy.deepcopy(explorer.dataset_json)
    assert window.media_controller.current_position_ms() == 2500
    for index in (window.tree_model.index(1, 0, parent), parent):
        window.dataset_explorer_panel.tree.setCurrentIndex(index)
        assert window.media_controller.current_position_ms() == 2500
    assert explorer.dataset_json == before
    assert not explorer.undo_stack

    input_path = explorer.get_media_sources_by_id("clip_1")[0]["path"]
    window._handle_input_utc_start_mutation(input_path, "2026-01-01 12:00:02")
    after = copy.deepcopy(explorer.dataset_json)
    entry = after["data"][0]["streaming_vqa"][0]
    # The other input is now the earliest (12:00:01); the original ask instant stays fixed.
    assert entry["timestamp_utc"] == "2026-01-01 12:00:02.500000"
    assert entry["position_ms"] == 1500
    assert len(explorer.undo_stack) == 1
    window.history_manager.perform_undo()
    assert explorer.dataset_json == before
    window.history_manager.perform_redo()
    assert explorer.dataset_json == after


def test_repair_duplicate_id_and_bad_time(qtbot):
    entry = dict(question(), timestamp_utc="broken")
    dialog = StreamingVQADialog(entry, other_ids=[entry["id"]])
    qtbot.addWidget(dialog)
    dialog.accept()
    assert dialog.result_entry is None
    dialog.time_edit.setText("garbage")
    dialog.accept()
    assert dialog.result_entry is None
    dialog.time_edit.setText("01:02.003")
    dialog.accept()
    repaired = dialog.result_entry
    UUID(repaired["id"])
    assert repaired["id"] != entry["id"]
    assert repaired["position_ms"] == 62003
    assert "timestamp_utc" not in repaired
    assert not entry_errors(repaired)


def test_invalid_container_is_preserved_and_explicitly_repaired(window, monkeypatch, streaming_project):
    entry = question()
    path = streaming_project(entry)
    explorer = window.dataset_explorer_controller
    panel = window.streaming_vqa_panel
    assert panel.table.item(0, 1).text().startswith("⚠")
    assert explorer._label_state_for_sample(explorer.get_sample("clip_1")) == (False, False)
    explorer.save_project()
    assert json.loads(path.read_text())["data"][0]["streaming_vqa"] == entry
    before = copy.deepcopy(explorer.dataset_json)
    panel.table.selectRow(0)
    assert "must be an array" in panel.details.toPlainText()
    def repair(dialog):
        dialog.accept()
        return dialog.result()
    monkeypatch.setattr(StreamingVQADialog, "exec", repair)
    panel.edit_button.click()
    assert explorer.get_sample("clip_1")["streaming_vqa"] == [entry]
    assert len(explorer.undo_stack) == 1
    window.history_manager.perform_undo()
    assert explorer.dataset_json == before


def test_utc_removal_preserves_ask_instant(window, streaming_project):
    streaming_project(utc=True)
    explorer = window.dataset_explorer_controller
    before = copy.deepcopy(explorer.dataset_json)
    input_path = explorer.get_media_sources_by_id("clip_1")[0]["path"]
    window._handle_input_utc_start_removal(input_path)
    entry = explorer.get_sample("clip_1")["streaming_vqa"][0]
    assert entry["timestamp_utc"] == "2026-01-01 12:00:01.000000"
    assert entry["position_ms"] == 1000
    assert len(explorer.undo_stack) == 1
    window.history_manager.perform_undo()
    assert explorer.dataset_json == before


def test_controller_boundary():
    assert list(inspect.signature(StreamingVQAEditorController.__init__).parameters) == ["self", "panel"]
    source = inspect.getsource(StreamingVQAEditorController)
    assert "QMediaPlayer" not in source
    assert "main_window" not in source
    assert "dataset_json" not in source
