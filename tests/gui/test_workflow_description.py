"""
Description mode workflows.
"""

import json
import os
from pathlib import Path

import pytest
from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtWidgets import QMessageBox


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
    "question_answer": 4,
}


@pytest.mark.gui
# Workflow: In Description mode, selecting a tree item should load media and refresh editor text.
def test_description_selection_loads_media_and_refreshes_editor(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("description")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    qtbot.wait(50)
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()

    load_calls = []
    monkeypatch.setattr(
        window.media_controller,
        "route_media_group",
        lambda sources, focused_path, ensure_playback=False: load_calls.append(
            (sources, focused_path, ensure_playback)
        ),
    )

    # Force a real selection transition: invalid -> first item.
    window.dataset_explorer_panel.tree.setCurrentIndex(QModelIndex())
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert len(load_calls) == 1
    assert load_calls[0][1] == ""
    assert Path(load_calls[0][0][0]["path"]).name == "test_video_1.mp4"
    assert window.description_panel.caption_edit.toPlainText().strip() == "A short test caption."


@pytest.mark.gui
def test_description_multi_caption_list_edits_and_round_trips(
    window,
    monkeypatch,
    qtbot,
    tmp_path,
):
    project_json_path = tmp_path / "multi_caption_project.json"
    project_json_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "task": "video_captioning",
                "dataset_name": "multi_caption",
                "data": [
                    {
                        "id": "clip_1",
                        "inputs": [{"path": "clip.mp4", "type": "video"}],
                        "captions": [
                            {
                                "lang": "en",
                                "text": "Automatic caption",
                                "variant": "auto",
                                "source": "model-a",
                            },
                            {
                                "lang": "en",
                                "text": "Clean caption",
                                "variant": "clean",
                                "reviewed": True,
                            },
                            {"lang": "en", "text": "Refined caption", "variant": "refined"},
                        ],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        window.media_controller, "route_media_group", lambda *args, **kwargs: None
    )
    assert window.dataset_explorer_controller.open_project_from_path(str(project_json_path))
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    qtbot.wait(50)

    panel = window.description_panel
    assert panel.descCaptionsList.count() == 3
    assert "auto" in panel.descCaptionsList.item(0).text()
    assert "clean" in panel.descCaptionsList.item(1).text()
    assert panel.descVariantEdit.text() == "auto"
    assert panel.descLanguageEdit.text() == "en"
    assert panel.caption_edit.toPlainText() == "Automatic caption"

    panel.descCaptionsList.setCurrentRow(1)
    panel.descVariantEdit.setText("edited-clean")
    panel.descLanguageEdit.setText("fr")
    panel.caption_edit.setPlainText("Edited clean caption")
    qtbot.wait(350)

    captions = window.dataset_explorer_controller.dataset_json["data"][0]["captions"]
    assert [caption["variant"] for caption in captions] == ["auto", "edited-clean", "refined"]
    assert captions[1]["lang"] == "fr"
    assert captions[1]["text"] == "Edited clean caption"
    assert captions[1]["reviewed"] is True
    assert captions[0]["source"] == "model-a"

    window.dataset_explorer_controller.save_project()
    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    assert saved["data"][0]["captions"] == captions

    window.dataset_explorer_controller.close_project()
    assert window.dataset_explorer_controller.open_project_from_path(str(project_json_path))
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    qtbot.wait(50)
    window.description_panel.descCaptionsList.setCurrentRow(1)
    assert window.description_panel.descVariantEdit.text() == "edited-clean"
    assert window.description_panel.descLanguageEdit.text() == "fr"
    assert window.description_panel.caption_edit.toPlainText() == "Edited clean caption"


@pytest.mark.gui
def test_description_caption_add_delete_and_selection_flush(
    window, monkeypatch, qtbot, synthetic_project_json
):
    project_json_path = synthetic_project_json("description", item_count=2)
    monkeypatch.setattr(
        window.dataset_explorer_controller,
        "check_and_close_current_project",
        lambda: True,
    )
    monkeypatch.setattr(
        window.media_controller, "route_media_group", lambda *args, **kwargs: None
    )
    assert window.dataset_explorer_controller.open_project_from_path(str(project_json_path))
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    qtbot.wait(50)

    panel = window.description_panel
    controller = window.desc_editor_controller
    undo_before = len(window.dataset_explorer_controller.undo_stack)
    controller.add_caption()
    assert panel.descCaptionsList.count() == 2
    assert panel.get_selected_caption_index() == 1
    assert len(window.dataset_explorer_controller.undo_stack) == undo_before + 1

    panel.caption_edit.setPlainText("Second caption")
    panel.descCaptionsList.setCurrentRow(0)
    captions = window.dataset_explorer_controller.dataset_json["data"][0]["captions"]
    assert captions[1] == {"lang": "en", "text": "Second caption"}

    panel.descCaptionsList.setCurrentRow(1)
    undo_before = len(window.dataset_explorer_controller.undo_stack)
    controller.delete_selected_caption()
    assert panel.descCaptionsList.count() == 1
    assert len(window.dataset_explorer_controller.undo_stack) == undo_before + 1

    panel.caption_edit.setPlainText("Flushed before sample switch")
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(1, 0))
    first_sample = window.dataset_explorer_controller.dataset_json["data"][0]
    assert first_sample["captions"][0]["text"] == "Flushed before sample switch"


@pytest.mark.gui
def test_description_delete_final_caption_clears_detail_editor(
    window, monkeypatch, qtbot, synthetic_project_json
):
    project_json_path = synthetic_project_json("description")
    monkeypatch.setattr(
        window.media_controller, "route_media_group", lambda *args, **kwargs: None
    )
    assert window.dataset_explorer_controller.open_project_from_path(str(project_json_path))
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    qtbot.wait(50)

    assert window.desc_editor_controller.delete_selected_caption() is True
    panel = window.description_panel
    assert panel.descCaptionsList.count() == 0
    assert panel.get_selected_caption_index() == -1
    assert panel.caption_edit.toPlainText() == ""
    assert panel.captionDetailWidget.isEnabled() is False
    assert "captions" not in window.dataset_explorer_controller.dataset_json["data"][0]


@pytest.mark.gui
# Workflow: Selecting a multiview parent routes the full media group while
# leaving input focus clear.
def test_description_multiview_parent_selection_loads_group_without_input_focus(
    window,
    monkeypatch,
    qtbot,
    tmp_path,
):
    repo_root = Path(__file__).resolve().parents[2]
    source_video = repo_root / "tests" / "data" / "test_video_1.mp4"
    assert source_video.exists(), f"Missing test asset: {source_video}"

    scene_dir = tmp_path / "scene_001"
    scene_dir.mkdir()
    view_a = scene_dir / "view_1.mp4"
    view_b = scene_dir / "view_2.mp4"
    video_bytes = source_video.read_bytes()
    view_a.write_bytes(video_bytes)
    view_b.write_bytes(video_bytes)

    rel_parent = os.path.relpath(scene_dir, start=tmp_path).replace("\\", "/")
    rel_view_a = os.path.relpath(view_a, start=tmp_path).replace("\\", "/")
    rel_view_b = os.path.relpath(view_b, start=tmp_path).replace("\\", "/")

    project_json_path = tmp_path / "description_multiview_project.json"
    project_json_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "date": "2026-04-07",
                "task": "video_captioning",
                "dataset_name": "synthetic_description_multiview",
                "metadata": {"source": "pytest-qt"},
                "data": [
                    {
                        "id": "scene_001",
                        "inputs": [
                            {"path": rel_view_a, "type": "video", "fps": 25.0},
                            {"path": rel_view_b, "type": "video", "fps": 25.0},
                        ],
                        "captions": [{"lang": "en", "text": "Scene-level caption."}],
                        "metadata": {"path": rel_parent},
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    load_calls = []
    monkeypatch.setattr(
        window.media_controller,
        "route_media_group",
        lambda sources, focused_path, ensure_playback=False: load_calls.append(
            (sources, focused_path, ensure_playback)
        ),
    )

    window.dataset_explorer_controller.import_annotations()
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    qtbot.wait(50)
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
    assert window.tree_model.rowCount() == 1

    parent_index = window.tree_model.index(0, 0)
    assert parent_index.isValid()
    assert window.tree_model.rowCount(parent_index) == 2

    window.dataset_explorer_panel.tree.setCurrentIndex(QModelIndex())
    window.dataset_explorer_panel.tree.setCurrentIndex(parent_index)
    qtbot.wait(50)

    assert load_calls
    assert load_calls[-1][1] == ""
    assert Path(load_calls[-1][0][0]["path"]).resolve() == view_a.resolve()
    assert {Path(source["path"]).resolve() for source in load_calls[-1][0]} == {
        view_a.resolve(),
        view_b.resolve(),
    }
    assert window.description_panel.caption_edit.toPlainText().strip() == "Scene-level caption."


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
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    # 1) Open description JSON and select first item.
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    qtbot.wait(50)
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    first_path = window.get_current_action_path()
    assert first_path is not None

    # 2) Write first caption text and wait for autosave.
    first_text = "Description v1 from GUI test."
    window.description_panel.caption_edit.setPlainText(first_text)
    qtbot.wait(350)

    target_item = next(
        item
        for item in window.dataset_explorer_controller.action_item_data
        if item.get("path") == first_path
    )
    assert target_item["captions"][0]["text"] == first_text

    # 3) Save + close + reopen and verify first text persisted.
    window.dataset_explorer_controller.save_project()
    saved_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry = saved_data.get("data", [])[0]
    assert saved_entry["captions"][0]["text"] == first_text

    window.dataset_explorer_controller.close_project()
    assert window.dataset_explorer_controller.json_loaded is False

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    reopened_index = window.tree_model.index(0, 0)
    assert reopened_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(reopened_index)
    qtbot.wait(50)
    assert window.description_panel.caption_edit.toPlainText().strip() == first_text

    # 4) Edit caption again, save, reload, and verify edited text persisted.
    second_text = "Description v2 edited after reload."
    window.description_panel.caption_edit.setPlainText(second_text)
    qtbot.wait(350)

    window.dataset_explorer_controller.save_project()
    saved_data_after_edit = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_entry_after_edit = saved_data_after_edit.get("data", [])[0]
    assert saved_entry_after_edit["captions"][0]["text"] == second_text

    window.dataset_explorer_controller.close_project()
    assert window.dataset_explorer_controller.json_loaded is False

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    final_index = window.tree_model.index(0, 0)
    assert final_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(final_index)
    qtbot.wait(50)
    assert window.description_panel.caption_edit.toPlainText().strip() == second_text


@pytest.mark.gui
# Workflow: In Description mode, removing the currently selected item should clear/disable editor state.
def test_description_remove_selected_item_clears_editor_state(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("description")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    qtbot.wait(50)
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
    assert window.tree_model.rowCount() == 1

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert window.description_panel.caption_edit.isEnabled() is True
    assert window.desc_editor_controller.current_action_path is not None

    # Simulate user confirming the remove action.
    # For some reason, testing get stuck there, so we patch QMessageBox.exec to auto-confirm.
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QMessageBox.exec",
        lambda self: QMessageBox.StandardButton.Yes,
    )
    window.dataset_explorer_controller.handle_remove_item(first_index)
    qtbot.wait(50)
    
    assert window.tree_model.rowCount() == 0
    assert window.dataset_explorer_controller.action_item_data == []
    assert window.desc_editor_controller.current_action_path is None
    assert window.description_panel.caption_edit.toPlainText() == ""
    assert window.description_panel.caption_edit.isEnabled() is False


@pytest.mark.gui
# Workflow: In Description mode, clearing workspace from Dataset Explorer should reset model/tree/editor state.
def test_description_clear_workspace_resets_editor_and_model(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("description")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    window.dataset_explorer_panel.tree.setCurrentIndex(window.tree_model.index(0, 0))
    qtbot.wait(50)
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
    assert window.tree_model.rowCount() == 1
    assert window.dataset_explorer_controller.json_loaded is True

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

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
    assert window.dataset_explorer_controller.json_loaded is True
    assert window.dataset_explorer_controller.current_json_path == str(project_json_path)
    assert window.dataset_explorer_controller.action_item_data == []
    assert window.dataset_explorer_controller.desc_global_metadata != {}
    assert window.desc_editor_controller.current_action_path is None
    assert window.description_panel.caption_edit.toPlainText() == ""
    assert window.description_panel.caption_edit.isEnabled() is False


# @pytest.mark.gui
# # Workflow: With multiple description items, editing one caption then switching selection should preserve each item's text.
# def test_description_switch_selection_preserves_text_per_item(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("description", item_count=2)
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )
#     window.dataset_explorer_controller.import_annotations()
#     assert window.tree_model.rowCount() == 2

#     first_index = window.tree_model.index(0, 0)
#     second_index = window.tree_model.index(1, 0)
#     assert first_index.isValid() and second_index.isValid()

#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)
#     edited_first_text = "Edited caption for first clip."
#     window.description_panel.caption_edit.setPlainText(edited_first_text)
#     qtbot.mouseClick(window.description_panel.confirm_btn, Qt.MouseButton.LeftButton)
#     qtbot.wait(50)

#     window.dataset_explorer_panel.tree.setCurrentIndex(second_index)
#     qtbot.wait(50)
#     second_text = window.description_panel.caption_edit.toPlainText().strip()
#     assert second_text == "A short test caption 2."

#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)
#     assert window.description_panel.caption_edit.toPlainText().strip() == edited_first_text


# @pytest.mark.gui
# # Workflow: In Description mode, undo/redo should refresh text only and must not trigger media reload.
# def test_description_undo_redo_refreshes_text_without_media_reload(
#     window,
#     monkeypatch,
#     qtbot,
#     synthetic_project_json,
# ):
#     project_json_path = synthetic_project_json("description")
#     monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
#         lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
#     )
#     window.dataset_explorer_controller.import_annotations()
#     assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]
#     assert window.tree_model.rowCount() == 1

#     first_index = window.tree_model.index(0, 0)
#     assert first_index.isValid()
#     window.dataset_explorer_panel.tree.setCurrentIndex(QModelIndex())
#     window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
#     qtbot.wait(50)

#     edited_text = "Description text edited before undo."
#     window.description_panel.caption_edit.setPlainText(edited_text)
#     qtbot.mouseClick(window.description_panel.confirm_btn, Qt.MouseButton.LeftButton)
#     qtbot.wait(50)
#     assert window.description_panel.caption_edit.toPlainText().strip() == edited_text

#     load_calls = []
#     monkeypatch.setattr(
#         window.media_controller,
#         "load_and_play",
#         lambda file_path, auto_play=True: load_calls.append(file_path),
#     )

#     window.history_manager.perform_undo()
#     qtbot.wait(50)
#     assert window.description_panel.caption_edit.toPlainText().strip() == "A short test caption."
#     assert load_calls == []

#     window.history_manager.perform_redo()
#     qtbot.wait(50)
#     assert window.description_panel.caption_edit.toPlainText().strip() == edited_text
#     assert load_calls == []
