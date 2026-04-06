"""
Dataset list editing workflow tests.
"""

import json
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt


@pytest.mark.gui
# Workflow: Import classification JSON, add five new video items, save/reopen and verify persistence;
# then remove one item, save/reopen, and verify deletion persistence.
def test_add_five_items_remove_one_save_and_reopen_persists_changes(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
    tmp_path,
):
    # Start from a small imported classification project (1 item).
    project_json_path = synthetic_project_json("classification")
    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()
    assert window.tree_model.rowCount() == 1

    # Add five more clips through the Dataset Explorer Add Data button.
    repo_root = Path(__file__).resolve().parents[2]
    source_video = repo_root / "tests" / "data" / "test_video_2.mp4"
    assert source_video.exists(), f"Missing test asset: {source_video}"

    source_bytes = source_video.read_bytes()
    added_video_paths = []
    for i in range(5):
        added_video = tmp_path / f"added_video_{i + 1}.mp4"
        added_video.write_bytes(source_bytes)
        added_video_paths.append(added_video)

    monkeypatch.setattr(
        "controllers.classification.classification_editor_controller.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(path) for path in added_video_paths], "Media Files (*.mp4)"),
    )
    qtbot.mouseClick(window.dataset_explorer_panel.btn_add_data, Qt.MouseButton.LeftButton)
    qtbot.wait(50)

    assert window.tree_model.rowCount() == 6
    added_paths = {entry.get("path") for entry in window.model.action_item_data}
    for added_video in added_video_paths:
        assert str(added_video) in added_paths

    # Save the project JSON and verify all five added items are written.
    window.dataset_explorer_controller.save_project()
    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_input_paths = [
        inp.get("path", "")
        for item in saved.get("data", [])
        for inp in item.get("inputs", [])
    ]
    for added_video in added_video_paths:
        assert any(path.endswith(added_video.name) for path in saved_input_paths)

    # Reopen and verify all added items still exist in UI/model.
    window.router.close_project()
    assert window.tree_model.rowCount() == 0

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    assert window.tree_model.rowCount() == 6
    reloaded_names = {entry.get("name") for entry in window.model.action_item_data}
    for added_video in added_video_paths:
        assert added_video.name in reloaded_names

    # Remove one of the added items and verify immediate state update.
    target_removed_name = added_video_paths[0].name
    remove_index = None
    for row in range(window.tree_model.rowCount()):
        idx = window.tree_model.index(row, 0)
        row_path = idx.data(window.tree_model.FilePathRole)
        if Path(str(row_path)).name == target_removed_name:
            remove_index = idx
            break

    assert remove_index is not None
    window.dataset_explorer_panel.tree.setCurrentIndex(remove_index)
    qtbot.wait(50)
    window.dataset_explorer_controller.handle_remove_item(remove_index)
    qtbot.wait(50)

    assert window.tree_model.rowCount() == 5
    names_after_remove = {entry.get("name") for entry in window.model.action_item_data}
    assert target_removed_name not in names_after_remove
    for remaining_video in added_video_paths[1:]:
        assert remaining_video.name in names_after_remove

    # Save after removal and verify JSON no longer contains removed item.
    window.dataset_explorer_controller.save_project()
    saved_after_remove = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_paths_after_remove = [
        inp.get("path", "")
        for item in saved_after_remove.get("data", [])
        for inp in item.get("inputs", [])
    ]
    assert not any(path.endswith(target_removed_name) for path in saved_paths_after_remove)
    for remaining_video in added_video_paths[1:]:
        assert any(path.endswith(remaining_video.name) for path in saved_paths_after_remove)

    # Reopen once more and confirm deletion persistence.
    window.router.close_project()
    assert window.tree_model.rowCount() == 0

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    assert window.tree_model.rowCount() == 5
    final_names = {entry.get("name") for entry in window.model.action_item_data}
    assert target_removed_name not in final_names
    for remaining_video in added_video_paths[1:]:
        assert remaining_video.name in final_names
