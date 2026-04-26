"""
Core GUI lifecycle smoke tests for `VideoAnnotationWindow`.
"""

import json
import os
from pathlib import Path

import pytest
from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtWidgets import QDialogButtonBox, QMessageBox

from app_info import APP_DISPLAY_NAME, APP_VERSION


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
    "question_answer": 4,
}

FRAME_STACK_PATH = (
    Path(__file__).resolve().parents[2]
    / "test_data"
    / "sn-gar"
    / "sngar-frames"
    / "train"
    / "clip_000000.npy"
)


@pytest.mark.gui
# Workflow: App startup should land on welcome screen with project UI disabled and no dataset loaded.
def test_launches_to_welcome_view(window):
    assert window.center_stack.currentIndex() == 0
    assert window.data_dock.isEnabled() is False
    assert window.editor_dock.isEnabled() is False
    assert window.dataset_explorer_controller.json_loaded is False


@pytest.mark.gui
@pytest.mark.parametrize("mode", list(MODE_TO_TAB_INDEX.keys()))
# Workflow: For each mode, import a synthetic JSON via routed file dialog and verify mode/view/tree state.
def test_import_project_routed_flow_all_modes(window, monkeypatch, synthetic_project_json, mode):
    project_json_path = synthetic_project_json(mode)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    window.dataset_explorer_controller.import_annotations()

    assert window.dataset_explorer_controller.json_loaded is True
    assert window.dataset_explorer_controller.current_json_path == str(project_json_path)
    assert window.center_stack.currentIndex() == 1
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX[mode]
    assert window.tree_model.rowCount() == 1


# @pytest.mark.gui
# @pytest.mark.parametrize("mode", list(MODE_TO_TAB_INDEX.keys()))
# # Workflow: Create a new project through router dialog flow for each mode and verify workspace/tab/model state.
# def test_create_project_routed_flow_all_modes(window, monkeypatch, mode):
#     class _FakeProjectTypeDialog:
#         def __init__(self, parent=None):
#             self.selected_mode = mode

#         def exec(self):
#             return True

#     monkeypatch.setattr("controllers.dataset_explorer_controller.ProjectTypeDialog", _FakeProjectTypeDialog)

#     window.dataset_explorer_controller.create_new_project_flow()

#     assert window.dataset_explorer_controller.json_loaded is True
#     assert window.dataset_explorer_controller.current_json_path is None
#     assert window.center_stack.currentIndex() == 1
#     assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX[mode]


@pytest.mark.gui
# Workflow: Create/load a project, trigger close flow, and verify full reset back to welcome view.
def test_close_project_returns_to_welcome(window, monkeypatch):
    window.dataset_explorer_controller.create_new_project("localization")
    assert window.dataset_explorer_controller.json_loaded is True

    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    window.dataset_explorer_controller.close_project()

    assert window.dataset_explorer_controller.json_loaded is False
    assert window.center_stack.currentIndex() == 0
    assert window.tree_model.rowCount() == 0


@pytest.mark.gui
# Workflow: Dataset Explorer Prev/Next Sample buttons should move current top-level dataset selection.
def test_dataset_explorer_prev_next_sample_buttons_navigate_rows(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification", item_count=3)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    window.dataset_explorer_controller.import_annotations()
    assert window.tree_model.rowCount() == 3

    tree = window.dataset_explorer_panel.tree
    first_index = window.tree_model.index(0, 0)
    tree.setCurrentIndex(first_index)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 0

    qtbot.mouseClick(window.dataset_explorer_panel.btn_next_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 1

    qtbot.mouseClick(window.dataset_explorer_panel.btn_next_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 2

    # Boundary: next on last row should keep selection unchanged.
    qtbot.mouseClick(window.dataset_explorer_panel.btn_next_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 2

    qtbot.mouseClick(window.dataset_explorer_panel.btn_prev_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 1

    qtbot.mouseClick(window.dataset_explorer_panel.btn_prev_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 0

    # Boundary: prev on first row should keep selection unchanged.
    qtbot.mouseClick(window.dataset_explorer_panel.btn_prev_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 0


@pytest.mark.gui
def test_add_data_accepts_npy_and_creates_frames_npy_sample(window, monkeypatch, qtbot):
    window.dataset_explorer_controller.create_new_project("classification")
    assert window.dataset_explorer_controller.json_loaded is True

    monkeypatch.setattr(
        window.dataset_explorer_controller,
        "_pick_files_or_folders_for_add_data",
        lambda _start_dir: [str(FRAME_STACK_PATH)],
    )

    window.dataset_explorer_controller.handle_add_sample()
    qtbot.wait(50)

    assert window.tree_model.rowCount() == 1
    sample = window.dataset_explorer_controller.get_sample("clip_000000")
    assert sample is not None
    assert sample["inputs"][0]["type"] == "frames_npy"
    assert sample["inputs"][0]["fps"] == pytest.approx(2.0)
    assert "frames_npy" in window.dataset_explorer_controller.modalities


@pytest.mark.gui
# Workflow: Selecting a sample emits Data ID (not path) and routes media load from Dataset Explorer.
def test_dataset_selection_emits_data_id_and_routes_media(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification")
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    emitted_ids = []
    media_calls = []
    window.dataset_explorer_controller.dataSelected.connect(lambda data_id: emitted_ids.append(data_id))
    monkeypatch.setattr(
        window.media_controller,
        "load_and_play",
        lambda file_path, auto_play=True: media_calls.append(file_path),
    )

    window.dataset_explorer_controller.import_annotations()
    first_index = window.tree_model.index(0, 0)
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert emitted_ids
    selected_data_id = emitted_ids[-1]
    selected_entry = window.dataset_explorer_controller.action_item_data[0]
    assert selected_data_id == selected_entry.get("data_id")

    assert media_calls
    assert media_calls[-1] == selected_entry.get("path")
    assert selected_data_id != media_calls[-1]


@pytest.mark.gui
def test_frames_npy_dataset_selection_routes_canonical_media_source(
    window,
    monkeypatch,
    qtbot,
    tmp_path,
):
    rel_frame_path = os.path.relpath(FRAME_STACK_PATH, start=tmp_path).replace("\\", "/")
    project_json_path = tmp_path / "frames_selection.json"
    payload = {
        "version": "2.0",
        "date": "2026-04-26",
        "task": "action_classification",
        "dataset_name": "frames_selection",
        "modalities": ["frame_npy"],
        "labels": {"action": {"type": "single_label", "labels": ["pass"]}},
        "data": [
            {
                "id": "frames_clip",
                "inputs": [{"path": rel_frame_path, "type": "frame_npy"}],
                "labels": {},
            }
        ],
    }
    project_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    media_calls = []
    monkeypatch.setattr(
        window.media_controller,
        "load_and_play",
        lambda source, auto_play=True: media_calls.append(source),
    )

    window.dataset_explorer_controller.import_annotations()
    first_index = window.tree_model.index(0, 0)
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert media_calls
    routed_source = media_calls[-1]
    assert isinstance(routed_source, dict)
    assert routed_source["type"] == "frames_npy"
    assert routed_source["path"] == str(FRAME_STACK_PATH)
    assert routed_source["fps"] == pytest.approx(2.0)
    assert window.dataset_explorer_controller.dataset_json["modalities"] == ["frames_npy"]
    assert window.dataset_explorer_controller.current_selected_input_path == str(FRAME_STACK_PATH)


@pytest.mark.gui
# Workflow: In classification multi-input samples, selecting parent routes primary media and emits Data ID.
def test_classification_multiview_selection_routes_views_and_data_id(
    window,
    monkeypatch,
    qtbot,
    tmp_path,
):
    source_a = Path(__file__).resolve().parents[1] / "data" / "test_video_1.mp4"
    source_b = Path(__file__).resolve().parents[1] / "data" / "test_video_2.mp4"
    assert source_a.exists()
    assert source_b.exists()

    # Use relative paths so JSON loading exercises path-resolution flow.
    rel_a_str = os.path.relpath(source_a, start=tmp_path).replace("\\", "/")
    rel_b_str = os.path.relpath(source_b, start=tmp_path).replace("\\", "/")

    payload = {
        "version": "2.0",
        "date": "2026-04-07",
        "task": "action_classification",
        "description": "multiview test",
        "modalities": ["video"],
        "labels": {"action": {"type": "single_label", "labels": ["pass", "shot"]}},
        "data": [
            {
                "id": "mv_1",
                "inputs": [
                    {"path": rel_a_str, "type": "video"},
                    {"path": rel_b_str, "type": "video"},
                ],
                "labels": {},
            }
        ],
    }
    project_json_path = tmp_path / "classification_multiview.json"
    project_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    emitted_ids = []
    media_calls = []
    window.dataset_explorer_controller.dataSelected.connect(lambda data_id: emitted_ids.append(data_id))
    monkeypatch.setattr(
        window.media_controller,
        "load_and_play",
        lambda file_path, auto_play=True: media_calls.append(file_path),
    )

    window.dataset_explorer_controller.import_annotations()
    parent_index = window.tree_model.index(0, 0)
    assert parent_index.isValid()
    assert window.tree_model.rowCount(parent_index) == 2
    window.dataset_explorer_panel.tree.setCurrentIndex(parent_index)
    qtbot.wait(50)

    assert emitted_ids[-1] == window.dataset_explorer_controller.action_item_data[0].get("data_id")
    assert media_calls


@pytest.mark.gui
# Workflow: Closing a loaded-but-clean project should not open a confirmation popup.
def test_close_project_when_clean_skips_confirmation_popup(window, monkeypatch):
    window.dataset_explorer_controller.create_new_project("localization")
    assert window.dataset_explorer_controller.json_loaded is True
    window.dataset_explorer_controller.is_data_dirty = False

    stop_calls = {"count": 0}
    monkeypatch.setattr(
        window.media_controller,
        "stop",
        lambda: stop_calls.__setitem__("count", stop_calls["count"] + 1),
    )
    # If a popup is shown unexpectedly, fail the test.
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QMessageBox.exec",
        lambda self: (_ for _ in ()).throw(AssertionError("Confirmation popup should not be shown")),
    )

    should_close = window.check_and_close_current_project()
    assert should_close is True
    assert stop_calls["count"] == 1


@pytest.mark.gui
# Workflow: When a filter leaves no visible samples, selection/media/annotation must be cleared.
def test_filter_with_no_visible_samples_clears_media_and_annotation(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification")
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    emitted_ids = []
    stop_calls = {"count": 0}
    window.dataset_explorer_controller.dataSelected.connect(lambda data_id: emitted_ids.append(data_id))
    monkeypatch.setattr(
        window.media_controller,
        "stop",
        lambda: stop_calls.__setitem__("count", stop_calls["count"] + 1),
    )

    window.dataset_explorer_controller.import_annotations()
    assert window.tree_model.rowCount() == 1
    assert window.dataset_explorer_panel.tree.currentIndex().isValid()

    # Default synthetic classification data is unlabelled, so hand-labelled filter hides all.
    window.dataset_explorer_panel.filter_combo.setCurrentIndex(1)
    window.dataset_explorer_controller.handle_filter_change(1)
    qtbot.wait(50)

    assert window.dataset_explorer_panel.tree.isRowHidden(0, QModelIndex()) is True
    assert window.dataset_explorer_panel.tree.currentIndex().isValid() is False
    assert emitted_ids and emitted_ids[-1] == ""
    assert stop_calls["count"] >= 1
    assert window.classification_panel.manual_box.isEnabled() is False


@pytest.mark.gui
@pytest.mark.parametrize("mode", ["description", "dense_description"])
# Workflow: For Description/Dense, hand-labelled samples remain visible in hand filter,
# while smart filter is currently expected to hide all rows.
def test_smart_filter_is_currently_empty_for_description_and_dense(
    window,
    monkeypatch,
    synthetic_project_json,
    mode,
):
    project_json_path = synthetic_project_json(mode)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    window.dataset_explorer_controller.import_annotations()
    assert window.tree_model.rowCount() == 1

    root_index = window.tree_model.index(0, 0)
    assert root_index.isValid()

    tree = window.dataset_explorer_panel.tree
    combo = window.dataset_explorer_panel.filter_combo

    combo.setCurrentIndex(1)  # Show Labelled
    window.dataset_explorer_controller.handle_filter_change(1)
    assert tree.isRowHidden(0, root_index.parent()) is False

    combo.setCurrentIndex(2)  # Show Smart Labelled
    window.dataset_explorer_controller.handle_filter_change(2)
    assert tree.isRowHidden(0, root_index.parent()) is True


@pytest.mark.gui
def test_menu_bar_contains_file_data_edit_help_menus(window):
    menu_names = [action.text().replace("&", "") for action in window.menuBar().actions()]
    assert menu_names[:4] == ["File", "Data", "Edit", "Help"]
    assert hasattr(window, "action_hf_download")
    assert hasattr(window, "action_hf_upload")
    assert window.action_hf_upload.isEnabled() is False


@pytest.mark.gui
def test_help_menu_actions_open_shortcuts_and_info_popups(window, monkeypatch):
    popup_calls = []

    def _fake_information(parent, title, text, *args, **kwargs):
        popup_calls.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr("main_window.QMessageBox.information", _fake_information)

    assert hasattr(window, "action_shortcuts")
    assert hasattr(window, "action_info")
    assert window.action_shortcuts.isEnabled() is True
    assert window.action_info.isEnabled() is True

    window.action_shortcuts.trigger()
    window.action_info.trigger()

    assert len(popup_calls) == 2

    shortcuts_title, shortcuts_text = popup_calls[0]
    info_title, info_text = popup_calls[1]

    assert shortcuts_title == "Shortcuts"
    assert "Ctrl+S" in shortcuts_text
    assert "Space" in shortcuts_text

    assert info_title == "Info"
    assert APP_DISPLAY_NAME in info_text
    assert f"Version: {APP_VERSION}" in info_text


@pytest.mark.gui
def test_hf_dialog_primary_buttons_use_action_labels(window, tmp_path):
    from ui.dialogs import HfDownloadDialog, HfUploadDialog

    opened_json = tmp_path / "opened_dataset.json"
    opened_json.write_text("{}", encoding="utf-8")
    custom_url = "https://huggingface.co/datasets/OpenSportsLab/custom/blob/main/annotations.json"
    window.dataset_explorer_controller.settings.setValue(
        HfDownloadDialog._KEY_SUCCESS_URLS,
        [
            HfDownloadDialog._AVAILABLE_DATASET_URLS[0],
            custom_url,
            custom_url,
        ],
    )
    window.dataset_explorer_controller.settings.sync()

    download_dialog = HfDownloadDialog(settings=window.dataset_explorer_controller.settings, parent=window)
    download_box = download_dialog.findChild(QDialogButtonBox)
    assert download_box is not None
    assert download_box.button(QDialogButtonBox.StandardButton.Ok).text() == "Download"
    assert download_dialog.url_combo.isEditable() is True
    combo_items = [download_dialog.url_combo.itemText(i) for i in range(download_dialog.url_combo.count())]
    assert combo_items.count(custom_url) == 1
    assert combo_items.count(HfDownloadDialog._AVAILABLE_DATASET_URLS[0]) == 1
    download_dialog.close()

    upload_dialog = HfUploadDialog(
        str(opened_json),
        settings=window.dataset_explorer_controller.settings,
        parent=window,
    )
    upload_box = upload_dialog.findChild(QDialogButtonBox)
    assert upload_box is not None
    assert upload_box.button(QDialogButtonBox.StandardButton.Ok).text() == "Upload"
    assert upload_dialog.revision_edit.text() == "main"
    assert upload_dialog.upload_as_json_checkbox.isChecked() is True
    assert upload_dialog.samples_per_shard_spin.value() == 100
    assert upload_dialog.samples_per_shard_spin.isEnabled() is False
    upload_dialog.close()


@pytest.mark.gui
def test_hf_upload_dialog_prefill_prefers_json_metadata_over_settings(window, tmp_path):
    from ui.dialogs import HfUploadDialog

    opened_json = tmp_path / "opened_dataset.json"
    opened_json.write_text("{}", encoding="utf-8")

    settings = window.dataset_explorer_controller.settings
    settings.setValue(HfUploadDialog._KEY_REPO_ID, "OpenSportsLab/from-settings")
    settings.setValue(HfUploadDialog._KEY_REVISION, "settings-branch")
    settings.setValue(HfUploadDialog._KEY_COMMIT_MESSAGE, "Settings commit message")
    settings.setValue(HfUploadDialog._KEY_TOKEN, "settings-token")
    settings.setValue(HfUploadDialog._KEY_UPLOAD_AS_JSON, False)
    settings.setValue(HfUploadDialog._KEY_SAMPLES_PER_SHARD, 64)
    settings.sync()

    upload_dialog = HfUploadDialog(
        str(opened_json),
        hf_defaults={
            "repo_id": "OpenSportsLab/from-json",
            "branch": "json-branch",
        },
        settings=settings,
        parent=window,
    )

    assert upload_dialog.repo_id_edit.text() == "OpenSportsLab/from-json"
    assert upload_dialog.revision_edit.text() == "json-branch"
    assert upload_dialog.commit_message_edit.text() == "Settings commit message"
    assert upload_dialog.token_edit.text() == "settings-token"
    assert upload_dialog.upload_as_json_checkbox.isChecked() is False
    assert upload_dialog.samples_per_shard_spin.value() == 64
    assert upload_dialog.samples_per_shard_spin.isEnabled() is True
    upload_dialog.close()


@pytest.mark.gui
def test_hf_upload_dialog_persists_upload_as_json_checkbox(window, tmp_path):
    from ui.dialogs import HfUploadDialog

    opened_json = tmp_path / "opened_dataset.json"
    opened_json.write_text("{}", encoding="utf-8")
    settings = window.dataset_explorer_controller.settings
    settings.remove(HfUploadDialog._KEY_UPLOAD_AS_JSON)
    settings.remove(HfUploadDialog._KEY_SAMPLES_PER_SHARD)
    settings.sync()

    upload_dialog = HfUploadDialog(
        str(opened_json),
        settings=settings,
        parent=window,
    )
    upload_dialog.upload_as_json_checkbox.setChecked(False)
    upload_dialog.samples_per_shard_spin.setValue(123)
    upload_dialog.repo_id_edit.setText("OpenSportsLab/test-repo")
    upload_dialog._validate_and_accept()
    upload_dialog.close()

    reloaded_dialog = HfUploadDialog(
        str(opened_json),
        settings=settings,
        parent=window,
    )
    assert reloaded_dialog.upload_as_json_checkbox.isChecked() is False
    assert reloaded_dialog.samples_per_shard_spin.value() == 123
    assert reloaded_dialog.samples_per_shard_spin.isEnabled() is True
    reloaded_dialog.close()


@pytest.mark.gui
def test_hf_upload_dialog_greys_out_samples_per_shard_when_json_selected(window, tmp_path):
    from ui.dialogs import HfUploadDialog

    opened_json = tmp_path / "opened_dataset.json"
    opened_json.write_text("{}", encoding="utf-8")

    dialog = HfUploadDialog(
        str(opened_json),
        settings=window.dataset_explorer_controller.settings,
        parent=window,
    )
    dialog.upload_as_json_checkbox.setChecked(False)
    assert dialog.samples_per_shard_spin.isEnabled() is True
    dialog.upload_as_json_checkbox.setChecked(True)
    assert dialog.samples_per_shard_spin.isEnabled() is False
    dialog.close()


@pytest.mark.gui
def test_data_menu_actions_dispatch_hf_download_and_upload(window, monkeypatch, tmp_path):
    opened_json = tmp_path / "opened_dataset.json"
    opened_json.write_text("{}", encoding="utf-8")
    window.dataset_explorer_controller.json_loaded = True
    window.dataset_explorer_controller.current_json_path = str(opened_json)
    window.update_save_export_button_state()
    assert window.action_hf_upload.isEnabled() is True

    download_payload = {
        "url": "https://huggingface.co/datasets/OpenSportsLab/repo/blob/main/annotations.json",
        "output_dir": "test_data/Classification/svfouls",
        "dry_run": False,
        "token": None,
    }
    upload_payload = {
        "repo_id": "OpenSportsLab/OSL-loc-tennis-public",
        "json_path": str(opened_json),
        "revision": "main",
        "commit_message": "Upload dataset inputs from JSON",
        "token": None,
    }

    download_calls = []
    upload_calls = []
    monkeypatch.setattr(window.hf_transfer_controller, "start_download", lambda cfg: download_calls.append(cfg) or True)
    monkeypatch.setattr(window.hf_transfer_controller, "start_upload", lambda cfg: upload_calls.append(cfg) or True)

    monkeypatch.setattr("main_window.HfDownloadDialog.exec", lambda self: self.DialogCode.Accepted)
    monkeypatch.setattr("main_window.HfDownloadDialog.get_payload", lambda self: download_payload)
    monkeypatch.setattr("main_window.HfUploadDialog.exec", lambda self: self.DialogCode.Accepted)
    monkeypatch.setattr("main_window.HfUploadDialog.get_payload", lambda self: upload_payload)

    window.action_hf_download.trigger()
    window.action_hf_upload.trigger()

    assert download_calls == [download_payload]
    assert upload_calls == [upload_payload]


@pytest.mark.gui
def test_hf_cancel_dispatches_to_download_controller(window, monkeypatch):
    calls = {"download": 0}
    window._active_hf_transfer_kind = "download"
    window._hf_busy_dialog = type("_FakeDialog", (), {"set_cancel_enabled": lambda self, enabled: None})()

    monkeypatch.setattr(
        window.hf_transfer_controller,
        "cancel_download",
        lambda: calls.__setitem__("download", calls["download"] + 1) or True,
    )

    window._on_hf_transfer_cancel_requested()
    assert calls["download"] == 1
    window._hf_busy_dialog = None


@pytest.mark.gui
def test_hf_cancel_dispatches_to_upload_controller(window, monkeypatch):
    calls = {"upload": 0}
    window._active_hf_transfer_kind = "upload"
    window._hf_busy_dialog = type("_FakeDialog", (), {"set_cancel_enabled": lambda self, enabled: None})()

    monkeypatch.setattr(
        window.hf_transfer_controller,
        "cancel_upload",
        lambda: calls.__setitem__("upload", calls["upload"] + 1) or True,
    )

    window._on_hf_transfer_cancel_requested()
    assert calls["upload"] == 1
    window._hf_busy_dialog = None


@pytest.mark.gui
def test_download_completion_prompts_and_opens_dataset_when_accepted(window, monkeypatch, tmp_path):
    downloaded_json = tmp_path / "annotations_test.json"
    downloaded_json.write_text("{}", encoding="utf-8")

    info_calls = {"count": 0}
    question_calls = {"count": 0}
    open_calls = []

    monkeypatch.setattr(
        "main_window.QMessageBox.information",
        lambda *args, **kwargs: info_calls.__setitem__("count", info_calls["count"] + 1),
    )
    monkeypatch.setattr(
        "main_window.QMessageBox.question",
        lambda *args, **kwargs: question_calls.__setitem__("count", question_calls["count"] + 1)
        or QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        window.dataset_explorer_controller,
        "open_project_from_path",
        lambda path: open_calls.append(path) or True,
    )

    window._on_hf_download_completed(
        {
            "dry_run": False,
            "output_dir": str(tmp_path),
            "downloaded_file_count": 4,
            "json_path": str(downloaded_json),
        }
    )

    assert info_calls["count"] == 1
    assert question_calls["count"] == 1
    assert open_calls == [str(downloaded_json)]


@pytest.mark.gui
def test_download_success_appends_url_to_settings_without_duplicates(window, monkeypatch, tmp_path):
    from ui.dialogs import HfDownloadDialog

    downloaded_json = tmp_path / "annotations_test.json"
    downloaded_json.write_text("{}", encoding="utf-8")
    successful_url = "https://huggingface.co/datasets/OpenSportsLab/repo/blob/main/annotations.json"

    settings = window.dataset_explorer_controller.settings
    HfDownloadDialog.add_successful_url_to_settings(settings, successful_url)
    window._last_hf_download_payload = {"url": successful_url}

    monkeypatch.setattr("main_window.QMessageBox.information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "main_window.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    window._on_hf_download_completed(
        {
            "dry_run": False,
            "output_dir": str(tmp_path),
            "downloaded_file_count": 1,
            "json_path": str(downloaded_json),
        }
    )

    saved_urls = HfDownloadDialog.get_successful_urls_from_settings(settings)
    assert saved_urls.count(successful_url) == 1


@pytest.mark.gui
def test_download_not_found_removes_url_from_settings(window, monkeypatch):
    from ui.dialogs import HfDownloadDialog

    stale_url = "https://huggingface.co/datasets/OpenSportsLab/repo/blob/main/missing.json"
    settings = window.dataset_explorer_controller.settings
    HfDownloadDialog.add_successful_url_to_settings(settings, stale_url)
    window._last_hf_download_payload = {"url": stale_url}

    monkeypatch.setattr("main_window.QMessageBox.critical", lambda *args, **kwargs: None)

    window._on_hf_download_failed(
        "404 Client Error. Entry Not Found for url: "
        "https://huggingface.co/datasets/OpenSportsLab/repo/resolve/main/missing.json."
    )

    saved_urls = HfDownloadDialog.get_successful_urls_from_settings(settings)
    assert stale_url not in saved_urls


@pytest.mark.gui
def test_upload_failure_repo_missing_prompts_create_and_retries(window, monkeypatch, tmp_path):
    opened_json = tmp_path / "opened_dataset.json"
    opened_json.write_text("{}", encoding="utf-8")
    payload = {
        "repo_id": "OpenSportsLab/OSL-test-auto-upload",
        "json_path": str(opened_json),
        "revision": "main",
        "commit_message": "Upload dataset inputs from JSON",
        "token": "hf_test_token",
    }
    window._last_hf_upload_payload = dict(payload)

    question_calls = {"count": 0}
    create_calls = []
    retry_calls = []

    monkeypatch.setattr(
        "main_window.QMessageBox.question",
        lambda *args, **kwargs: question_calls.__setitem__("count", question_calls["count"] + 1)
        or QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr("main_window.QMessageBox.critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "main_window.create_dataset_repo_on_hf",
        lambda repo_id, token=None: create_calls.append((repo_id, token)),
    )
    monkeypatch.setattr(
        window.hf_transfer_controller,
        "start_upload",
        lambda cfg: retry_calls.append(cfg) or True,
    )

    window._on_hf_upload_failed(
        "404 Client Error. Repository Not Found for url: "
        "https://huggingface.co/api/datasets/OpenSportsLab/OSL-test-auto-upload/preupload/main."
    )

    assert question_calls["count"] == 1
    assert create_calls == [("OpenSportsLab/OSL-test-auto-upload", "hf_test_token")]
    assert retry_calls == [payload]


@pytest.mark.gui
def test_upload_failure_branch_missing_prompts_create_and_retries(window, monkeypatch, tmp_path):
    opened_json = tmp_path / "opened_dataset.json"
    opened_json.write_text("{}", encoding="utf-8")
    payload = {
        "repo_id": "OpenSportsLab/OSL-test-auto-upload",
        "json_path": str(opened_json),
        "revision": "feature-branch",
        "commit_message": "Upload dataset inputs from JSON",
        "token": "hf_test_token",
    }
    window._last_hf_upload_payload = dict(payload)

    question_calls = {"count": 0}
    create_branch_calls = []
    create_repo_calls = []
    retry_calls = []

    monkeypatch.setattr(
        "main_window.QMessageBox.question",
        lambda *args, **kwargs: question_calls.__setitem__("count", question_calls["count"] + 1)
        or QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr("main_window.QMessageBox.critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "main_window.dataset_repo_exists_on_hf",
        lambda repo_id, token=None: True,
    )
    monkeypatch.setattr(
        "main_window.create_dataset_repo_on_hf",
        lambda repo_id, token=None: create_repo_calls.append((repo_id, token)),
    )
    monkeypatch.setattr(
        "main_window.create_dataset_branch_on_hf",
        lambda repo_id, branch, source_revision="main", token=None: create_branch_calls.append(
            (repo_id, branch, source_revision, token)
        ),
    )
    monkeypatch.setattr(
        window.hf_transfer_controller,
        "start_upload",
        lambda cfg: retry_calls.append(cfg) or True,
    )

    window._on_hf_upload_failed(
        "404 Client Error. Repository Not Found for url: "
        "https://huggingface.co/api/datasets/OpenSportsLab/OSL-test-auto-upload/preupload/feature-branch."
    )

    assert question_calls["count"] == 1
    assert create_repo_calls == []
    assert create_branch_calls == [
        ("OpenSportsLab/OSL-test-auto-upload", "feature-branch", "main", "hf_test_token")
    ]
    assert retry_calls == [payload]


# @pytest.mark.gui
# # Workflow: If user cancels close flow, the current workspace remains open and loaded.
# def test_close_project_cancel_keeps_workspace_open(window, monkeypatch):
#     window.dataset_explorer_controller.create_new_project("localization")
#     assert window.dataset_explorer_controller.json_loaded is True
#     assert window.center_stack.currentIndex() == 1

#     monkeypatch.setattr(window, "check_and_close_current_project", lambda: False)
#     window.dataset_explorer_controller.close_project()

#     assert window.dataset_explorer_controller.json_loaded is True
#     assert window.center_stack.currentIndex() == 1


# @pytest.mark.gui
# # Workflow: Quit action should route to dataset close when a project is loaded.
# def test_action_quit_closes_dataset_when_loaded(window, monkeypatch):
#     window.dataset_explorer_controller.create_new_project("description")
#     assert window.dataset_explorer_controller.json_loaded is True

#     close_calls = {"count": 0}
#     window_close_calls = {"count": 0}
#     monkeypatch.setattr(
#         window.dataset_explorer_controller,
#         "close_project",
#         lambda: close_calls.__setitem__("count", close_calls["count"] + 1),
#     )
#     monkeypatch.setattr(
#         window,
#         "close",
#         lambda: window_close_calls.__setitem__("count", window_close_calls["count"] + 1),
#     )

#     window.action_quit.trigger()

#     assert close_calls["count"] == 1
#     assert window_close_calls["count"] == 0


# @pytest.mark.gui
# # Workflow: Quit action should close the app window when no project is loaded.
# def test_action_quit_closes_window_when_unloaded(window, monkeypatch):
#     window.dataset_explorer_controller.json_loaded = False
#     close_calls = {"count": 0}
#     monkeypatch.setattr(window.dataset_explorer_controller, "close_project", lambda: None)
#     monkeypatch.setattr(
#         window,
#         "close",
#         lambda: close_calls.__setitem__("count", close_calls["count"] + 1),
#     )

#     window.action_quit.trigger()
#     assert close_calls["count"] == 1


# @pytest.mark.gui
# # Workflow: check_and_close_current_project should return False when dialog is canceled.
# def test_check_and_close_current_project_cancel_returns_false(window, monkeypatch):
#     window.dataset_explorer_controller.json_loaded = True
#     window.dataset_explorer_controller.is_data_dirty = True

#     def _fake_exec(self):
#         no_button = next(btn for btn in self.buttons() if btn.text() == "No")
#         no_button.click()
#         return 0

#     monkeypatch.setattr("controllers.dataset_explorer_controller.QMessageBox.exec", _fake_exec)
#     stopped = {"count": 0}
#     monkeypatch.setattr(window.media_controller, "stop", lambda: stopped.__setitem__("count", stopped["count"] + 1))

#     should_close = window.check_and_close_current_project()
#     assert should_close is False
#     assert stopped["count"] == 0
