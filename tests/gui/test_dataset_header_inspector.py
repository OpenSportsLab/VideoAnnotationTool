"""
Dataset Explorer header inspector workflows.
"""

import json
import os
from pathlib import Path

import pytest
from PyQt6.QtCore import Qt


def _write_classification_project_with_custom_header(tmp_path: Path) -> Path:
    source_video = Path(__file__).resolve().parents[1] / "data" / "test_video_1.mp4"
    assert source_video.exists()
    rel_video_path = os.path.relpath(source_video, start=tmp_path).replace("\\", "/")

    payload = {
        "version": "2.0",
        "date": "2026-04-06",
        "task": "action_classification",
        "description": "Header smoke",
        "dataset_name": "header_fixture",
        "modalities": ["video"],
        "metadata": {"source": "pytest"},
        "custom_owner": "qa-team",
        "custom_block": {"note": "keep me"},
        "labels": {
            "action": {
                "type": "single_label",
                "labels": ["pass", "shot"],
            }
        },
        "data": [
            {
                "id": "clip_1",
                "inputs": [{"path": rel_video_path, "type": "video"}],
                "labels": {},
            }
        ],
    }
    project_path = tmp_path / "classification_header_project.json"
    project_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return project_path


def _row_for_key(table, key: str) -> int:
    for row in range(table.rowCount()):
        key_item = table.item(row, 0)
        if key_item and key_item.text() == key:
            return row
    raise AssertionError(f"Key row not found: {key}")


def _set_known_value(panel, key: str, value: str):
    row = _row_for_key(panel.table_header_known, key)
    item = panel.table_header_known.item(row, 1)
    assert item is not None
    item.setText(value)


@pytest.mark.gui
# Workflow: Header inspector should show known keys as editable (scalars) and unknown keys as read-only.
def test_dataset_header_inspector_renders_known_and_unknown_fields(window, monkeypatch, tmp_path):
    project_json_path = _write_classification_project_with_custom_header(tmp_path)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    panel = window.dataset_explorer_panel
    known = panel.table_header_known
    unknown = panel.table_header_unknown

    modalities_row = _row_for_key(unknown, "modalities")
    modalities_item = unknown.item(modalities_row, 1)
    assert not bool(modalities_item.flags() & Qt.ItemFlag.ItemIsEditable)
    assert modalities_item.text().startswith("[")

    task_row = _row_for_key(unknown, "task")
    task_item = unknown.item(task_row, 1)
    assert task_item.text() == "action_classification"
    assert not bool(task_item.flags() & Qt.ItemFlag.ItemIsEditable)

    owner_row = _row_for_key(unknown, "custom_owner")
    owner_item = unknown.item(owner_row, 1)
    assert owner_item.text() == "qa-team"
    assert not bool(owner_item.flags() & Qt.ItemFlag.ItemIsEditable)

    block_row = _row_for_key(unknown, "custom_block")
    block_item = unknown.item(block_row, 1)
    assert block_item.text().startswith("{")
    assert not bool(block_item.flags() & Qt.ItemFlag.ItemIsEditable)


@pytest.mark.gui
# Workflow: Header edits should update the canonical dataset_json immediately, then persist and round-trip.
def test_header_draft_applies_on_save_and_roundtrips(window, monkeypatch, qtbot, tmp_path):
    project_json_path = _write_classification_project_with_custom_header(tmp_path)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    panel = window.dataset_explorer_panel
    new_description = "Edited header description"

    _set_known_value(panel, "description", new_description)
    qtbot.wait(50)

    assert window.model.dataset_json.get("description") == new_description
    assert window.model.project_header_draft == {}

    window.dataset_explorer_controller.save_project()

    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    assert saved.get("task") == "action_classification"
    assert saved.get("description") == new_description
    assert saved.get("custom_owner") == "qa-team"
    assert "labels" in saved
    assert len(saved.get("data", [])) == 1
    assert window.model.dataset_json.get("task") == "action_classification"

    window.router.close_project()
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    reloaded_panel = window.dataset_explorer_panel
    desc_row = _row_for_key(reloaded_panel.table_header_known, "description")
    assert reloaded_panel.table_header_known.item(desc_row, 1).text() == new_description
    owner_row = _row_for_key(reloaded_panel.table_header_unknown, "custom_owner")
    assert reloaded_panel.table_header_unknown.item(owner_row, 1).text() == "qa-team"
    task_row = _row_for_key(reloaded_panel.table_header_unknown, "task")
    assert reloaded_panel.table_header_unknown.item(task_row, 1).text() == "action_classification"


@pytest.mark.gui
# Workflow: Closing with discard after unsaved header edits should not write the in-memory values to disk.
def test_header_draft_discard_close_does_not_persist(window, monkeypatch, qtbot, tmp_path):
    project_json_path = _write_classification_project_with_custom_header(tmp_path)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.router.import_annotations()

    _set_known_value(window.dataset_explorer_panel, "description", "Unsaved staged description")
    qtbot.wait(50)
    assert window.model.is_data_dirty is True

    monkeypatch.setattr(window.dataset_explorer_controller, "_prompt_unsaved_close_action", lambda: "discard")
    window.router.close_project()

    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    assert saved.get("description") == "Header smoke"
    assert saved.get("custom_owner") == "qa-team"
