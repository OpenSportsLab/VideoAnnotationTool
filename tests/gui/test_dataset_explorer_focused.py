"""
Focused Dataset Explorer controller and panel tests using minimal fixtures.
"""

import types

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QDialog, QMessageBox

from controllers.dataset_explorer_controller import DatasetExplorerController
from ui.dataset_explorer_panel import DatasetExplorerPanel


class _DummyMediaController:
    def stop(self):
        return None


@pytest.fixture
def explorer_panel_and_controller(qtbot, tmp_path):
    panel = DatasetExplorerPanel(
        tree_title="Data",
        filter_items=["Show All", "Show Hand Labelled", "Show Smart Labelled", "Show Not Labelled"],
        clear_text="Clear All",
        enable_context_menu=True,
    )
    qtbot.addWidget(panel)

    controller = DatasetExplorerController(
        main_window=types.SimpleNamespace(),
        panel=panel,
        tree_model=panel.tree_model,
        media_controller=_DummyMediaController(),
    )
    controller.settings = QSettings(str(tmp_path / "dataset_explorer_test.ini"), QSettings.Format.IniFormat)
    return panel, controller


def _known_row(panel, key: str) -> int:
    for row in range(panel.table_header_known.rowCount()):
        key_item = panel.table_header_known.item(row, 0)
        if key_item and key_item.text() == key:
            return row
    raise AssertionError(f"Missing known header row: {key}")


def _unknown_row(panel, key: str) -> int:
    for row in range(panel.table_header_unknown.rowCount()):
        key_item = panel.table_header_unknown.item(row, 0)
        if key_item and key_item.text() == key:
            return row
    raise AssertionError(f"Missing unknown header row: {key}")


def test_normalize_dataset_json_inserts_defaults_preserves_unknowns_and_fixes_ids(
    explorer_panel_and_controller,
):
    _panel, controller = explorer_panel_and_controller
    raw = {
        "custom_root": {"keep": True},
        "metadata": "not-a-dict",
        "modalities": "video",
        "data": [
            {
                "id": "clip_dup",
                "inputs": [{"path": "clips/one.mp4", "type": "video"}],
                "metadata": "bad",
                "events": [{"head": "action", "label": "pass", "position_ms": "1001"}],
                "custom_sample": {"keep": 1},
            },
            {
                "id": "clip_dup",
                "inputs": [{"path": "clips/two.mp4", "type": "video"}],
            },
            {
                "inputs": [{"path": "clips/three.mp4", "type": "video"}],
            },
        ],
    }

    normalized, error = controller._normalize_dataset_json(raw)

    assert error == ""
    assert normalized["version"] == "2.0"
    assert normalized["task"] == "video_annotation"
    assert normalized["metadata"] == {}
    assert normalized["modalities"] == ["video"]
    assert normalized["custom_root"] == {"keep": True}
    assert [sample["id"] for sample in normalized["data"]] == ["clip_dup", "clip_dup__2", "sample_3"]
    assert normalized["data"][0]["events"][0]["position_ms"] == 1001
    assert normalized["data"][0]["metadata"] == {}
    assert normalized["data"][0]["custom_sample"] == {"keep": 1}


def test_normalize_dataset_json_rejects_invalid_root_and_non_list_data(explorer_panel_and_controller):
    _panel, controller = explorer_panel_and_controller

    normalized, error = controller._normalize_dataset_json(["not", "a", "dict"])
    assert normalized is None
    assert error == "Root JSON must be an object."

    normalized, error = controller._normalize_dataset_json({"data": {}})
    assert normalized is None
    assert error == "Top-level 'data' must be a list."


def test_dataset_json_for_write_rewrites_relative_paths_and_strips_empty_fields(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    project_root = tmp_path / "project"
    save_root = tmp_path / "exports"
    media_dir = project_root / "clips"
    media_dir.mkdir(parents=True)
    save_root.mkdir(parents=True)
    media_path = media_dir / "clip.mp4"
    media_path.write_bytes(b"video")

    controller.project_root = str(project_root)
    controller.current_working_directory = str(project_root)
    controller.dataset_json = {
        "version": "2.0",
        "date": "2026-04-08",
        "task": "video_annotation",
        "dataset_name": "write_test",
        "description": None,
        "modalities": ["video"],
        "metadata": {},
        "labels": {},
        "custom_root": {"keep": True},
        "data": [
            {
                "id": "clip_1",
                "inputs": [{"path": "clips/clip.mp4", "type": "video"}],
                "labels": {},
                "smart_labels": {},
                "events": [],
                "smart_events": [],
                "captions": [],
                "dense_captions": [],
                "metadata": {},
                "custom_sample": {"keep": 1},
            }
        ],
    }

    written = controller._dataset_json_for_write(str(save_root / "dataset.json"))

    assert written["description"] == ""
    assert written["metadata"] == {}
    assert written["modalities"] == ["video"]
    assert written["custom_root"] == {"keep": True}
    assert written["data"][0]["inputs"][0]["path"] == "../project/clips/clip.mp4"
    assert "labels" not in written["data"][0]
    assert "smart_labels" not in written["data"][0]
    assert "events" not in written["data"][0]
    assert "smart_events" not in written["data"][0]
    assert "captions" not in written["data"][0]
    assert "dense_captions" not in written["data"][0]
    assert "metadata" not in written["data"][0]
    assert written["data"][0]["custom_sample"] == {"keep": 1}


@pytest.mark.parametrize(
    ("task_name", "expected_idx"),
    [
        ("classification", 0),
        ("action_classification", 0),
        ("action-spotting", 1),
        ("video captioning", 2),
        ("dense_video_captioning", 3),
        ("unknown", None),
        (None, None),
    ],
)
def test_tab_index_for_task_supports_aliases(explorer_panel_and_controller, task_name, expected_idx):
    _panel, controller = explorer_panel_and_controller
    assert controller._tab_index_for_task(task_name) == expected_idx


def test_group_selected_files_and_sample_id_rules_for_single_and_multiview(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    group_a = tmp_path / "group_a"
    group_b = tmp_path / "group_b"
    group_a.mkdir()
    group_b.mkdir()

    file_a1 = str(group_a / "view_1.mp4")
    file_a2 = str(group_a / "view_2.mp4")
    file_b1 = str(group_b / "view_1.mp4")

    controller.is_multi_view = False
    assert controller._group_selected_files([file_a1, file_a2]) == [[file_a1], [file_a2]]
    assert controller._sample_id_from_group([file_a1]) == "view_1"

    controller.is_multi_view = True
    grouped = controller._group_selected_files([file_a2, file_b1, file_a1])
    assert grouped == [[file_a1, file_a2], [file_b1]]
    assert controller._sample_id_from_group([file_a1, file_a2]) == "group_a"
    assert controller._sample_id_from_group([file_b1]) == "view_1"


def test_panel_header_editor_flags_and_raw_json_widget_are_configured(explorer_panel_and_controller):
    panel, _controller = explorer_panel_and_controller
    panel.set_header_rows(
        known={
            "version": "2.0",
            "task": "video_annotation",
            "metadata": {"source": "pytest"},
            "modalities": ["video"],
        },
        unknown={"custom_owner": "qa-team"},
        draft={},
    )

    task_item = panel.table_header_known.item(_known_row(panel, "task"), 1)
    metadata_item = panel.table_header_known.item(_known_row(panel, "metadata"), 1)
    modalities_item = panel.table_header_known.item(_known_row(panel, "modalities"), 1)
    owner_item = panel.table_header_unknown.item(_unknown_row(panel, "custom_owner"), 1)

    assert bool(task_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert not bool(metadata_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert not bool(modalities_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert not bool(owner_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert panel.json_raw_text.isReadOnly() is True


def test_panel_nested_json_edit_updates_draft_and_emits_signal(
    explorer_panel_and_controller,
):
    panel, _controller = explorer_panel_and_controller
    panel.set_header_rows(
        known={"metadata": {"source": "pytest"}},
        unknown={},
        draft={},
    )

    draft_events = []
    panel.headerDraftChanged.connect(draft_events.append)

    panel._open_json_value_dialog = lambda key, current_value: {"source": "updated", "owner": "qa"}
    panel._on_known_header_cell_double_clicked(_known_row(panel, "metadata"), 1)

    assert panel.get_staged_header_draft() == {"metadata": {"source": "updated", "owner": "qa"}}
    assert draft_events[-1] == {"metadata": {"source": "updated", "owner": "qa"}}
    assert panel.table_header_known.item(_known_row(panel, "metadata"), 1).text().startswith("{")


def test_panel_open_json_value_dialog_rejects_invalid_json_and_returns_missing(
    explorer_panel_and_controller,
    monkeypatch,
):
    panel, _controller = explorer_panel_and_controller

    exec_results = iter([QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected])
    warning_calls = {"count": 0}

    monkeypatch.setattr("ui.dataset_explorer_panel.QDialog.exec", lambda self: next(exec_results))
    monkeypatch.setattr("ui.dataset_explorer_panel.QPlainTextEdit.toPlainText", lambda self: "{invalid json")
    monkeypatch.setattr(
        "ui.dataset_explorer_panel.QMessageBox.warning",
        lambda *args, **kwargs: warning_calls.__setitem__("count", warning_calls["count"] + 1)
        or QMessageBox.StandardButton.Ok,
    )

    result = panel._open_json_value_dialog("metadata", {"source": "pytest"})

    assert result is panel._MISSING
    assert warning_calls["count"] == 1


def test_recent_path_helpers_normalize_and_dedupe_equivalent_paths(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    dataset_path = (tmp_path / "datasets" / "demo.json").resolve()
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text("{}", encoding="utf-8")

    controller._add_recent_project(str(dataset_path))
    controller._add_recent_project(str(dataset_path.parent / "." / dataset_path.name))

    recents = controller.get_recent_projects()
    assert recents == [str(dataset_path)]

    other_path = (tmp_path / "datasets" / "second.json").resolve()
    other_path.write_text("{}", encoding="utf-8")
    controller._add_recent_project(str(other_path))
    controller._add_recent_project(str(dataset_path))

    assert controller.get_recent_projects()[:2] == [str(dataset_path), str(other_path)]
