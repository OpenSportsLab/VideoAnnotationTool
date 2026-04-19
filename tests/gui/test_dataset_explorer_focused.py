"""
Focused Dataset Explorer controller and panel tests using minimal fixtures.
"""

import pytest
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import QDialog, QMessageBox

from controllers.dataset_explorer_controller import DatasetExplorerController
from ui.dataset_explorer_panel import DatasetExplorerPanel


@pytest.fixture
def explorer_panel_and_controller(qtbot, tmp_path):
    panel = DatasetExplorerPanel(
        tree_title="Data",
        filter_items=["Show All", "Show Labelled", "Show Smart Labelled", "Show Not Labelled"],
        clear_text="Clear All",
        enable_context_menu=True,
    )
    qtbot.addWidget(panel)

    controller = DatasetExplorerController(panel=panel, tree_model=panel.tree_model)
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
    assert "task" not in normalized
    assert normalized["metadata"] == {}
    assert normalized["modalities"] == ["video"]
    assert normalized["questions"] == []
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


def test_normalize_dataset_json_drops_legacy_smart_keys(explorer_panel_and_controller):
    _panel, controller = explorer_panel_and_controller
    raw = {
        "questions": [
            {"id": "q1", "question": "How are you?"},
            {"id": "q1", "question": "duplicate"},
            {"id": "", "question": "invalid"},
        ],
        "data": [
            {
                "id": "clip_1",
                "inputs": [{"path": "clips/one.mp4", "type": "video"}],
                "labels": {"phase": {"label": "build"}},
                "events": [{"head": "ball_action", "label": "pass", "position_ms": 1000}],
                "answers": [
                    {"question_id": "q1", "answer": "ok"},
                    {"question_id": "q2", "answer": "unknown-id"},
                    {"question_id": "q1", "answer": "duplicate-id"},
                ],
                "smart_label": {"label": "shot"},
                "smart_event": {"head": "ball_action", "label": "shot", "position_ms": 1200},
                "smart_labels": {"action": {"label": "shot", "conf_dict": {"shot": 0.72}}},
                "smart_events": [{"head": "ball_action", "label": "shot", "position_ms": 2000}],
            }
        ],
    }

    normalized, error = controller._normalize_dataset_json(raw)
    assert error == ""
    sample = normalized["data"][0]
    assert normalized["questions"] == [{"id": "q1", "question": "How are you?"}]
    assert sample["answers"] == [{"question_id": "q1", "answer": "ok"}]
    assert sample["labels"]["phase"]["label"] == "build"
    assert "smart_labels" not in sample
    assert "smart_events" not in sample
    assert "smart_label" not in sample
    assert "smart_event" not in sample


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
        "questions": [
            {"id": "q1", "question": "How are you?"},
            {"id": "q2", "question": "What happened?"},
        ],
        "custom_root": {"keep": True},
        "data": [
            {
                "id": "clip_1",
                "inputs": [{"path": "clips/clip.mp4", "type": "video"}],
                "labels": {},
                "events": [],
                "captions": [],
                "dense_captions": [],
                "answers": [
                    {"question_id": "q1", "answer": "I am fine."},
                    {"question_id": "qmissing", "answer": "drop"},
                ],
                "metadata": {},
                "custom_sample": {"keep": 1},
            }
        ],
    }

    written = controller._dataset_json_for_write(str(save_root / "dataset.json"))

    assert written["description"] == ""
    assert written["metadata"] == {}
    assert written["modalities"] == ["video"]
    assert written["task"] == "video_annotation"
    assert written["custom_root"] == {"keep": True}
    assert written["questions"] == [
        {"id": "q1", "question": "How are you?"},
        {"id": "q2", "question": "What happened?"},
    ]
    assert written["data"][0]["inputs"][0]["path"] == "../project/clips/clip.mp4"
    assert "labels" not in written["data"][0]
    assert "events" not in written["data"][0]
    assert "captions" not in written["data"][0]
    assert "dense_captions" not in written["data"][0]
    assert written["data"][0]["answers"] == [{"question_id": "q1", "answer": "I am fine."}]
    assert "metadata" not in written["data"][0]
    assert written["data"][0]["custom_sample"] == {"keep": 1}


def test_available_mode_indices_for_sample_prefers_fixed_order(explorer_panel_and_controller):
    _panel, controller = explorer_panel_and_controller
    sample = {
        "labels": {"action": {"label": "shot", "confidence_score": 0.9}},
        "events": [
            {"head": "action", "label": "pass", "position_ms": 1000},
            {"head": "action", "label": "shot", "position_ms": 2000, "confidence_score": 0.7},
        ],
        "captions": [{"lang": "en", "text": "caption"}],
        "dense_captions": [{"position_ms": 1500, "lang": "en", "text": "dense"}],
        "answers": [{"question_id": "q1", "answer": "answer"}],
    }
    controller.dataset_json["questions"] = [{"id": "q1", "question": "How are you?"}]
    assert controller._available_mode_indices_for_sample(sample) == [0, 1, 2, 3, 4]
    assert controller._available_mode_indices_for_sample({"events": [{"position_ms": 1}]}) == [1]
    assert controller._available_mode_indices_for_sample({"captions": [{"text": ""}]}) == []
    assert controller._available_mode_indices_for_sample({"answers": [{"question_id": "q1", "answer": "x"}]}) == [4]


def test_group_selected_files_and_sample_id_rules(
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

    assert controller._group_selected_files([file_a1, file_a2]) == [[file_a1, file_a2]]
    grouped = controller._group_selected_files([file_a2, file_b1, file_a1])
    assert grouped == [[file_a1, file_a2], [file_b1]]
    assert controller._sample_id_from_group([file_a1]) == "view_1"
    assert controller._sample_id_from_group([file_a1, file_a2]) == "group_a"
    assert controller._sample_id_from_group([file_b1]) == "view_1"


def test_source_groups_from_selected_paths_maps_files_to_single_and_folders_to_multi(
    explorer_panel_and_controller,
    tmp_path,
):
    _panel, controller = explorer_panel_and_controller
    single_file = tmp_path / "single.mp4"
    single_file.write_bytes(b"media")

    group_dir = tmp_path / "group_dir"
    group_dir.mkdir()
    group_view_2 = group_dir / "view_2.mp4"
    group_view_1 = group_dir / "view_1.mp4"
    ignored = group_dir / "notes.txt"
    group_view_2.write_bytes(b"media")
    group_view_1.write_bytes(b"media")
    ignored.write_text("ignore", encoding="utf-8")

    source_groups = controller._source_groups_from_selected_paths(
        [str(single_file), str(group_dir)]
    )

    assert source_groups == [
        [str(single_file)],
        [str(group_view_1), str(group_view_2)],
    ]


def test_panel_header_editor_flags_and_raw_json_widget_are_configured(explorer_panel_and_controller):
    panel, _controller = explorer_panel_and_controller
    panel.set_header_rows(
        known={
            "version": "2.0",
            "metadata": {"source": "pytest"},
        },
        unknown={
            "custom_owner": "qa-team",
            "task": "video_annotation",
            "modalities": ["video"],
        },
        draft={},
    )

    metadata_item = panel.table_header_known.item(_known_row(panel, "metadata"), 1)
    owner_item = panel.table_header_unknown.item(_unknown_row(panel, "custom_owner"), 1)
    task_item = panel.table_header_unknown.item(_unknown_row(panel, "task"), 1)
    modalities_item = panel.table_header_unknown.item(_unknown_row(panel, "modalities"), 1)

    assert not bool(metadata_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert not bool(modalities_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert not bool(owner_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert not bool(task_item.flags() & Qt.ItemFlag.ItemIsEditable)
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
