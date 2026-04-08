"""
Dataset Explorer regression coverage across mixed datasets and cross-mode flows.
"""

import json
import os
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from controllers.command_types import CmdType


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
}


def _open_project(window, monkeypatch, project_json_path: Path):
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()


def _select_top_row(window, qtbot, row: int = 0):
    index = window.tree_model.index(row, 0)
    assert index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(index)
    qtbot.wait(50)
    return index


def _set_known_header_value(panel, key: str, value: str):
    for row in range(panel.table_header_known.rowCount()):
        key_item = panel.table_header_known.item(row, 0)
        if key_item and key_item.text() == key:
            value_item = panel.table_header_known.item(row, 1)
            assert value_item is not None
            value_item.setText(value)
            return
    raise AssertionError(f"Known header row not found: {key}")


def _recent_file_button_text(window, row: int = 0) -> str:
    recent_list = window.welcome_widget.recent_projects_list
    item = recent_list.item(row)
    assert item is not None
    row_widget = recent_list.itemWidget(item)
    assert row_widget is not None
    file_btn = row_widget.findChild(type(window.welcome_widget.import_btn), "welcome_recent_file_btn")
    assert file_btn is not None
    return file_btn.text()


@pytest.mark.gui
def test_mixed_dataset_switch_tabs_save_reopen_preserves_all_annotation_blocks(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=2)
    _open_project(window, monkeypatch, project_json_path)

    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["classification"]
    assert window.tree_model.rowCount() == 2

    _select_top_row(window, qtbot, 0)
    selected_id = window.model.current_selected_sample_id
    assert selected_id == "clip_1"

    for mode_idx in (
        MODE_TO_TAB_INDEX["classification"],
        MODE_TO_TAB_INDEX["localization"],
        MODE_TO_TAB_INDEX["description"],
        MODE_TO_TAB_INDEX["dense_description"],
    ):
        window.right_tabs.setCurrentIndex(mode_idx)
        qtbot.wait(50)
        assert window.model.current_selected_sample_id == selected_id
        assert window.dataset_explorer_panel.tree.currentIndex().isValid()

    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["description"])
    window.dataset_explorer_controller.save_project()

    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_sample = next(item for item in saved["data"] if item["id"] == "clip_1")
    assert saved["custom_root"] == {"keep": True}
    assert saved_sample["custom_sample"] == {"keep": True, "index": 1}
    assert saved_sample["labels"]["action"]["label"] == "pass"
    assert saved_sample["smart_labels"]["_confirmed"] is True
    assert saved_sample["events"][0]["position_ms"] == 1000
    assert saved_sample["smart_events"][0]["position_ms"] == 2000
    assert saved_sample["captions"][0]["text"] == "Mixed caption"
    assert saved_sample["dense_captions"][0]["text"] == "Mixed dense caption"

    window.router.close_project()
    _open_project(window, monkeypatch, project_json_path)

    reloaded_sample = window.model.get_sample("clip_1")
    assert reloaded_sample is not None
    assert reloaded_sample["labels"]["action"]["label"] == "pass"
    assert reloaded_sample["smart_labels"]["_confirmed"] is True
    assert reloaded_sample["events"][0]["position_ms"] == 1000
    assert reloaded_sample["smart_events"][0]["position_ms"] == 2000
    assert reloaded_sample["captions"][0]["text"] == "Mixed caption"
    assert reloaded_sample["dense_captions"][0]["text"] == "Mixed dense caption"
    assert window.model.dataset_json["custom_root"] == {"keep": True}


@pytest.mark.gui
def test_single_input_samples_render_as_parent_with_one_child(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("classification")
    _open_project(window, monkeypatch, project_json_path)

    parent_index = _select_top_row(window, qtbot, 0)
    assert parent_index.isValid()
    assert window.tree_model.rowCount(parent_index) == 1

    child_index = window.tree_model.index(0, 0, parent_index)
    assert child_index.isValid()
    assert child_index.data(window.tree_model.DataIdRole) == parent_index.data(window.tree_model.DataIdRole)
    assert child_index.data(window.tree_model.FilePathRole) == parent_index.data(window.tree_model.FilePathRole)


@pytest.mark.gui
def test_legacy_task_header_is_preserved_but_does_not_route_initial_tab(
    window,
    monkeypatch,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=1)
    _open_project(window, monkeypatch, project_json_path)

    assert window.model.dataset_json.get("task") == "video_captioning"
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["classification"]

    panel = window.dataset_explorer_panel
    unknown_rows = {}
    for row in range(panel.table_header_unknown.rowCount()):
        key_item = panel.table_header_unknown.item(row, 0)
        value_item = panel.table_header_unknown.item(row, 1)
        if key_item and value_item:
            unknown_rows[key_item.text()] = value_item.text()

    assert unknown_rows.get("task") == "video_captioning"
    raw_json = json.loads(panel.json_raw_text.toPlainText())
    assert raw_json.get("task") == "video_captioning"


@pytest.mark.gui
def test_selection_switches_to_first_available_tab_when_current_is_not_supported(
    window,
    monkeypatch,
    qtbot,
    tmp_path,
):
    source_a = Path(__file__).resolve().parents[1] / "data" / "test_video_1.mp4"
    source_b = Path(__file__).resolve().parents[1] / "data" / "test_video_2.mp4"
    rel_a = os.path.relpath(source_a, start=tmp_path).replace("\\", "/")
    rel_b = os.path.relpath(source_b, start=tmp_path).replace("\\", "/")

    payload = {
        "version": "2.0",
        "date": "2026-04-08",
        "task": "action_classification",
        "dataset_name": "mode_fallback",
        "modalities": ["video"],
        "labels": {"action": {"type": "single_label", "labels": ["pass", "shot"]}},
        "data": [
            {
                "id": "desc_only",
                "inputs": [{"path": rel_a, "type": "video"}],
                "captions": [{"lang": "en", "text": "description text"}],
            },
            {
                "id": "loc_only",
                "inputs": [{"path": rel_b, "type": "video"}],
                "events": [{"head": "action", "label": "pass", "position_ms": 1000}],
            },
        ],
    }
    project_json_path = tmp_path / "mode_fallback.json"
    project_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    _open_project(window, monkeypatch, project_json_path)
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]

    second_index = window.tree_model.index(1, 0)
    assert second_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(second_index)
    qtbot.wait(50)
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["localization"]

    first_index = window.tree_model.index(0, 0)
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]


@pytest.mark.gui
def test_multiview_child_selection_keeps_sample_id_and_switches_preferred_media_path(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("multiview")
    _open_project(window, monkeypatch, project_json_path)

    play_calls = []
    monkeypatch.setattr(
        window.media_controller,
        "load_and_play",
        lambda file_path, auto_play=True: play_calls.append(file_path),
    )

    parent_index = _select_top_row(window, qtbot, 0)
    assert window.tree_model.rowCount(parent_index) == 2

    parent_sample_id = window.model.current_selected_sample_id
    parent_action_path = window.get_current_action_path()
    first_selected_path = window.model.current_selected_input_path
    child_index = window.tree_model.index(1, 0, parent_index)
    child_path = child_index.data(window.tree_model.FilePathRole)

    assert parent_sample_id == "mv_clip"
    assert parent_action_path == parent_index.data(window.tree_model.FilePathRole)
    assert first_selected_path in window.model.get_sources_by_id(parent_sample_id)

    window.dataset_explorer_panel.tree.setCurrentIndex(child_index)
    qtbot.wait(50)

    assert window.model.current_selected_sample_id == parent_sample_id
    assert window.model.current_selected_input_path == child_path
    assert window.get_current_action_path() == parent_action_path
    assert play_calls[-1] == child_path
    assert len(window.model.action_item_data) == 1


@pytest.mark.gui
@pytest.mark.parametrize(
    ("fixture_mode", "expected_ids"),
    [
        ("duplicate_id", ["clip_dup", "clip_dup__2"]),
        ("missing_id", ["sample_1", "sample_2"]),
    ],
)
def test_id_normalization_roundtrips_for_duplicate_and_missing_ids(
    window,
    monkeypatch,
    synthetic_project_json,
    fixture_mode,
    expected_ids,
):
    project_json_path = synthetic_project_json(fixture_mode)
    _open_project(window, monkeypatch, project_json_path)

    assert [entry["name"] for entry in window.model.action_item_data] == expected_ids
    window.dataset_explorer_controller.save_project()

    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    assert [item["id"] for item in saved["data"]] == expected_ids

    window.router.close_project()
    _open_project(window, monkeypatch, project_json_path)
    assert [entry["name"] for entry in window.model.action_item_data] == expected_ids


@pytest.mark.gui
def test_rename_sample_id_updates_tree_selection_and_dataset_json(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification")
    _open_project(window, monkeypatch, project_json_path)

    sample_index = _select_top_row(window, qtbot, 0)
    assert sample_index.isValid()
    assert sample_index.data(window.tree_model.DataIdRole) == "clip_1"

    parent_item = window.tree_model.itemFromIndex(sample_index)
    assert parent_item is not None
    parent_item.setText("renamed_clip")
    qtbot.wait(50)

    refreshed_index = window.tree_model.index(0, 0)
    assert refreshed_index.isValid()
    assert refreshed_index.data(window.tree_model.DataIdRole) == "renamed_clip"
    assert refreshed_index.data() == "renamed_clip"

    renamed_sample = window.model.get_sample("renamed_clip")
    assert renamed_sample is not None
    assert renamed_sample.get("id") == "renamed_clip"
    assert window.model.get_sample("clip_1") is None
    assert window.model.current_selected_sample_id == "renamed_clip"
    assert window.model.is_data_dirty is True

@pytest.mark.gui
def test_active_tab_switch_reapplies_markers_without_leaking_stale_markers(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=2)
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"])
    qtbot.wait(50)
    assert [marker["start_ms"] for marker in window.center_panel.slider.markers] == [1000]

    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["dense_description"])
    qtbot.wait(50)
    assert [marker["start_ms"] for marker in window.center_panel.slider.markers] == [1500]

    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["description"])
    qtbot.wait(50)
    assert window.center_panel.slider.markers == []

    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["classification"])
    qtbot.wait(50)
    assert window.center_panel.slider.markers == []


@pytest.mark.gui
def test_tab_switch_with_selection_does_not_repopulate_tree_or_restart_media(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=1)
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    populate_calls = {"count": 0}
    monkeypatch.setattr(
        window.dataset_explorer_controller,
        "populate_tree",
        lambda: populate_calls.__setitem__("count", populate_calls["count"] + 1),
    )

    play_calls = []
    monkeypatch.setattr(
        window.media_controller,
        "load_and_play",
        lambda file_path, auto_play=True: play_calls.append(file_path),
    )

    for mode_idx in (
        MODE_TO_TAB_INDEX["localization"],
        MODE_TO_TAB_INDEX["description"],
        MODE_TO_TAB_INDEX["dense_description"],
        MODE_TO_TAB_INDEX["classification"],
    ):
        window.right_tabs.setCurrentIndex(mode_idx)
        qtbot.wait(50)

    assert populate_calls["count"] == 0
    assert play_calls == []
    assert window.model.current_selected_sample_id == "clip_1"
    assert window.dataset_explorer_panel.tree.currentIndex().isValid()


@pytest.mark.gui
def test_remove_top_level_row_keeps_next_selection_valid(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=2)
    _open_project(window, monkeypatch, project_json_path)

    first_index = _select_top_row(window, qtbot, 0)
    window.dataset_explorer_controller.handle_remove_item(first_index)
    qtbot.wait(50)

    assert window.tree_model.rowCount() == 1
    assert window.model.current_selected_sample_id == "clip_2"
    assert window.get_current_action_path() == window.model.get_path_by_id("clip_2")


@pytest.mark.gui
def test_remove_child_row_removes_one_input_and_keeps_multiview_sample(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("multiview")
    _open_project(window, monkeypatch, project_json_path)

    parent_index = _select_top_row(window, qtbot, 0)
    child_index = window.tree_model.index(0, 0, parent_index)
    assert child_index.isValid()

    original_sample = window.model.get_sample("mv_clip")
    assert original_sample is not None
    assert len(original_sample.get("inputs", [])) == 2

    window.dataset_explorer_panel.tree.setCurrentIndex(child_index)
    qtbot.wait(50)
    window.dataset_explorer_controller.handle_remove_item(child_index)
    qtbot.wait(50)

    assert window.tree_model.rowCount() == 1
    remaining_sample = window.model.get_sample("mv_clip")
    assert remaining_sample is not None
    assert len(remaining_sample.get("inputs", [])) == 1

    refreshed_parent = window.tree_model.index(0, 0)
    assert refreshed_parent.isValid()
    assert window.tree_model.rowCount(refreshed_parent) == 1
    remaining_child = window.tree_model.index(0, 0, refreshed_parent)
    assert remaining_child.isValid()
    assert window.model.current_selected_sample_id == "mv_clip"
    assert window.model.current_selected_input_path == remaining_child.data(window.tree_model.FilePathRole)
    assert window.dataset_explorer_panel.tree.currentIndex() == remaining_child


@pytest.mark.gui
def test_remove_only_child_row_removes_whole_single_input_sample(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification")
    _open_project(window, monkeypatch, project_json_path)

    parent_index = _select_top_row(window, qtbot, 0)
    child_index = window.tree_model.index(0, 0, parent_index)
    assert child_index.isValid()

    window.dataset_explorer_panel.tree.setCurrentIndex(child_index)
    qtbot.wait(50)
    window.dataset_explorer_controller.handle_remove_item(child_index)
    qtbot.wait(50)

    assert window.tree_model.rowCount() == 0
    assert window.model.dataset_json["data"] == []
    assert window.model.current_selected_sample_id == ""


@pytest.mark.gui
def test_remove_sample_selects_previous_sample(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=3)
    _open_project(window, monkeypatch, project_json_path)

    second_index = _select_top_row(window, qtbot, 1)
    assert second_index.isValid()
    assert second_index.data(window.tree_model.DataIdRole) == "clip_2"

    window.dataset_explorer_controller.handle_remove_item(second_index)
    qtbot.wait(50)

    assert window.tree_model.rowCount() == 2
    assert window.model.current_selected_sample_id == "clip_1"
    assert window.get_current_action_path() == window.model.get_path_by_id("clip_1")


@pytest.mark.gui
def test_remove_keeps_expanded_tree_rows(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=3)
    _open_project(window, monkeypatch, project_json_path)

    first_parent = _select_top_row(window, qtbot, 0)
    second_parent = _select_top_row(window, qtbot, 1)
    third_parent = _select_top_row(window, qtbot, 2)
    assert first_parent.isValid()
    assert second_parent.isValid()
    assert third_parent.isValid()

    tree = window.dataset_explorer_panel.tree
    assert tree.isExpanded(first_parent)
    assert tree.isExpanded(second_parent)
    assert tree.isExpanded(third_parent)

    window.dataset_explorer_controller.handle_remove_item(second_parent)
    qtbot.wait(50)

    refreshed_first = window.tree_model.index(0, 0)
    refreshed_second = window.tree_model.index(1, 0)
    assert refreshed_first.isValid()
    assert refreshed_second.isValid()
    assert refreshed_first.data(window.tree_model.DataIdRole) == "clip_1"
    assert refreshed_second.data(window.tree_model.DataIdRole) == "clip_3"
    assert tree.isExpanded(refreshed_first)
    assert tree.isExpanded(refreshed_second)


@pytest.mark.gui
def test_selecting_new_parent_expands_it_without_collapsing_others(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=2)
    _open_project(window, monkeypatch, project_json_path)

    first_parent = _select_top_row(window, qtbot, 0)
    second_parent = window.tree_model.index(1, 0)
    assert first_parent.isValid()
    assert second_parent.isValid()
    assert window.tree_model.rowCount(first_parent) == 1
    assert window.tree_model.rowCount(second_parent) == 1

    tree = window.dataset_explorer_panel.tree
    assert tree.isExpanded(first_parent)
    assert not tree.isExpanded(second_parent)

    tree.setCurrentIndex(second_parent)
    qtbot.wait(50)

    assert tree.isExpanded(first_parent)
    assert tree.isExpanded(second_parent)


@pytest.mark.gui
@pytest.mark.parametrize("mode_idx", [0, 1, 2, 3])
def test_filter_not_labelled_reselects_first_visible_row_for_each_mode(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
    mode_idx,
):
    project_json_path = synthetic_project_json("mixed", item_count=2)
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    window.right_tabs.setCurrentIndex(mode_idx)
    qtbot.wait(50)
    window.dataset_explorer_panel.filter_combo.setCurrentIndex(3)
    qtbot.wait(50)

    assert window.model.current_selected_sample_id == "clip_2"
    assert window.get_current_action_path() == window.model.get_path_by_id("clip_2")
    assert window.dataset_explorer_panel.tree.isRowHidden(0, window.dataset_explorer_panel.tree.rootIndex())
    assert not window.dataset_explorer_panel.tree.isRowHidden(1, window.dataset_explorer_panel.tree.rootIndex())


@pytest.mark.gui
@pytest.mark.parametrize("mode_idx", [2, 3])
def test_filter_smart_labelled_clears_selection_when_mode_has_no_smart_state(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
    mode_idx,
):
    project_json_path = synthetic_project_json("mixed", item_count=2)
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    window.right_tabs.setCurrentIndex(mode_idx)
    qtbot.wait(50)
    window.dataset_explorer_panel.filter_combo.setCurrentIndex(2)
    qtbot.wait(50)

    assert window.model.current_selected_sample_id == ""
    assert window.model.current_selected_input_path is None
    assert window.center_panel.slider.markers == []
    if mode_idx == MODE_TO_TAB_INDEX["description"]:
        assert not window.description_panel.isEnabled()
    else:
        assert not window.dense_panel.isEnabled()


# @pytest.mark.gui
# def test_add_sample_without_dataset_warns_and_dialog_cancel_is_noop(window, monkeypatch):
#     warning_calls = {"count": 0}
#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QMessageBox.warning",
#         lambda *args, **kwargs: warning_calls.__setitem__("count", warning_calls["count"] + 1)
#         or QMessageBox.StandardButton.Ok,
#     )

#     window.dataset_explorer_controller.handle_add_sample()
#     assert warning_calls["count"] == 1

#     window.dataset_explorer_controller.create_new_project()
#     before_count = window.tree_model.rowCount()
#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileNames",
#         lambda *args, **kwargs: ([], "Media Files (*.mp4)"),
#     )
#     window.dataset_explorer_controller.handle_add_sample()

#     assert window.tree_model.rowCount() == before_count == 0
#     assert window.model.dataset_json["data"] == []


# @pytest.mark.gui
# def test_add_sample_multiview_groups_files_by_parent_directory(window, monkeypatch, qtbot, tmp_path):
#     source_video = Path(__file__).resolve().parents[1] / "data" / "test_video_1.mp4"
#     source_bytes = source_video.read_bytes()

#     window.dataset_explorer_controller.create_new_project(multiview_grouping=True)

#     group_a = tmp_path / "group_a"
#     group_b = tmp_path / "group_b"
#     group_a.mkdir()
#     group_b.mkdir()

#     selected_files = []
#     for directory in (group_a, group_b):
#         for idx in range(2):
#             target = directory / f"view_{idx + 1}.mp4"
#             target.write_bytes(source_bytes)
#             selected_files.append(str(target))

#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileNames",
#         lambda *args, **kwargs: (selected_files, "Media Files (*.mp4)"),
#     )
#     qtbot.mouseClick(window.dataset_explorer_panel.btn_add_data, Qt.MouseButton.LeftButton)
#     qtbot.wait(50)

#     assert window.tree_model.rowCount() == 2
#     assert {entry["name"] for entry in window.model.action_item_data} == {"group_a", "group_b"}

#     for row in range(window.tree_model.rowCount()):
#         index = window.tree_model.index(row, 0)
#         assert window.tree_model.rowCount(index) == 2


# @pytest.mark.gui
# def test_add_sample_single_view_duplicate_basenames_get_unique_ids(window, monkeypatch, qtbot, tmp_path):
#     source_video = Path(__file__).resolve().parents[1] / "data" / "test_video_2.mp4"
#     source_bytes = source_video.read_bytes()

#     window.dataset_explorer_controller.create_new_project(multiview_grouping=False)

#     dir_a = tmp_path / "camera_a"
#     dir_b = tmp_path / "camera_b"
#     dir_a.mkdir()
#     dir_b.mkdir()

#     first_dup = dir_a / "dup.mp4"
#     second_dup = dir_b / "dup.mp4"
#     first_dup.write_bytes(source_bytes)
#     second_dup.write_bytes(source_bytes)

#     monkeypatch.setattr(
#         "controllers.dataset_explorer_controller.QFileDialog.getOpenFileNames",
#         lambda *args, **kwargs: ([str(first_dup), str(second_dup)], "Media Files (*.mp4)"),
#     )
#     qtbot.mouseClick(window.dataset_explorer_panel.btn_add_data, Qt.MouseButton.LeftButton)
#     qtbot.wait(50)

#     assert window.tree_model.rowCount() == 2
#     assert {entry["name"] for entry in window.model.action_item_data} == {"dup", "dup__2"}


@pytest.mark.gui
def test_clear_workspace_preserves_headers_schema_and_unknown_keys(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=2)
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QMessageBox.exec",
        lambda self: QMessageBox.StandardButton.Yes,
    )

    window.dataset_explorer_controller.handle_clear_workspace()

    assert window.model.json_loaded is True
    assert window.model.dataset_json["data"] == []
    assert window.model.dataset_json["custom_root"] == {"keep": True}
    assert "action" in window.model.dataset_json["labels"]
    assert window.tree_model.rowCount() == 0
    assert not window.description_panel.isEnabled()

    raw_json = json.loads(window.dataset_explorer_panel.json_raw_text.toPlainText())
    assert raw_json["data"] == []
    assert raw_json["custom_root"] == {"keep": True}


@pytest.mark.gui
def test_clear_workspace_cancel_is_a_noop(window, monkeypatch, qtbot, synthetic_project_json):
    project_json_path = synthetic_project_json("mixed", item_count=2)
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QMessageBox.exec",
        lambda self: QMessageBox.StandardButton.Cancel,
    )

    before_json = json.loads(window.dataset_explorer_panel.json_raw_text.toPlainText())
    window.dataset_explorer_controller.handle_clear_workspace()

    assert window.tree_model.rowCount() == 2
    assert window.model.dataset_json["data"] == before_json["data"]


@pytest.mark.gui
def test_save_as_rewrites_paths_autosaves_description_and_promotes_new_recent(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
    tmp_path,
):
    project_json_path = synthetic_project_json("description")
    _open_project(window, monkeypatch, project_json_path)
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["description"]

    _select_top_row(window, qtbot, 0)
    final_text = "Description saved through Save As."
    window.description_panel.caption_edit.setPlainText(final_text)

    export_dir = tmp_path / "exported" / "nested"
    export_dir.mkdir(parents=True)
    export_path = export_dir / "saved_description.json"
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "JSON Files (*.json)"),
    )

    assert window.dataset_explorer_controller.export_project() is True
    assert Path(window.model.current_json_path) == export_path.resolve()
    assert window.router.get_recent_projects()[0] == str(export_path.resolve())

    saved = json.loads(export_path.read_text(encoding="utf-8"))
    saved_sample = saved["data"][0]
    saved_input_path = saved_sample["inputs"][0]["path"]
    expected_video = Path(__file__).resolve().parents[1] / "data" / "test_video_1.mp4"
    expected_rel = os.path.relpath(expected_video, start=export_dir).replace("\\", "/")

    assert saved_sample["captions"][0]["text"] == final_text
    assert not os.path.isabs(saved_input_path)
    assert saved_input_path == expected_rel

    window.show_welcome_view()
    assert _recent_file_button_text(window) == export_path.name

    window.router.close_project()
    _open_project(window, monkeypatch, export_path)
    _select_top_row(window, qtbot, 0)

    assert Path(window.model.action_item_data[0]["path"]).resolve() == expected_video.resolve()
    assert window.description_panel.caption_edit.toPlainText() == final_text


@pytest.mark.gui
def test_save_keeps_current_tree_selection_and_expansion_state(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=3)
    _open_project(window, monkeypatch, project_json_path)

    first_parent = _select_top_row(window, qtbot, 0)
    second_parent = _select_top_row(window, qtbot, 1)
    assert first_parent.isValid()
    assert second_parent.isValid()
    assert second_parent.data(window.tree_model.DataIdRole) == "clip_2"

    tree = window.dataset_explorer_panel.tree
    assert tree.isExpanded(first_parent)
    assert tree.isExpanded(second_parent)
    assert window.model.current_selected_sample_id == "clip_2"

    window.dataset_explorer_controller.save_project()
    qtbot.wait(50)

    refreshed_first = window.tree_model.index(0, 0)
    refreshed_second = window.tree_model.index(1, 0)
    assert refreshed_first.isValid()
    assert refreshed_second.isValid()
    assert refreshed_second.data(window.tree_model.DataIdRole) == "clip_2"
    assert window.model.current_selected_sample_id == "clip_2"
    assert tree.isExpanded(refreshed_first)
    assert tree.isExpanded(refreshed_second)


@pytest.mark.gui
def test_json_tab_reflects_header_edit_sample_edit_and_undo_redo(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("description")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    edited_description = "Header description updated from explorer test."
    edited_caption = "Description v2 for JSON preview coverage."
    original_caption = "A short test caption."

    _set_known_header_value(window.dataset_explorer_panel, "description", edited_description)
    qtbot.wait(50)
    window.description_panel.caption_edit.setPlainText(edited_caption)
    qtbot.wait(350)

    raw_json = json.loads(window.dataset_explorer_panel.json_raw_text.toPlainText())
    assert raw_json["description"] == edited_description
    assert raw_json["data"][0]["captions"][0]["text"] == edited_caption

    window.history_manager.perform_undo()
    qtbot.wait(50)

    raw_after_undo = json.loads(window.dataset_explorer_panel.json_raw_text.toPlainText())
    assert raw_after_undo["description"] == edited_description
    assert raw_after_undo["data"][0]["captions"][0]["text"] == original_caption

    window.history_manager.perform_redo()
    qtbot.wait(50)

    raw_after_redo = json.loads(window.dataset_explorer_panel.json_raw_text.toPlainText())
    assert raw_after_redo["description"] == edited_description
    assert raw_after_redo["data"][0]["captions"][0]["text"] == edited_caption

    window.dataset_explorer_controller.save_project()
    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    assert saved["description"] == edited_description
    assert saved["data"][0]["captions"][0]["text"] == edited_caption


@pytest.mark.gui
def test_localization_undo_redo_does_not_repopulate_tree_or_restart_media(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("localization")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)
    window.right_tabs.setCurrentIndex(MODE_TO_TAB_INDEX["localization"])
    qtbot.wait(50)

    path = window.model.get_path_by_id(window.model.current_selected_sample_id)
    assert path
    events = window.model.localization_events.get(path, [])
    assert events
    old_event = events[0]
    new_event = dict(old_event)
    new_event["position_ms"] = int(old_event.get("position_ms", 0)) + 250
    window.localization_editor_controller._on_annotation_modified(old_event, new_event)
    qtbot.wait(50)
    assert window.model.undo_stack

    populate_calls = {"count": 0}
    monkeypatch.setattr(
        window.dataset_explorer_controller,
        "populate_tree",
        lambda: populate_calls.__setitem__("count", populate_calls["count"] + 1),
    )

    play_calls = []
    monkeypatch.setattr(
        window.media_controller,
        "load_and_play",
        lambda file_path, auto_play=True: play_calls.append(file_path),
    )

    window.history_manager.perform_undo()
    qtbot.wait(50)
    window.history_manager.perform_redo()
    qtbot.wait(50)

    assert populate_calls["count"] == 0
    assert play_calls == []


@pytest.mark.gui
def test_undo_filter_clear_selection_when_selected_row_becomes_hidden(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification", item_count=2)
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 1)

    first_path = window.model.get_path_by_id("clip_1")
    second_path = window.model.get_path_by_id("clip_2")
    assert first_path
    assert second_path

    window.model.manual_annotations[first_path] = {"action": "pass"}
    window.model.manual_annotations[second_path] = {"action": "pass"}
    window.update_action_item_status(first_path)
    window.update_action_item_status(second_path)

    window.model.push_undo(
        CmdType.ANNOTATION_CONFIRM,
        path=second_path,
        old_data=None,
        new_data={"action": "pass"},
    )

    window.dataset_explorer_panel.filter_combo.setCurrentIndex(1)
    qtbot.wait(50)
    assert window.model.current_selected_sample_id == "clip_2"

    window.history_manager.perform_undo()
    qtbot.wait(50)

    tree = window.dataset_explorer_panel.tree
    assert not tree.currentIndex().isValid()
    assert window.model.current_selected_sample_id == ""
    assert window.model.current_selected_input_path is None
    assert not tree.isRowHidden(0, tree.rootIndex())
    assert tree.isRowHidden(1, tree.rootIndex())
