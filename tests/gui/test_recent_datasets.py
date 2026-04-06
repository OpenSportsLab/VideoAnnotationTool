"""
Recent datasets GUI behavior tests.
"""

import json
import shutil
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QMessageBox, QPushButton, QToolButton


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
# Workflow: Add 6+ unique opens, verify full deduped history is stored while UI-facing recents are newest-first top-N.
def test_recent_projects_dedupe_order_and_limit(window, monkeypatch, tmp_path, synthetic_project_json):
    window.router.remove_all_recent_project()
    max_recent_display = window.router.get_max_recent_datasets_displayed()
    base_project = synthetic_project_json("classification")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    project_paths = []
    for idx in range(max_recent_display + 5):
        project_path = tmp_path / f"classification_project_{idx}.json"
        shutil.copyfile(base_project, project_path)
        project_paths.append(project_path.resolve())
        assert window.router.open_project_from_path(str(project_path)) is True

    stored_history = window.router.settings.value(window.router.RECENT_DATASETS_KEY, [])
    assert isinstance(stored_history, list)
    assert len(stored_history) == max_recent_display + 5

    recents = window.router.get_recent_projects()
    assert len(recents) == max_recent_display
    assert recents == [str(path) for path in reversed(project_paths[-10:])]

    reopened_path = project_paths[2]
    assert window.router.open_project_from_path(str(reopened_path)) is True
    recents_after_reopen = window.router.get_recent_projects()
    assert recents_after_reopen[0] == str(reopened_path)
    assert len(recents_after_reopen) == max_recent_display
    assert recents_after_reopen.count(str(reopened_path)) == 1

    stored_history_after_reopen = window.router.settings.value(window.router.RECENT_DATASETS_KEY, [])
    assert isinstance(stored_history_after_reopen, list)
    assert len(stored_history_after_reopen) == max_recent_display + 5


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
