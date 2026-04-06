"""
GUI lifecycle smoke tests for `VideoAnnotationWindow` using pytest-qt.

Coverage goals:
- Launch and base routing behavior.
- Import/close lifecycle flows.
- Persistence workflows (save -> close -> reopen) across all annotation modes.
- Edit-after-reload workflows to guard against serialization regressions.

Test style:
- Patch Qt file dialogs to deterministic local fixture files.
- Drive UI through widgets/signals where practical.
- Assert both in-memory model state and on-disk JSON content.
"""

import json
import shutil
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QMessageBox, QPushButton, QToolButton


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
}
# Mapping between mode identifiers and right-tab indexes in `MainWindow`.


def _get_recent_row_controls(window, row: int):
    recent_list = window.welcome_widget.recent_projects_list
    item = recent_list.item(row)
    assert item is not None
    row_widget = recent_list.itemWidget(item)
    assert row_widget is not None

    file_btn = row_widget.findChild(QPushButton, "welcome_recent_file_btn")
    folder_lbl = row_widget.findChild(QLabel, "welcome_recent_path_lbl")
    remove_btn = row_widget.findChild(QToolButton, "welcome_recent_remove_btn")
    assert file_btn is not None
    assert folder_lbl is not None
    assert remove_btn is not None
    return file_btn, folder_lbl, remove_btn


@pytest.mark.gui
# Workflow: App startup should land on welcome screen with project UI disabled and no dataset loaded.
def test_launches_to_welcome_view(window):
    assert window.center_stack.currentIndex() == 0
    assert window.data_dock.isEnabled() is False
    assert window.editor_dock.isEnabled() is False
    assert window.model.json_loaded is False


@pytest.mark.gui
@pytest.mark.parametrize("mode", list(MODE_TO_TAB_INDEX.keys()))
# Workflow: For each mode, import a synthetic JSON via routed file dialog and verify mode/view/tree state.
def test_import_project_routed_flow_all_modes(window, monkeypatch, synthetic_project_json, mode):
    project_json_path = synthetic_project_json(mode)

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    window.router.import_annotations()

    assert window.model.json_loaded is True
    assert window.model.current_json_path == str(project_json_path)
    assert window.center_stack.currentIndex() == 1
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX[mode]
    assert window.tree_model.rowCount() == 1


@pytest.mark.gui
# Workflow: Create/load a project, trigger close flow, and verify full reset back to welcome view.
def test_close_project_returns_to_welcome(window, monkeypatch):
    window.dataset_explorer_controller.create_new_project("localization")
    assert window.model.json_loaded is True

    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    window.router.close_project()

    assert window.model.json_loaded is False
    assert window.center_stack.currentIndex() == 0
    assert window.tree_model.rowCount() == 0


@pytest.mark.gui
# Workflow: Import a dataset, return to welcome, and verify it appears in the recent projects list.
def test_recent_projects_list_updates_after_successful_import(window, monkeypatch, synthetic_project_json):
    window.router.remove_all_recent_project()
    project_json_path = synthetic_project_json("classification").resolve()

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    window.router.import_annotations()
    window.show_welcome_view()

    recents = window.router.get_recent_projects()
    assert recents == [str(project_json_path)]

    recent_list = window.welcome_widget.recent_projects_list
    assert recent_list.count() == 1
    file_btn, folder_lbl, _remove_btn = _get_recent_row_controls(window, 0)
    assert file_btn.text() == project_json_path.name
    assert folder_lbl.text() == str(project_json_path.parent)


@pytest.mark.gui
# Workflow: Click a recent project entry from welcome and verify dataset opens directly in workspace.
def test_recent_project_click_opens_dataset(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("classification").resolve()

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    window.router.import_annotations()
    window.router.close_project()
    assert window.center_stack.currentIndex() == 0

    file_btn, _folder_lbl, _remove_btn = _get_recent_row_controls(window, 0)
    qtbot.mouseClick(file_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    assert window.model.json_loaded is True
    assert Path(window.model.current_json_path).resolve() == project_json_path
    assert window.center_stack.currentIndex() == 1


@pytest.mark.gui
# Workflow: Add 6 unique opens, verify full deduped history is stored while UI-facing recents are newest-first top-5.
def test_recent_projects_dedupe_order_and_limit(window, monkeypatch, tmp_path, synthetic_project_json):
    window.router.remove_all_recent_project()
    MAX_RECENT_DATASETS_DISPLAY = window.router.get_max_recent_datasets_displayed()
    base_project = synthetic_project_json("classification")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    project_paths = []
    for idx in range(MAX_RECENT_DATASETS_DISPLAY+5):
        project_path = tmp_path / f"classification_project_{idx}.json"
        shutil.copyfile(base_project, project_path)
        project_paths.append(project_path.resolve())
        assert window.router.open_project_from_path(str(project_path)) is True

    stored_history = window.router.settings.value(window.router.RECENT_DATASETS_KEY, [])
    assert isinstance(stored_history, list)
    assert len(stored_history) == MAX_RECENT_DATASETS_DISPLAY + 5

    recents = window.router.get_recent_projects()
    assert len(recents) == MAX_RECENT_DATASETS_DISPLAY
    assert recents == [str(path) for path in reversed(project_paths[-10:])]

    reopened_path = project_paths[2]
    assert window.router.open_project_from_path(str(reopened_path)) is True
    recents_after_reopen = window.router.get_recent_projects()
    assert recents_after_reopen[0] == str(reopened_path)
    assert len(recents_after_reopen) == MAX_RECENT_DATASETS_DISPLAY
    assert recents_after_reopen.count(str(reopened_path)) == 1

    stored_history_after_reopen = window.router.settings.value(window.router.RECENT_DATASETS_KEY, [])
    assert isinstance(stored_history_after_reopen, list)
    assert len(stored_history_after_reopen) == MAX_RECENT_DATASETS_DISPLAY + 5


@pytest.mark.gui
# Workflow: Try to open an invalid JSON project and verify it is not added to recents.
def test_recent_projects_failed_open_does_not_add(window, monkeypatch, tmp_path):
    window.router.remove_all_recent_project()
    invalid_project = tmp_path / "invalid_project.json"
    invalid_project.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.router.QMessageBox.critical",
        lambda *args, **kwargs: QMessageBox.StandardButton.Ok,
    )

    loaded = window.router.open_project_from_path(str(invalid_project))
    assert loaded is False
    assert window.router.get_recent_projects() == []


@pytest.mark.gui
# Workflow: Click a missing recent path, verify warning appears, and ensure the stale entry is removed.
def test_recent_projects_missing_path_removed_on_click(window, monkeypatch, qtbot, tmp_path):
    window.router.remove_all_recent_project()
    missing_project = (tmp_path / "missing_project.json").resolve()
    window.router._add_recent_project(str(missing_project))
    window.welcome_controller.refresh_recent_projects()

    warning_calls = {"count": 0}
    monkeypatch.setattr(
        "controllers.router.QMessageBox.warning",
        lambda *args, **kwargs: warning_calls.__setitem__("count", warning_calls["count"] + 1)
        or QMessageBox.StandardButton.Ok,
    )

    recent_list = window.welcome_widget.recent_projects_list
    assert recent_list.count() == 1
    file_btn, _folder_lbl, _remove_btn = _get_recent_row_controls(window, 0)
    qtbot.mouseClick(file_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    assert warning_calls["count"] == 1
    assert window.router.get_recent_projects() == []
    assert recent_list.count() == 0


@pytest.mark.gui
# Workflow: Use the per-row remove button (×) and verify the recent entry is removed without attempting open.
def test_recent_projects_remove_button_removes_entry(window, monkeypatch, qtbot, synthetic_project_json):
    window.router.remove_all_recent_project()
    project_json_path = synthetic_project_json("classification").resolve()
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)
    window.router.import_annotations()
    window.router.close_project()
    assert window.welcome_widget.recent_projects_list.count() == 1

    open_calls = {"count": 0}
    monkeypatch.setattr(
        window.router,
        "open_project_from_path",
        lambda path: open_calls.__setitem__("count", open_calls["count"] + 1) or True,
    )

    _file_btn, _folder_lbl, remove_btn = _get_recent_row_controls(window, 0)
    qtbot.mouseClick(remove_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    assert open_calls["count"] == 0
    assert window.router.get_recent_projects() == []
    assert window.welcome_widget.recent_projects_list.count() == 0


@pytest.mark.gui
# Workflow: Import classification JSON, add one new video item, save, reopen, and confirm item persistence.
def test_add_data_save_and_reopen_keeps_new_item(window, monkeypatch, qtbot, synthetic_project_json):
    # Start from a small imported classification project (1 item).
    project_json_path = synthetic_project_json("classification")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.tree_model.rowCount() == 1

    # Add one more clip through the Dataset Explorer Add Data button.
    repo_root = Path(__file__).resolve().parents[2]
    gymnastics_video = repo_root / "tests" / "data" / "test_video_2.mp4"
    assert gymnastics_video.exists(), f"Missing test asset: {gymnastics_video}"

    monkeypatch.setattr(
        "controllers.common.dataset_explorer_controller.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(gymnastics_video)], "Media Files (*.mp4)"),
    )
    qtbot.mouseClick(window.dataset_explorer_panel.btn_add_data, Qt.MouseButton.LeftButton)

    assert window.tree_model.rowCount() == 2
    added_paths = {entry.get("path") for entry in window.model.action_item_data}
    assert str(gymnastics_video) in added_paths

    # Save the project JSON.
    window.dataset_explorer_controller.save_project()
    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_input_paths = [
        inp.get("path", "")
        for item in saved.get("data", [])
        for inp in item.get("inputs", [])
    ]
    assert any(path.endswith("test_video_2.mp4") for path in saved_input_paths)

    # Reopen and verify the item still exists in UI/model.
    window.router.close_project()
    assert window.tree_model.rowCount() == 0

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    assert window.tree_model.rowCount() == 2
    reloaded_names = {entry.get("name") for entry in window.model.action_item_data}
    assert "test_video_2.mp4" in reloaded_names


@pytest.mark.gui
# Workflow: Classification annotation round-trip with edit:
# 1) annotate + save + reopen (label persists), then 2) modify label + save + reopen (new label persists).
def test_classification_annotate_save_reload_edit_labels_and_persist(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    # 1) Open classification JSON.
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["classification"]
    assert window.tree_model.rowCount() == 1

    # 2) Select the first data item in the list.
    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    first_path = window.get_current_action_path()
    assert first_path is not None

    # 3) Annotate with a hand label.
    panel = window.classification_panel
    panel.tabs.setCurrentIndex(0)
    assert "action" in panel.label_groups
    action_group = panel.label_groups["action"]
    pass_btn = next(btn for btn in action_group.radio_group.buttons() if btn.text() == "pass")
    qtbot.mouseClick(pass_btn, Qt.MouseButton.LeftButton)
    assert panel.get_annotation().get("action") == "pass"

    # Confirm annotation via UI button and verify in-memory model state.
    qtbot.mouseClick(panel.confirm_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert window.model.manual_annotations[first_path]["action"] == "pass"

    # 4) Save JSON and verify label is written.
    window.dataset_explorer_controller.save_project()
    saved_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry = next(item for item in saved_data.get("data", []) if item.get("id") == "clip_1")
    assert saved_entry["labels"]["action"]["label"] == "pass"

    # 5) Close dataset.
    window.router.close_project()
    assert window.model.json_loaded is False
    assert window.center_stack.currentIndex() == 0

    # 6) Reopen and verify label persistence in model and UI.
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    reopened_index = window.tree_model.index(0, 0)
    assert reopened_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(reopened_index)
    qtbot.wait(50)

    reopened_path = window.get_current_action_path()
    assert reopened_path is not None
    assert window.model.manual_annotations[reopened_path]["action"] == "pass"
    assert window.classification_panel.get_annotation().get("action") == "pass"

    # 7) Edit the label after reload, save again, and verify persistence again.
    reopened_panel = window.classification_panel
    reopened_panel.tabs.setCurrentIndex(0)
    reopened_group = reopened_panel.label_groups["action"]
    shot_btn = next(btn for btn in reopened_group.radio_group.buttons() if btn.text() == "shot")
    qtbot.mouseClick(shot_btn, Qt.MouseButton.LeftButton)
    assert reopened_panel.get_annotation().get("action") == "shot"

    qtbot.mouseClick(reopened_panel.confirm_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert window.model.manual_annotations[reopened_path]["action"] == "shot"

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry_after_edit = next(item for item in saved_data_after_edit.get("data", []) if item.get("id") == "clip_1")
    assert saved_entry_after_edit["labels"]["action"]["label"] == "shot"

    window.router.close_project()
    assert window.model.json_loaded is False
    assert window.center_stack.currentIndex() == 0

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    final_index = window.tree_model.index(0, 0)
    assert final_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(final_index)
    qtbot.wait(50)

    final_path = window.get_current_action_path()
    assert final_path is not None
    assert window.model.manual_annotations[final_path]["action"] == "shot"
    assert window.classification_panel.get_annotation().get("action") == "shot"


@pytest.mark.gui
# Workflow: Localization annotation round-trip with timestamp edit:
# 1) create event(label+time) + save + reopen, then 2) change time + save + reopen and verify final timestamp.
def test_localization_annotate_save_reload_edit_time_and_persist(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    # 1) Open localization JSON.
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["localization"]
    assert window.tree_model.rowCount() == 1

    # 2) Select first data item.
    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    video_path = window.get_current_action_path()
    assert video_path is not None

    # 3) Annotate with label, then set timestamp.
    window.loc_manager._on_spotting_triggered("ball_action", "shot")
    events = window.model.localization_events.get(video_path, [])
    assert any(e.get("label") == "shot" for e in events)

    old_event = next(e for e in events if e.get("label") == "shot")
    new_event = old_event.copy()
    new_event["position_ms"] = 2345
    window.loc_manager._on_annotation_modified(old_event, new_event)

    events_after_add = window.model.localization_events.get(video_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 2345 for e in events_after_add)
    table_events = [
        window.localization_panel.table.model.get_annotation_at(i)
        for i in range(window.localization_panel.table.model.rowCount())
    ]
    assert any(e and e.get("label") == "shot" and e.get("position_ms") == 2345 for e in table_events)

    # 4) Save + close + reopen and verify event persistence.
    window.dataset_explorer_controller.save_project()
    saved_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_events = saved_data.get("data", [])[0].get("events", [])
    assert any(e.get("label") == "shot" and str(e.get("position_ms")) == "2345" for e in saved_events)

    window.router.close_project()
    assert window.model.json_loaded is False

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    reopened_index = window.tree_model.index(0, 0)
    assert reopened_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(reopened_index)
    qtbot.wait(50)

    reopened_path = window.get_current_action_path()
    assert reopened_path is not None
    reopened_events = window.model.localization_events.get(reopened_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 2345 for e in reopened_events)

    # 5) Edit timestamp, save again, reload again, and verify changed time persists.
    old_event_after_reload = next(
        e for e in reopened_events if e.get("label") == "shot" and e.get("position_ms") == 2345
    )
    edited_event = old_event_after_reload.copy()
    edited_event["position_ms"] = 3456
    window.loc_manager._on_annotation_modified(old_event_after_reload, edited_event)

    edited_events = window.model.localization_events.get(reopened_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 3456 for e in edited_events)

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_events_after_edit = saved_data_after_edit.get("data", [])[0].get("events", [])
    assert any(e.get("label") == "shot" and str(e.get("position_ms")) == "3456" for e in saved_events_after_edit)

    window.router.close_project()
    assert window.model.json_loaded is False

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    final_index = window.tree_model.index(0, 0)
    assert final_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(final_index)
    qtbot.wait(50)

    final_path = window.get_current_action_path()
    assert final_path is not None
    final_events = window.model.localization_events.get(final_path, [])
    assert any(e.get("label") == "shot" and e.get("position_ms") == 3456 for e in final_events)


@pytest.mark.gui
# Workflow: Description annotation round-trip with edit:
# 1) update caption text + save + reopen, then 2) edit caption again + save + reopen and verify final text.
def test_description_annotate_save_reload_edit_and_persist(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("description")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    # 1) Open description JSON and select first item.
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    first_path = window.get_current_action_path()
    assert first_path is not None

    # 2) Write first caption text and confirm.
    first_text = "Description v1 from GUI test."
    window.description_panel.caption_edit.setPlainText(first_text)
    qtbot.mouseClick(window.description_panel.confirm_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    target_item = next(
        item
        for item in window.model.action_item_data
        if item.get("metadata", {}).get("path") == first_path
    )
    assert target_item["captions"][0]["text"] == first_text

    # 3) Save + close + reopen and verify first text persisted.
    window.dataset_explorer_controller.save_project()
    saved_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry = saved_data.get("data", [])[0]
    assert saved_entry["captions"][0]["text"] == first_text

    window.router.close_project()
    assert window.model.json_loaded is False

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    reopened_index = window.tree_model.index(0, 0)
    assert reopened_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(reopened_index)
    qtbot.wait(50)
    assert window.description_panel.caption_edit.toPlainText().strip() == first_text

    # 4) Edit caption again, save, reload, and verify edited text persisted.
    second_text = "Description v2 edited after reload."
    window.description_panel.caption_edit.setPlainText(second_text)
    qtbot.mouseClick(window.description_panel.confirm_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry_after_edit = saved_data_after_edit.get("data", [])[0]
    assert saved_entry_after_edit["captions"][0]["text"] == second_text

    window.router.close_project()
    assert window.model.json_loaded is False

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    final_index = window.tree_model.index(0, 0)
    assert final_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(final_index)
    qtbot.wait(50)
    assert window.description_panel.caption_edit.toPlainText().strip() == second_text


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
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    # 1) Open dense description JSON and select first item.
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
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
    window.dense_manager._on_annotation_modified(old_event, first_edit)

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
        "controllers.router.QFileDialog.getOpenFileName",
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
    window.dense_manager._on_annotation_modified(old_event_after_reload, second_edit)

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
        "controllers.router.QFileDialog.getOpenFileName",
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
