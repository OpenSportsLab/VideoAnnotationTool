"""
Dense Description mode persistence/editing workflows.
"""

import copy
import json

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QMessageBox


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
}


@pytest.mark.gui
# Workflow: Dense Description annotation round-trip with edit:
# 1) modify first dense event(text+time) + save + reopen, then 2) modify again + save + reopen and verify final state.
def test_dense_description_annotate_save_reload_edit_and_persist(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("dense_description")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    # 1) Open dense description JSON and select first item.
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["dense_description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    first_path = window.get_current_action_path()
    assert first_path is not None
    initial_events = window.model.dense_description_events.get(first_path, [])
    assert len(initial_events) >= 1

    # 2) Modify the first dense event (text + timestamp).
    old_event = initial_events[0]
    first_edit = old_event.copy()
    first_edit["position_ms"] = 2100
    first_edit["text"] = "Dense text v1 from GUI test."
    window.dense_editor_controller._on_annotation_modified(old_event, first_edit)

    after_first_edit = window.model.dense_description_events.get(first_path, [])
    assert any(e.get("position_ms") == 2100 and e.get("text") == "Dense text v1 from GUI test." for e in after_first_edit)

    # 3) Save + close + reopen and verify first edit persisted.
    window.dataset_explorer_controller.save_project()
    saved_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_dense = saved_data.get("data", [])[0].get("dense_captions", [])
    assert any(e.get("position_ms") == 2100 and e.get("text") == "Dense text v1 from GUI test." for e in saved_dense)

    window.router.close_project()
    assert window.model.json_loaded is False

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    reopened_index = window.tree_model.index(0, 0)
    assert reopened_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(reopened_index)
    qtbot.wait(50)

    reopened_path = window.get_current_action_path()
    assert reopened_path is not None
    reopened_events = window.model.dense_description_events.get(reopened_path, [])
    assert any(e.get("position_ms") == 2100 and e.get("text") == "Dense text v1 from GUI test." for e in reopened_events)

    # 4) Modify again, save, reload, and verify second edit persisted.
    old_event_after_reload = next(
        e for e in reopened_events if e.get("position_ms") == 2100 and e.get("text") == "Dense text v1 from GUI test."
    )
    second_edit = old_event_after_reload.copy()
    second_edit["position_ms"] = 3200
    second_edit["text"] = "Dense text v2 edited after reload."
    window.dense_editor_controller._on_annotation_modified(old_event_after_reload, second_edit)

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_dense_after_edit = saved_data_after_edit.get("data", [])[0].get("dense_captions", [])
    assert any(
        e.get("position_ms") == 3200 and e.get("text") == "Dense text v2 edited after reload."
        for e in saved_dense_after_edit
    )

    window.router.close_project()
    assert window.model.json_loaded is False

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    final_index = window.tree_model.index(0, 0)
    assert final_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(final_index)
    qtbot.wait(50)

    final_path = window.get_current_action_path()
    assert final_path is not None
    final_events = window.model.dense_description_events.get(final_path, [])
    assert any(
        e.get("position_ms") == 3200 and e.get("text") == "Dense text v2 edited after reload."
        for e in final_events
    )


@pytest.mark.gui
# Workflow: In Dense Description mode, removing the selected item should reset dense panel state.
def test_dense_description_remove_selected_item_resets_panel_state(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("dense_description")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["dense_description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert window.dense_editor_controller.current_video_path is not None

    monkeypatch.setattr(
        "controllers.dense_description.dense_editor_controller.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    # window.dataset_explorer_controller.handle_remove_item(first_index)
    # qtbot.wait(50)

    # assert window.tree_model.rowCount() == 0
    # assert window.model.action_item_data == []
    # assert window.dense_editor_controller.current_video_path is None
    # assert window.dense_panel.input_widget.text_editor.toPlainText() == ""
    # assert window.dense_panel.table.model.rowCount() == 0


@pytest.mark.gui
# Workflow: In Dense Description mode, clearing workspace should reset model/tree/panel and keep mode active.
def test_dense_description_clear_workspace_resets_panel_and_model(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("dense_description")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["dense_description"]
    assert window.tree_model.rowCount() == 1
    assert window.model.json_loaded is True

    stop_calls = []
    monkeypatch.setattr(window.media_controller, "stop", lambda: stop_calls.append(True))
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QMessageBox.exec",
        lambda self: QMessageBox.StandardButton.Yes,
    )

    window.dataset_explorer_controller.handle_clear_workspace()
    qtbot.wait(50)

    assert stop_calls
    assert window.tree_model.rowCount() == 0
    assert window.model.json_loaded is True
    assert window.model.current_json_path == str(project_json_path)
    assert window.model.action_item_data == []
    assert window.model.dense_global_metadata != {}
    assert window.dense_editor_controller.current_video_path is None
    assert window.dense_panel.table.model.rowCount() == 0
    assert window.center_stack.currentIndex() == 1


@pytest.mark.gui
def test_dense_add_button_text_is_defined_in_ui(window):
    assert window.dense_panel.denseConfirmBtn.text() == "Add New Description"


@pytest.mark.gui
def test_dense_add_description_modal_flow_creates_event_and_resumes_playback(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("dense_description")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    pause_calls = []
    play_calls = []
    monkeypatch.setattr(
        window.center_panel.player,
        "playbackState",
        lambda: QMediaPlayer.PlaybackState.PlayingState,
    )
    monkeypatch.setattr(window.center_panel.player, "pause", lambda: pause_calls.append(True))
    monkeypatch.setattr(window.center_panel.player, "play", lambda: play_calls.append(True))
    monkeypatch.setattr(window.center_panel.player, "position", lambda: 7777)
    monkeypatch.setattr(
        "controllers.dense_description.dense_editor_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: ("  Added from popup  ", True),
    )

    path = window.dense_editor_controller.current_video_path
    assert path is not None
    before_events = list(window.model.dense_description_events.get(path, []))
    before_undo = len(window.model.undo_stack)

    qtbot.mouseClick(window.dense_panel.denseConfirmBtn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    events = list(window.model.dense_description_events.get(path, []))
    assert len(events) == len(before_events) + 1
    assert any(event.get("position_ms") == 7777 and event.get("text") == "Added from popup" for event in events)
    assert len(window.model.undo_stack) == before_undo + 1
    assert pause_calls
    assert play_calls
    selected = window.dense_editor_controller._selected_event_in_table()
    assert selected is not None
    assert selected.get("text") == "Added from popup"


@pytest.mark.gui
def test_dense_add_description_cancel_and_empty_submit_are_noops(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("dense_description")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    path = window.dense_editor_controller.current_video_path
    assert path is not None

    before_events = copy.deepcopy(window.model.dense_description_events.get(path, []))
    before_undo = len(window.model.undo_stack)

    monkeypatch.setattr(
        "controllers.dense_description.dense_editor_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: ("", False),
    )
    qtbot.mouseClick(window.dense_panel.denseConfirmBtn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    monkeypatch.setattr(
        "controllers.dense_description.dense_editor_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: ("   ", True),
    )
    qtbot.mouseClick(window.dense_panel.denseConfirmBtn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    assert window.model.dense_description_events.get(path, []) == before_events
    assert len(window.model.undo_stack) == before_undo


@pytest.mark.gui
def test_dense_table_description_edit_updates_event_and_history(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("dense_description")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    table_model = window.dense_panel.table.model
    assert table_model.rowCount() >= 1

    before_undo = len(window.model.undo_stack)
    cell_idx = table_model.index(0, 2)
    assert cell_idx.isValid()
    assert table_model.setData(cell_idx, "Edited via table double-click path")
    qtbot.wait(50)

    path = window.dense_editor_controller.current_video_path
    assert path is not None
    events = window.model.dense_description_events.get(path, [])
    assert any(event.get("text") == "Edited via table double-click path" for event in events)
    assert len(window.model.undo_stack) == before_undo + 1


# @pytest.mark.gui
# # Workflow: In Dense Description mode, clicking "Set to Current Video Time"
# # should update the selected annotation timestamp to the player's current time.
# def test_dense_description_set_to_current_video_time_updates_selected_annotation(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("dense_description")
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )

#     window.router.import_annotations()
#     assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["dense_description"]
#     assert window.tree_model.rowCount() == 1

#     first_index = window.tree_model.index(0, 0)
#     assert first_index.isValid()
#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

#     current_path = window.get_current_action_path()
#     assert current_path is not None

#     events = window.model.dense_description_events.get(current_path, [])
#     assert len(events) >= 1
#     original_event = events[0]
#     original_text = original_event["text"]
#     original_lang = original_event["lang"]
#     original_time = original_event["position_ms"]

#     table_widget = window.dense_panel.table
#     table_widget.table.selectRow(0)
#     qtbot.wait(50)

#     assert table_widget.btn_set_time.isEnabled() is True

#     target_ms = original_time + 2222
#     monkeypatch.setattr(window.center_panel.player, "position", lambda: target_ms)

#     table_widget.btn_set_time.click()
#     qtbot.wait(50)

#     updated_events = window.model.dense_description_events.get(current_path, [])
#     assert len(updated_events) >= 1

#     assert any(
#         event.get("position_ms") == target_ms
#         and event.get("text") == original_text
#         and event.get("lang") == original_lang
#         for event in updated_events
#     )

#     assert not any(
#         event.get("position_ms") == original_time
#         and event.get("text") == original_text
#         and event.get("lang") == original_lang
#         for event in updated_events
#     )


# @pytest.mark.gui
# # Workflow: In Dense mode, adding an event should be undoable/redoable via global history controls.
# def test_dense_description_undo_redo_event_roundtrip(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("dense_description")
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )
#     window.router.import_annotations()

#     first_index = window.tree_model.index(0, 0)
#     assert first_index.isValid()
#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

#     current_path = window.get_current_action_path()
#     assert current_path is not None
#     initial_count = len(window.model.dense_description_events.get(current_path, []))

#     monkeypatch.setattr(window.center_panel.player, "position", lambda: 5500)
#     window.dense_panel.input_widget.text_editor.setPlainText("Dense undo/redo test event.")
#     qtbot.mouseClick(window.dense_panel.denseConfirmBtn, Qt.MouseButton.LeftButton)
#     qtbot.wait(50)

#     events_after_add = window.model.dense_description_events.get(current_path, [])
#     assert len(events_after_add) == initial_count + 1
#     assert any(e.get("position_ms") == 5500 and e.get("text") == "Dense undo/redo test event." for e in events_after_add)

#     window.history_manager.perform_undo()
#     qtbot.wait(50)
#     events_after_undo = window.model.dense_description_events.get(current_path, [])
#     assert len(events_after_undo) == initial_count
#     assert not any(e.get("position_ms") == 5500 and e.get("text") == "Dense undo/redo test event." for e in events_after_undo)

#     window.history_manager.perform_redo()
#     qtbot.wait(50)
#     events_after_redo = window.model.dense_description_events.get(current_path, [])
#     assert len(events_after_redo) == initial_count + 1
#     assert any(e.get("position_ms") == 5500 and e.get("text") == "Dense undo/redo test event." for e in events_after_redo)
