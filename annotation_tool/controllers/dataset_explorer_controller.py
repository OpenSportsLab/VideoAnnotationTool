import copy
import datetime
import json
import os
from collections.abc import MutableMapping

from PyQt6.QtCore import QModelIndex, QObject, QSettings, QUrl, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from ui.dialogs import NewDatasetDialog
from utils import natural_sort_key


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


class _ManualAnnotationRecord(MutableMapping):
    """Mutable view of one sample's manual classification labels."""

    def __init__(self, sample: dict):
        self.sample = sample

    def _store(self) -> dict:
        return self.sample.setdefault("labels", {})

    def _read_value(self, payload):
        if isinstance(payload, dict):
            if "labels" in payload and isinstance(payload["labels"], list):
                return list(payload["labels"])
            if "label" in payload:
                return payload.get("label")
        return payload

    def _write_value(self, value):
        if isinstance(value, list):
            return {"labels": list(value), "confidence": 1.0, "manual": True}
        return {"label": value, "confidence": 1.0, "manual": True}

    def to_dict(self) -> dict:
        output = {}
        for head, payload in self.sample.get("labels", {}).items():
            value = self._read_value(payload)
            if value not in (None, "", []):
                output[head] = value
        return output

    def __deepcopy__(self, memo):
        return copy.deepcopy(self.to_dict(), memo)

    def __getitem__(self, key):
        store = self.sample.get("labels", {})
        if key not in store:
            raise KeyError(key)
        return self._read_value(store[key])

    def __setitem__(self, key, value):
        if value in (None, "", []):
            self.__delitem__(key)
            return
        self._store()[key] = self._write_value(value)

    def __delitem__(self, key):
        store = self.sample.get("labels", {})
        if key not in store:
            raise KeyError(key)
        del store[key]
        if not store:
            self.sample.pop("labels", None)

    def __iter__(self):
        return iter(self.to_dict())

    def __len__(self):
        return len(self.to_dict())


class _ManualAnnotationsProxy(MutableMapping):
    """Path-keyed compatibility layer backed by `dataset_json.data[].labels`."""

    def __init__(self, owner):
        self.owner = owner

    def _sample(self, path: str) -> dict:
        sample = self.owner.get_sample_by_path(path)
        if sample is None:
            raise KeyError(path)
        return sample

    def __getitem__(self, path):
        return _ManualAnnotationRecord(self._sample(path))

    def __setitem__(self, path, value):
        sample = self._sample(path)
        if not value:
            sample.pop("labels", None)
            return
        store = sample.setdefault("labels", {})
        store.clear()
        for head, item_value in dict(value).items():
            _ManualAnnotationRecord(sample)[head] = item_value

    def __delitem__(self, path):
        sample = self._sample(path)
        if "labels" not in sample:
            raise KeyError(path)
        sample.pop("labels", None)

    def __iter__(self):
        for entry in self.owner.action_item_data:
            sample = entry["sample_ref"]
            if _ManualAnnotationRecord(sample):
                yield entry["path"]

    def __len__(self):
        return sum(1 for _ in self)


class _SampleDictProxy(MutableMapping):
    """Path-keyed compatibility layer backed by a sample dict field."""

    def __init__(self, owner, field_name: str):
        self.owner = owner
        self.field_name = field_name

    def _sample(self, path: str) -> dict:
        sample = self.owner.get_sample_by_path(path)
        if sample is None:
            raise KeyError(path)
        return sample

    def __getitem__(self, path):
        sample = self._sample(path)
        if self.field_name not in sample:
            raise KeyError(path)
        return sample[self.field_name]

    def __setitem__(self, path, value):
        sample = self._sample(path)
        if not value:
            sample.pop(self.field_name, None)
            return
        sample[self.field_name] = value

    def __delitem__(self, path):
        sample = self._sample(path)
        if self.field_name not in sample:
            raise KeyError(path)
        sample.pop(self.field_name, None)

    def __iter__(self):
        for entry in self.owner.action_item_data:
            if entry["sample_ref"].get(self.field_name):
                yield entry["path"]

    def __len__(self):
        return sum(1 for _ in self)


class _SampleListProxy(MutableMapping):
    """Path-keyed compatibility layer backed by a sample list field."""

    def __init__(self, owner, field_name: str):
        self.owner = owner
        self.field_name = field_name

    def _sample(self, path: str) -> dict:
        sample = self.owner.get_sample_by_path(path)
        if sample is None:
            raise KeyError(path)
        return sample

    def __getitem__(self, path):
        sample = self._sample(path)
        if self.field_name not in sample:
            raise KeyError(path)
        return sample[self.field_name]

    def __setitem__(self, path, value):
        sample = self._sample(path)
        if value is None:
            sample.pop(self.field_name, None)
            return
        sample[self.field_name] = list(value)

    def __delitem__(self, path):
        sample = self._sample(path)
        if self.field_name not in sample:
            raise KeyError(path)
        sample.pop(self.field_name, None)

    def __iter__(self):
        for entry in self.owner.action_item_data:
            if entry["sample_ref"].get(self.field_name):
                yield entry["path"]

    def __len__(self):
        return sum(1 for _ in self)


class DatasetExplorerController(QObject):
    """
    Canonical dataset owner.
    - Holds one `dataset_json` document as the persisted source of truth.
    - Exposes router/model compatibility methods so the rest of the app can migrate
      without another orchestration layer.
    """

    dataSelected = pyqtSignal(str)

    SETTINGS_ORG = "OpenSportsLab"
    SETTINGS_APP = "VideoAnnotationTool"
    RECENT_DATASETS_KEY = "welcome/recent_datasets"
    MAX_RECENT_DATASETS_DISPLAY = 10

    HEADER_EDITABLE_KEYS = (
        "version",
        "date",
        "task",
        "dataset_name",
        "description",
        "modalities",
        "metadata",
    )
    HEADER_EXCLUDED_KEYS = {"data", "labels"}
    TASK_TAB_INDEX = {
        "classification": 0,
        "action_classification": 0,
        "localization": 1,
        "action_spotting": 1,
        "spotting": 1,
        "description": 2,
        "video_captioning": 2,
        "captioning": 2,
        "dense_description": 3,
        "dense_video_captioning": 3,
        "dense_captioning": 3,
    }

    def __init__(self, main_window, panel, tree_model, media_controller=None):
        super().__init__()
        self.main = main_window
        self.panel = panel
        self.tree_model = tree_model
        self.media_controller = media_controller

        self.settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

        self.dataset_json = {}
        self.current_json_path = None
        self.project_root = None
        self.current_working_directory = None
        self.json_loaded = False
        self.is_data_dirty = False
        self.is_multi_view = False

        self.undo_stack = []
        self.redo_stack = []

        self.action_item_data = []
        self.action_item_map = {}
        self.action_path_to_name = {}
        self.action_id_to_path = {}
        self.action_id_to_item = {}
        self.sample_id_to_sample = {}
        self.sample_id_to_entry = {}

        self.current_selected_sample_id = ""
        self.current_selected_input_path = None

        self.manual_annotations = _ManualAnnotationsProxy(self)
        self.smart_annotations = _SampleDictProxy(self, "smart_labels")
        self.localization_events = _SampleListProxy(self, "events")
        self.smart_localization_events = _SampleListProxy(self, "smart_events")
        self.dense_description_events = _SampleListProxy(self, "dense_captions")

        self._setup_connections()

    # ------------------------------------------------------------------
    # Compatibility properties
    # ------------------------------------------------------------------
    @property
    def label_definitions(self) -> dict:
        return self.dataset_json.setdefault("labels", {})

    @label_definitions.setter
    def label_definitions(self, value):
        self.dataset_json["labels"] = value if isinstance(value, dict) else {}

    @property
    def current_task_name(self) -> str:
        return (
            self.dataset_json.get("task")
            or self.dataset_json.get("dataset_name")
            or "Untitled Dataset"
        )

    @current_task_name.setter
    def current_task_name(self, value: str):
        if value:
            self.dataset_json["task"] = value

    @property
    def project_description(self) -> str:
        return self.dataset_json.get("description", "")

    @project_description.setter
    def project_description(self, value: str):
        self.dataset_json["description"] = value or ""

    @property
    def modalities(self):
        return self.dataset_json.setdefault("modalities", ["video"])

    @modalities.setter
    def modalities(self, value):
        self.dataset_json["modalities"] = list(value) if isinstance(value, list) else ["video"]

    @property
    def project_header_known(self) -> dict:
        return {
            key: copy.deepcopy(self.dataset_json[key])
            for key in self.HEADER_EDITABLE_KEYS
            if key in self.dataset_json
        }

    @property
    def project_header_unknown(self) -> dict:
        return {
            key: copy.deepcopy(value)
            for key, value in self.dataset_json.items()
            if key not in self.HEADER_EDITABLE_KEYS and key not in self.HEADER_EXCLUDED_KEYS
        }

    @property
    def project_header_draft(self) -> dict:
        return {}

    @project_header_draft.setter
    def project_header_draft(self, _value):
        return

    @property
    def desc_global_metadata(self) -> dict:
        return {
            "version": self.dataset_json.get("version", "2.0"),
            "date": self.dataset_json.get("date", datetime.date.today().isoformat()),
            "metadata": copy.deepcopy(self.dataset_json.get("metadata", {})),
        }

    @desc_global_metadata.setter
    def desc_global_metadata(self, value: dict):
        if not isinstance(value, dict):
            return
        for key in ("version", "date"):
            if key in value:
                self.dataset_json[key] = value[key]
        if "metadata" in value and isinstance(value["metadata"], dict):
            self.dataset_json["metadata"] = copy.deepcopy(value["metadata"])

    @property
    def dense_global_metadata(self) -> dict:
        return {
            "version": self.dataset_json.get("version", "2.0"),
            "date": self.dataset_json.get("date", datetime.date.today().isoformat()),
            "metadata": copy.deepcopy(self.dataset_json.get("metadata", {})),
        }

    @dense_global_metadata.setter
    def dense_global_metadata(self, value: dict):
        self.desc_global_metadata = value

    # ------------------------------------------------------------------
    # Basic state helpers
    # ------------------------------------------------------------------
    def _setup_connections(self):
        self.panel.addDataRequested.connect(self.handle_add_sample)
        self.panel.clear_btn.clicked.connect(self.handle_clear_workspace)
        self.panel.removeItemRequested.connect(self.handle_remove_item)
        self.panel.filter_combo.currentIndexChanged.connect(self.handle_filter_change)
        self.panel.sampleNavigateRequested.connect(self.navigate_samples)
        self.panel.headerDraftChanged.connect(self._on_header_draft_changed)
        if hasattr(self.panel, "header_tabs"):
            self.panel.header_tabs.currentChanged.connect(self._on_explorer_tab_changed)
        self.panel.tree.selectionModel().currentChanged.connect(self._on_selection_changed)

    def reset(self, full_reset: bool = False):
        self.current_json_path = None
        self.project_root = None
        self.current_working_directory = None
        self.json_loaded = False
        self.is_data_dirty = False
        self.is_multi_view = False

        self.undo_stack = []
        self.redo_stack = []

        self.action_item_data = []
        self.action_item_map = {}
        self.action_path_to_name = {}
        self.action_id_to_path = {}
        self.action_id_to_item = {}
        self.sample_id_to_sample = {}
        self.sample_id_to_entry = {}

        self.current_selected_sample_id = ""
        self.current_selected_input_path = None

        if full_reset:
            self.dataset_json = {}

    def push_undo(self, cmd_type, **kwargs):
        self.undo_stack.append({"type": cmd_type, **kwargs})
        self.redo_stack.clear()
        self.is_data_dirty = True

    def ensure_data_ids(self):
        self._ensure_sample_ids()
        self._rebuild_runtime_index()

    def get_samples(self):
        if not isinstance(self.dataset_json, dict):
            self.dataset_json = {}
        data = self.dataset_json.get("data")
        if not isinstance(data, list):
            data = []
            self.dataset_json["data"] = data
        return data

    def get_sample(self, sample_id: str):
        if not sample_id:
            return None
        sample = self.sample_id_to_sample.get(sample_id)
        if sample is not None:
            return sample
        for candidate in self.get_samples():
            if candidate.get("id") == sample_id:
                self.sample_id_to_sample[sample_id] = candidate
                return candidate
        return None

    def get_sample_by_path(self, path: str):
        if not path:
            return None
        for entry in self.action_item_data:
            if entry.get("path") == path:
                return entry["sample_ref"]
        return None

    def get_item_by_id(self, data_id: str):
        return self.action_id_to_item.get(data_id)

    def get_path_by_id(self, data_id: str):
        return self.action_id_to_path.get(data_id)

    def get_sources_by_id(self, data_id: str):
        entry = self.action_id_to_item.get(data_id)
        if not entry:
            return []
        return list(entry.get("source_files", []))

    def get_data_id_by_path(self, path: str):
        for entry in self.action_item_data:
            if entry.get("path") == path:
                return entry.get("data_id")
        return None

    def has_action_path(self, path: str) -> bool:
        return self.get_data_id_by_path(path) is not None

    def has_action_name(self, name: str) -> bool:
        return any(entry.get("name") == name for entry in self.action_item_data)

    def has_description_path(self, path: str) -> bool:
        return self.has_action_path(path)

    def add_action_item(self, name: str, path: str, source_files=None, **extra_fields):
        sample_id = str(extra_fields.pop("data_id", None) or extra_fields.get("id") or name or os.path.basename(path))
        sample_id = self._make_unique_sample_id(sample_id)
        inputs = extra_fields.pop("inputs", None)
        if not isinstance(inputs, list):
            paths = list(source_files or [path])
            inputs = [{"type": "video", "path": src} for src in paths]

        sample = {"id": sample_id, "inputs": inputs}
        sample.update(extra_fields)
        self.get_samples().append(sample)
        self._rebuild_runtime_index()
        return self.sample_id_to_entry.get(sample_id)

    def remove_action_item_by_path(self, path: str) -> bool:
        before = len(self.get_samples())
        self.dataset_json["data"] = [
            sample for sample in self.get_samples()
            if self._primary_runtime_path_for_sample(sample) != path
        ]
        removed = len(self.get_samples()) != before
        if removed:
            self._rebuild_runtime_index()
        return removed

    def remove_description_action_by_path(self, path: str):
        removed = self.remove_action_item_by_path(path)
        return [path] if removed else []

    def clear_annotations_for_path(self, path: str):
        sample = self.get_sample_by_path(path)
        if not sample:
            return
        for field in ("labels", "smart_labels", "events", "smart_events", "captions", "dense_captions"):
            sample.pop(field, None)

    def is_action_done(self, action_path: str) -> bool:
        sample = self.get_sample_by_path(action_path)
        if not sample:
            return False
        if _ManualAnnotationRecord(sample):
            return True
        if sample.get("events"):
            return True
        if sample.get("dense_captions"):
            return True
        captions = sample.get("captions", [])
        if any(isinstance(cap, dict) and str(cap.get("text", "")).strip() for cap in captions):
            return True
        return False

    def set_sample_captions(self, sample_id: str, captions):
        sample = self.get_sample(sample_id)
        if sample is None:
            return
        if captions:
            sample["captions"] = captions
        else:
            sample.pop("captions", None)
        self._rebuild_runtime_index()

    # ------------------------------------------------------------------
    # Project lifecycle and recents
    # ------------------------------------------------------------------
    def create_new_project_flow(self):
        dialog = NewDatasetDialog(self.main)
        if not dialog.exec():
            return

        if not self.check_and_close_current_project():
            return

        self.main.reset_all_managers()
        self.create_new_project(multiview_grouping=dialog.is_multi_view)

    def import_annotations(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.main,
            "Select Project JSON",
            "",
            "JSON Files (*.json)",
        )
        if file_path:
            self.open_project_from_path(file_path)

    def open_project_from_path(self, file_path: str) -> bool:
        normalized_path = self._normalize_project_path(file_path)
        if not normalized_path:
            return False

        if not os.path.exists(normalized_path):
            QMessageBox.warning(
                self.main,
                "Dataset Not Found",
                f"Dataset file does not exist and will be removed from recents:\n{normalized_path}",
            )
            self._remove_recent_project(normalized_path)
            return False

        if not self.check_and_close_current_project():
            return False

        self.main.reset_all_managers()

        try:
            with open(normalized_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            QMessageBox.critical(self.main, "Error", f"Invalid JSON: {exc}")
            return False

        if not self.load_project(data, normalized_path):
            QMessageBox.critical(self.main, "Error", "Could not load dataset JSON.")
            return False

        self._add_recent_project(normalized_path)
        return True

    def load_project(self, data, file_path):
        normalized, error = self._normalize_dataset_json(data)
        if error:
            QMessageBox.critical(self.main, "Invalid Dataset", error)
            return False

        self.reset(full_reset=True)
        self.dataset_json = normalized
        self.current_json_path = file_path
        self.project_root = os.path.dirname(os.path.abspath(file_path))
        self.current_working_directory = self.project_root
        self.json_loaded = True
        self.is_data_dirty = False
        self.is_multi_view = any(len(sample.get("inputs", [])) > 1 for sample in self.get_samples())

        self._rebuild_runtime_index()
        self.main.show_workspace()
        initial_tab = self._tab_index_for_task(self.dataset_json.get("task"))
        if initial_tab is not None:
            self.main.right_tabs.setCurrentIndex(initial_tab)
        self._refresh_header_panel()
        self._refresh_schema_panels()
        self.populate_tree()
        self.main.update_save_export_button_state()
        self.main.show_temp_msg(
            "Loaded",
            f"Loaded {len(self.action_item_data)} samples.",
        )
        return True

    def create_new_project(self, mode=None, multiview_grouping=False):
        initial_tab = self.main.right_tabs.currentIndex()
        if isinstance(mode, str):
            mapped_tab = self._tab_index_for_task(mode)
            if mapped_tab is not None:
                initial_tab = mapped_tab

        self.reset(full_reset=True)
        self.dataset_json = self._default_dataset_json()
        self.json_loaded = True
        self.is_data_dirty = True
        self.is_multi_view = bool(multiview_grouping)
        self._rebuild_runtime_index()

        self.main.show_workspace()
        self.main.right_tabs.setCurrentIndex(initial_tab)
        self._refresh_header_panel()
        self._refresh_schema_panels()
        self.populate_tree()
        self.main.update_save_export_button_state()
        self.main.show_temp_msg("New Dataset", "Blank dataset ready.")

    def close_project(self):
        if not self.check_and_close_current_project():
            return

        self.main.reset_all_managers()
        self.reset(full_reset=True)
        self.panel.clear_header_rows()
        if hasattr(self.panel, "clear_raw_json_text"):
            self.panel.clear_raw_json_text()
        self.main.update_save_export_button_state()
        self.main.show_welcome_view()
        self.main.show_temp_msg("Project Closed", "Returned to Home Screen", duration=1000)

    def check_and_close_current_project(self) -> bool:
        if not self.json_loaded:
            return True
        if not self.is_data_dirty:
            self.media_controller.stop()
            return True

        action = self._prompt_unsaved_close_action()
        if action == "save":
            if not self.save_project():
                return False
        elif action == "save_as":
            if not self.export_project():
                return False
        elif action == "discard":
            pass
        else:
            return False

        self.media_controller.stop()
        return True

    def _prompt_unsaved_close_action(self) -> str:
        msg_box = QMessageBox(self.main)
        msg_box.setWindowTitle("Unsaved Changes")
        msg_box.setText("Unsaved changes will be lost. How do you want to proceed?")

        btn_save = msg_box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        btn_save_as = msg_box.addButton("Save As", QMessageBox.ButtonRole.ActionRole)
        btn_discard = msg_box.addButton("Close Without Saving", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(btn_save)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == btn_save:
            return "save"
        if clicked == btn_save_as:
            return "save_as"
        if clicked == btn_discard:
            return "discard"
        if clicked == btn_cancel:
            return "cancel"
        return "cancel"

    def save_project(self):
        if self.main.right_tabs.currentIndex() == 2:
            self.main.desc_editor_controller.save_current_annotation()

        if not self.current_json_path:
            return self.export_project()
        return self._write_dataset_json(self.current_json_path)

    def export_project(self):
        if self.main.right_tabs.currentIndex() == 2:
            self.main.desc_editor_controller.save_current_annotation()

        path, _ = QFileDialog.getSaveFileName(
            self.main,
            "Save Dataset As",
            self.current_json_path or "",
            "JSON (*.json)",
        )
        if not path:
            return False
        return self._write_dataset_json(path)

    def get_recent_projects(self):
        return self._read_recent_projects()[: self.MAX_RECENT_DATASETS_DISPLAY]

    def get_max_recent_datasets_displayed(self):
        return self.MAX_RECENT_DATASETS_DISPLAY

    def remove_all_recent_project(self):
        self.settings.setValue(self.RECENT_DATASETS_KEY, [])
        self.settings.sync()

    def remove_recent_project(self, path: str):
        self._remove_recent_project(path)

    def _read_recent_projects(self):
        raw_value = self.settings.value(self.RECENT_DATASETS_KEY, [])
        if isinstance(raw_value, str):
            paths = [raw_value]
        elif isinstance(raw_value, (list, tuple)):
            paths = [str(path) for path in raw_value if path]
        else:
            paths = []
        return [self._normalize_project_path(path) for path in paths if path]

    def _add_recent_project(self, path: str):
        normalized_path = self._normalize_project_path(path)
        if not normalized_path:
            return
        existing = self._read_recent_projects()
        target_key = self._path_key(normalized_path)
        updated = [normalized_path, *[p for p in existing if self._path_key(p) != target_key]]
        self._write_recent_projects(updated)

    def _remove_recent_project(self, path: str):
        normalized_path = self._normalize_project_path(path)
        if not normalized_path:
            return
        target_key = self._path_key(normalized_path)
        updated = [p for p in self._read_recent_projects() if self._path_key(p) != target_key]
        self._write_recent_projects(updated)

    def _write_recent_projects(self, paths):
        self.settings.setValue(self.RECENT_DATASETS_KEY, paths)
        self.settings.sync()

    def _normalize_project_path(self, path: str) -> str:
        if not path:
            return ""
        return os.path.abspath(os.path.normpath(path))

    def _path_key(self, path: str) -> str:
        return os.path.normcase(os.path.normpath(path))

    def _tab_index_for_task(self, task_name):
        if not isinstance(task_name, str):
            return None
        normalized = task_name.strip().lower().replace("-", "_").replace(" ", "_")
        return self.TASK_TAB_INDEX.get(normalized)

    # ------------------------------------------------------------------
    # Header and JSON tabs
    # ------------------------------------------------------------------
    def _known_header_for_panel(self):
        return self.project_header_known

    def _unknown_header_for_panel(self):
        return self.project_header_unknown

    def _refresh_header_panel(self):
        self.panel.set_header_rows(
            known=self._known_header_for_panel(),
            unknown=self._unknown_header_for_panel(),
            draft={},
            key_order=list(self.HEADER_EDITABLE_KEYS),
        )
        self._refresh_json_preview()

    def _refresh_json_preview(self):
        if hasattr(self.panel, "set_raw_json_text"):
            if self.json_loaded:
                self.panel.set_raw_json_text(json.dumps(self.dataset_json, indent=2, ensure_ascii=False))
            else:
                self.panel.clear_raw_json_text()

    def _on_explorer_tab_changed(self, index: int):
        if not hasattr(self.panel, "header_tabs"):
            return
        if self.panel.header_tabs.tabText(index).strip().lower() == "json":
            self._refresh_json_preview()

    def _on_header_draft_changed(self, draft: dict):
        if not self.json_loaded or not isinstance(draft, dict):
            return
        changed = False
        for key, value in draft.items():
            if key in self.HEADER_EDITABLE_KEYS:
                self.dataset_json[key] = copy.deepcopy(value)
                changed = True
        if not changed:
            return
        self.is_data_dirty = True
        self.main.update_save_export_button_state()
        self._refresh_header_panel()
        self._refresh_schema_panels()

    # ------------------------------------------------------------------
    # Runtime/sample indexing
    # ------------------------------------------------------------------
    def _default_dataset_json(self):
        today = datetime.date.today().isoformat()
        return {
            "version": "2.0",
            "date": today,
            "task": "video_annotation",
            "dataset_name": "Untitled Dataset",
            "description": "",
            "modalities": ["video"],
            "metadata": {},
            "labels": {},
            "data": [],
        }

    def _normalize_dataset_json(self, data):
        if not isinstance(data, dict):
            return None, "Root JSON must be an object."

        normalized = copy.deepcopy(data)
        defaults = self._default_dataset_json()
        for key, value in defaults.items():
            if key not in normalized:
                normalized[key] = copy.deepcopy(value)

        if not isinstance(normalized.get("labels"), dict):
            normalized["labels"] = {}
        if not isinstance(normalized.get("metadata"), dict):
            normalized["metadata"] = {}
        if not isinstance(normalized.get("modalities"), list):
            normalized["modalities"] = ["video"]
        if not isinstance(normalized.get("data"), list):
            return None, "Top-level 'data' must be a list."

        seen_ids = set()
        cleaned_data = []
        for index, raw_sample in enumerate(normalized["data"]):
            if not isinstance(raw_sample, dict):
                continue
            sample = raw_sample
            sample_id = sample.get("id") or sample.get("name") or f"sample_{index + 1}"
            sample_id = self._make_unique_sample_id(str(sample_id), seen_ids)
            seen_ids.add(sample_id)
            sample["id"] = sample_id

            inputs = sample.get("inputs")
            if not isinstance(inputs, list):
                inputs = []
                sample["inputs"] = inputs
            sample["metadata"] = sample.get("metadata", {}) if isinstance(sample.get("metadata"), dict) else {}

            if "events" in sample and isinstance(sample["events"], list):
                for event in sample["events"]:
                    if isinstance(event, dict):
                        event["position_ms"] = _safe_int(event.get("position_ms", 0))
            if "smart_events" in sample and isinstance(sample["smart_events"], list):
                for event in sample["smart_events"]:
                    if isinstance(event, dict):
                        event["position_ms"] = _safe_int(event.get("position_ms", 0))
            if "dense_captions" in sample and isinstance(sample["dense_captions"], list):
                for event in sample["dense_captions"]:
                    if isinstance(event, dict):
                        event["position_ms"] = _safe_int(event.get("position_ms", 0))

            cleaned_data.append(sample)

        normalized["data"] = cleaned_data
        return normalized, ""

    def _ensure_sample_ids(self):
        used = set()
        for index, sample in enumerate(self.get_samples()):
            sample_id = sample.get("id") or sample.get("name") or f"sample_{index + 1}"
            sample_id = self._make_unique_sample_id(str(sample_id), used)
            used.add(sample_id)
            sample["id"] = sample_id

    def _make_unique_sample_id(self, base: str, reserved=None):
        used = set(reserved or set())
        if reserved is None:
            used.update(
                str(sample.get("id"))
                for sample in self.get_samples()
                if isinstance(sample, dict) and sample.get("id")
            )
        if base not in used:
            return base
        idx = 2
        while f"{base}__{idx}" in used:
            idx += 1
        return f"{base}__{idx}"

    def _display_name_for_sample(self, sample: dict) -> str:
        return str(sample.get("id") or "sample")

    def _raw_source_paths_for_sample(self, sample: dict):
        raw_paths = []
        for input_item in sample.get("inputs", []):
            if not isinstance(input_item, dict):
                continue
            raw_path = input_item.get("path")
            if raw_path:
                raw_paths.append(str(raw_path))
        return raw_paths

    def _resolve_media_path(self, path):
        if not path:
            return None
        path = str(path)
        if os.path.isabs(path):
            return os.path.normpath(path)
        base_dir = self.project_root or self.current_working_directory or os.getcwd()
        return os.path.normpath(os.path.join(base_dir, path))

    def _resolved_source_paths_for_sample(self, sample: dict):
        return [self._resolve_media_path(path) for path in self._raw_source_paths_for_sample(sample)]

    def _primary_runtime_path_for_sample(self, sample: dict):
        sources = self._resolved_source_paths_for_sample(sample)
        if sources:
            return sources[0]
        return f"sample://{sample.get('id', 'unknown')}"

    def _rebuild_runtime_index(self):
        self._ensure_sample_ids()

        self.action_item_data = []
        self.action_path_to_name = {}
        self.action_id_to_path = {}
        self.action_id_to_item = {}
        self.sample_id_to_sample = {}
        self.sample_id_to_entry = {}

        for sample in self.get_samples():
            sample_id = str(sample.get("id"))
            source_files = self._resolved_source_paths_for_sample(sample)
            path = self._primary_runtime_path_for_sample(sample)
            entry = {
                "name": self._display_name_for_sample(sample),
                "path": path,
                "source_files": source_files or [path],
                "data_id": sample_id,
                "id": sample_id,
                "inputs": sample.get("inputs", []),
                "captions": sample.get("captions", []),
                "metadata": sample.get("metadata", {}),
                "sample_ref": sample,
            }
            self.action_item_data.append(entry)
            self.action_path_to_name[path] = entry["name"]
            self.action_id_to_path[sample_id] = path
            self.action_id_to_item[sample_id] = entry
            self.sample_id_to_sample[sample_id] = sample
            self.sample_id_to_entry[sample_id] = entry

        self.action_item_data.sort(key=lambda item: natural_sort_key(item.get("name", "")))

    def _sample_from_index(self, index: QModelIndex):
        if not index.isValid():
            return None
        action_idx = self._get_action_index(index)
        if not action_idx.isValid():
            return None
        sample_id = action_idx.data(getattr(self.tree_model, "DataIdRole", 0x0101))
        return self.get_sample(sample_id)

    # ------------------------------------------------------------------
    # Tree population and selection
    # ------------------------------------------------------------------
    def populate_tree(self):
        self._rebuild_runtime_index()
        self.tree_model.clear()
        self.action_item_map.clear()

        sorted_items = sorted(
            self.action_item_data,
            key=lambda item: natural_sort_key(item.get("name", "")),
        )

        for entry in sorted_items:
            item = self.tree_model.add_entry(
                name=entry["name"],
                path=entry["path"],
                source_files=entry.get("source_files"),
                data_id=entry["data_id"],
            )
            self.action_item_map[entry["path"]] = item
            self.update_item_status(entry["path"])

        self.handle_filter_change(self.panel.filter_combo.currentIndex())

        if self.tree_model.rowCount() > 0:
            first_index = self.tree_model.index(0, 0)
            if first_index.isValid():
                self.panel.tree.setCurrentIndex(first_index)
        else:
            self._clear_selection_for_empty_filtered_view()

        self._refresh_json_preview()
        if hasattr(self.main, "classification_editor_controller"):
            self.main.classification_editor_controller.sync_batch_inference_dropdowns()

    def update_item_status(self, action_path: str):
        item = self.action_item_map.get(action_path)
        if not item:
            return
        done_icon = getattr(self.main, "done_icon", None)
        empty_icon = getattr(self.main, "empty_icon", None)
        if done_icon is not None and empty_icon is not None:
            item.setIcon(done_icon if self.is_action_done(action_path) else empty_icon)

    def _set_annotation_panels_enabled(self, enabled: bool):
        self.main.classification_panel.manual_box.setEnabled(enabled)
        self.main.localization_panel.setEnabled(enabled)
        self.main.description_panel.setEnabled(enabled)
        self.main.dense_panel.setEnabled(enabled)

    def _active_mode_idx(self) -> int:
        return self.main.right_tabs.currentIndex()

    def _get_action_index(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        if index.parent().isValid():
            return index.parent()
        return index

    def _path_from_index(self, index: QModelIndex):
        action_idx = self._get_action_index(index)
        if not action_idx.isValid():
            return None, QModelIndex()
        return action_idx.data(getattr(self.tree_model, "FilePathRole", 0x0100)), action_idx

    def _remove_tree_row(self, action_idx: QModelIndex):
        if action_idx.isValid():
            self.tree_model.removeRow(action_idx.row(), action_idx.parent())

    def _clear_selection_for_empty_filtered_view(self):
        self.current_selected_sample_id = ""
        self.current_selected_input_path = None
        self.media_controller.stop()
        self.main.center_panel.player.setSource(QUrl())
        self.main.center_panel.set_markers([])

        current_idx = self.panel.tree.currentIndex()
        if current_idx.isValid():
            self.panel.tree.setCurrentIndex(QModelIndex())
        else:
            self._set_annotation_panels_enabled(False)
            self.dataSelected.emit("")

    def _on_selection_changed(self, current, _previous):
        self._set_annotation_panels_enabled(current.isValid())
        if not current.isValid():
            self.current_selected_sample_id = ""
            self.current_selected_input_path = None
            self.dataSelected.emit("")
            return

        action_idx = self._get_action_index(current)
        if not action_idx.isValid():
            self.current_selected_sample_id = ""
            self.current_selected_input_path = None
            self.dataSelected.emit("")
            return

        sample_id = action_idx.data(getattr(self.tree_model, "DataIdRole", 0x0101))
        if not sample_id:
            self.current_selected_sample_id = ""
            self.current_selected_input_path = None
            self.dataSelected.emit("")
            return

        selected_path = current.data(getattr(self.tree_model, "FilePathRole", 0x0100))
        self.current_selected_sample_id = sample_id
        self.current_selected_input_path = selected_path or self.get_path_by_id(sample_id)
        self._route_media_for_selection(current, sample_id)
        self.dataSelected.emit(sample_id)

    def _route_media_for_selection(self, selected_idx: QModelIndex, sample_id: str):
        media_paths = [path for path in self.get_sources_by_id(sample_id) if path]
        if not media_paths:
            return

        center_panel = self.main.center_panel
        if len(media_paths) > 1 and self.is_multi_view and self._active_mode_idx() == 0:
            self.main.center_panel.show_all_views(media_paths)
        elif hasattr(center_panel, "view_layout") and hasattr(center_panel, "single_view_widget"):
            center_panel.view_layout.setCurrentWidget(center_panel.single_view_widget)

        preferred = selected_idx.data(getattr(self.tree_model, "FilePathRole", 0x0100))
        primary_path = preferred or media_paths[0]
        self.current_selected_input_path = primary_path
        self.main.media_controller.load_and_play(primary_path)

    def handle_active_mode_changed(self):
        self.handle_filter_change(self.panel.filter_combo.currentIndex())
        current_idx = self.panel.tree.currentIndex()
        if not current_idx.isValid() or not self.current_selected_sample_id:
            self.dataSelected.emit("")
            return
        self._route_media_for_selection(current_idx, self.current_selected_sample_id)
        self.dataSelected.emit(self.current_selected_sample_id)

    def navigate_samples(self, step: int):
        tree = self.panel.tree
        current = tree.currentIndex()
        if not current.isValid():
            return

        current_top = self._get_action_index(current)
        if not current_top.isValid():
            return

        row = current_top.row() + (1 if step > 0 else -1)
        root = QModelIndex()

        while 0 <= row < self.tree_model.rowCount(root):
            if not tree.isRowHidden(row, root):
                next_idx = self.tree_model.index(row, 0, root)
                if next_idx.isValid():
                    tree.setCurrentIndex(next_idx)
                    tree.scrollTo(next_idx)
                    return
            row += 1 if step > 0 else -1

    def handle_filter_change(self, index):
        root = self.tree_model.invisibleRootItem()
        first_visible_idx = QModelIndex()
        for row in range(root.rowCount()):
            item = root.child(row)
            if item is None:
                continue

            path = item.data(getattr(self.tree_model, "FilePathRole", 0x0100))
            data_id = item.data(getattr(self.tree_model, "DataIdRole", 0x0101))
            hand_labelled, smart_labelled = self._label_state_for_mode(path, data_id)

            hide = False
            if index == 1 and not hand_labelled:
                hide = True
            elif index == 2 and not smart_labelled:
                hide = True
            elif index == 3 and (hand_labelled or smart_labelled):
                hide = True

            self.panel.tree.setRowHidden(row, QModelIndex(), hide)
            if not hide and not first_visible_idx.isValid():
                first_visible_idx = self.tree_model.index(row, 0, QModelIndex())

        if first_visible_idx.isValid():
            current_idx = self._get_action_index(self.panel.tree.currentIndex())
            current_visible = current_idx.isValid() and not self.panel.tree.isRowHidden(current_idx.row(), QModelIndex())
            if not current_visible:
                self.panel.tree.setCurrentIndex(first_visible_idx)
                self.panel.tree.scrollTo(first_visible_idx)
            return

        self._clear_selection_for_empty_filtered_view()

    def _label_state_for_mode(self, path: str, data_id: str):
        sample = self.get_sample(data_id)
        if not sample:
            return False, False

        mode_idx = self._active_mode_idx()
        if mode_idx == 0:
            hand = bool(_ManualAnnotationRecord(sample))
            smart = bool(sample.get("smart_labels", {}).get("_confirmed", False))
            return hand, smart
        if mode_idx == 1:
            return bool(sample.get("events")), bool(sample.get("smart_events"))
        if mode_idx == 2:
            captions = sample.get("captions", [])
            hand = any(isinstance(cap, dict) and str(cap.get("text", "")).strip() for cap in captions)
            return hand, False
        if mode_idx == 3:
            return bool(sample.get("dense_captions")), False
        return False, False

    # ------------------------------------------------------------------
    # Sample add/remove/clear
    # ------------------------------------------------------------------
    def _sample_file_filter(self) -> str:
        return "Media Files (*.mp4 *.avi *.mov *.mkv *.jpg *.jpeg *.png *.bmp);;All Files (*)"

    def _group_selected_files(self, files):
        if self.is_multi_view:
            grouped = {}
            for file_path in files:
                grouped.setdefault(os.path.dirname(file_path), []).append(file_path)
            groups = []
            for paths in grouped.values():
                groups.append(sorted(paths))
            return groups
        return [[path] for path in files]

    def _sample_id_from_group(self, source_group):
        primary = source_group[0]
        if self.is_multi_view and len(source_group) > 1:
            return os.path.basename(os.path.dirname(primary)) or os.path.basename(primary)
        return os.path.splitext(os.path.basename(primary))[0] or os.path.basename(primary)

    def _raw_path_for_new_input(self, path: str):
        if self.project_root:
            try:
                return os.path.relpath(path, self.project_root).replace("\\", "/")
            except Exception:
                return path
        return path

    def _build_new_sample(self, source_group):
        sample_id = self._make_unique_sample_id(self._sample_id_from_group(source_group))
        inputs = []
        for source_path in source_group:
            inputs.append(
                {
                    "type": "video",
                    "path": self._raw_path_for_new_input(source_path),
                }
            )
        return {
            "id": sample_id,
            "metadata": {},
            "inputs": inputs,
            "labels": {},
            "smart_labels": {},
            "events": [],
            "smart_events": [],
            "captions": [],
            "dense_captions": [],
        }

    def handle_add_sample(self):
        if not self.json_loaded:
            QMessageBox.warning(self.main, "Warning", "Please create or load a dataset first.")
            return

        start_dir = self.current_working_directory or self.project_root or ""
        files, _ = QFileDialog.getOpenFileNames(
            self.main,
            "Select Samples to Add",
            start_dir,
            self._sample_file_filter(),
        )
        if not files:
            return

        if not self.current_working_directory:
            self.current_working_directory = os.path.dirname(files[0])

        added_count = 0
        first_sample_id = None

        for source_group in self._group_selected_files(files):
            sample = self._build_new_sample(source_group)
            self.get_samples().append(sample)
            added_count += 1
            if first_sample_id is None:
                first_sample_id = sample["id"]

        if added_count <= 0:
            return

        self.is_data_dirty = True
        self.populate_tree()
        self.main.update_save_export_button_state()
        self.main.show_temp_msg("Added", f"Added {added_count} samples.")

        if first_sample_id:
            entry = self.sample_id_to_entry.get(first_sample_id)
            item = self.action_item_map.get(entry["path"]) if entry else None
            if item is not None:
                self.panel.tree.setCurrentIndex(item.index())
                self.panel.tree.setFocus()

    def handle_clear_workspace(self):
        if not self.json_loaded:
            return

        msg = QMessageBox(self.main)
        msg.setWindowTitle("Clear Workspace")
        msg.setText("Clear workspace? Unsaved changes will be lost.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        self.media_controller.stop()
        self.dataset_json["data"] = []
        self.is_data_dirty = True
        self._rebuild_runtime_index()
        self.main.reset_all_managers()
        self.main.show_workspace()
        self._refresh_schema_panels()
        self.populate_tree()
        self.main.update_save_export_button_state()
        self.main.show_temp_msg("Cleared", "Workspace reset.")

    def handle_remove_item(self, index: QModelIndex):
        path, _action_idx = self._path_from_index(index)
        if not path:
            return

        removed = self.remove_action_item_by_path(path)
        if not removed:
            return

        self.is_data_dirty = True
        removed_selected = self.current_selected_input_path == path or self.get_data_id_by_path(path) == self.current_selected_sample_id
        self.populate_tree()
        self.main.update_save_export_button_state()
        self.main.show_temp_msg("Removed", "Sample removed.")

        if removed_selected and self.tree_model.rowCount() == 0:
            self._reset_panels_after_removed_path(path)

    def _reset_panels_after_removed_path(self, _removed_path: str):
        self.current_selected_sample_id = ""
        self.current_selected_input_path = None
        self.media_controller.stop()
        self.main.center_panel.player.setSource(QUrl())
        self.main.center_panel.set_markers([])

        self.main.classification_panel.clear_selection()
        self.main.classification_panel.reset_smart_inference()
        self.main.classification_panel.manual_box.setEnabled(False)

        self.main.localization_editor_controller.current_video_path = None
        self.main.localization_editor_controller.current_head = None
        self.main.localization_panel.table.set_data([])
        if hasattr(self.main.localization_panel, "smart_widget"):
            self.main.localization_panel.smart_widget.smart_table.set_data([])
        self.main.localization_panel.setEnabled(False)

        self.main.desc_editor_controller.current_sample_id = ""
        self.main.desc_editor_controller.current_action_path = None
        self.main.description_panel.caption_edit.clear()
        self.main.description_panel.caption_edit.setEnabled(False)
        self.main.description_panel.setEnabled(False)

        self.main.dense_editor_controller.current_video_path = None
        self.main.dense_editor_controller.current_sample_id = ""
        self.main.dense_panel.table.set_data([])
        self.main.dense_panel.input_widget.set_text("")
        self.main.dense_panel.setEnabled(False)

        self.dataSelected.emit("")

    # ------------------------------------------------------------------
    # Save helpers
    # ------------------------------------------------------------------
    def _dataset_json_for_write(self, save_path: str):
        normalized, error = self._normalize_dataset_json(self.dataset_json)
        if error:
            raise ValueError(error)

        base_dir = os.path.dirname(os.path.abspath(save_path))
        written = copy.deepcopy(normalized)
        for sample in written.get("data", []):
            new_inputs = []
            source_paths = self._raw_source_paths_for_sample(sample)
            if not source_paths:
                source_paths = [inp.get("path") for inp in sample.get("inputs", []) if isinstance(inp, dict) and inp.get("path")]

            for index, input_item in enumerate(sample.get("inputs", [])):
                if not isinstance(input_item, dict):
                    continue
                raw_path = input_item.get("path")
                abs_path = self._resolve_media_path(raw_path)
                new_input = copy.deepcopy(input_item)
                if abs_path:
                    try:
                        new_input["path"] = os.path.relpath(abs_path, base_dir).replace("\\", "/")
                    except Exception:
                        new_input["path"] = abs_path
                new_inputs.append(new_input)
            sample["inputs"] = new_inputs

            if not sample.get("labels"):
                sample.pop("labels", None)
            if not sample.get("smart_labels"):
                sample.pop("smart_labels", None)
            if not sample.get("events"):
                sample.pop("events", None)
            if not sample.get("smart_events"):
                sample.pop("smart_events", None)
            if not sample.get("captions"):
                sample.pop("captions", None)
            if not sample.get("dense_captions"):
                sample.pop("dense_captions", None)
            if not sample.get("metadata"):
                sample.pop("metadata", None)

        written.setdefault("labels", {})
        written.setdefault("metadata", {})
        written.setdefault("modalities", ["video"])
        if not written.get("description"):
            written["description"] = ""
        return written

    def _write_dataset_json(self, save_path: str):
        try:
            written = self._dataset_json_for_write(save_path)
            with open(save_path, "w", encoding="utf-8") as handle:
                json.dump(written, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            QMessageBox.critical(self.main, "Save Error", f"Save failed: {exc}")
            return False

        self.dataset_json = written
        self.current_json_path = os.path.abspath(save_path)
        self.project_root = os.path.dirname(os.path.abspath(save_path))
        self.current_working_directory = self.project_root
        self.is_data_dirty = False
        self._add_recent_project(self.current_json_path)
        self._rebuild_runtime_index()
        self._refresh_header_panel()
        self.populate_tree()
        self.main.update_save_export_button_state()
        self.main.show_temp_msg("Saved", f"Saved to {os.path.basename(save_path)}")
        return True

    # ------------------------------------------------------------------
    # Shared schema/UI refresh
    # ------------------------------------------------------------------
    def _refresh_schema_panels(self):
        if hasattr(self.main, "classification_editor_controller"):
            self.main.classification_editor_controller.setup_dynamic_ui()
        if hasattr(self.main, "localization_editor_controller"):
            self.main.localization_editor_controller._refresh_schema_ui()
