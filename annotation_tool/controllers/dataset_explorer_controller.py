import copy
import datetime
import json
import os
from collections.abc import MutableMapping

from PyQt6.QtCore import QDir, QModelIndex, QObject, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QFileSystemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialogButtonBox,
    QFileDialog,
    QListView,
    QMessageBox,
    QTreeView,
)

from controllers.command_types import CmdType
from ui.dialogs import UnsavedChangesDialog
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
            return {"labels": list(value)}
        return {"label": value}

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

    def __contains__(self, path):
        try:
            return bool(_ManualAnnotationRecord(self._sample(path)))
        except KeyError:
            return False

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
    sampleSelectionChanged = pyqtSignal(object)
    schemaContextChanged = pyqtSignal(dict)
    questionBankChanged = pyqtSignal(list)
    classificationActionListChanged = pyqtSignal(list)
    mediaRouteRequested = pyqtSignal(object, bool)
    mediaStopRequested = pyqtSignal()
    statusMessageRequested = pyqtSignal(str, str, int)
    saveStateRefreshRequested = pyqtSignal()
    schemaRefreshRequested = pyqtSignal()
    batchDropdownSyncRequested = pyqtSignal()
    workspaceViewRequested = pyqtSignal()
    welcomeViewRequested = pyqtSignal()
    resetEditorsRequested = pyqtSignal()
    editorTabRequested = pyqtSignal(int)
    descSaveRequested = pyqtSignal()
    qaSaveRequested = pyqtSignal()
    clearMarkersRequested = pyqtSignal()
    annotationPanelsEnabledRequested = pyqtSignal(bool)
    headerDraftMutationRequested = pyqtSignal(dict)
    sampleRenameRequested = pyqtSignal(str, str)
    addSamplesRequested = pyqtSignal(list)
    clearWorkspaceRequested = pyqtSignal()
    removeItemMutationRequested = pyqtSignal(str, str)
    settingsChanged = pyqtSignal(object)

    SETTINGS_ORG = "OpenSportsLab"
    SETTINGS_APP = "VideoAnnotationTool"
    RECENT_DATASETS_KEY = "welcome/recent_datasets"
    MAX_RECENT_DATASETS_DISPLAY = 10

    HEADER_EDITABLE_KEYS = (
        "version",
        "date",
        "dataset_name",
        "description",
        "metadata",
    )
    HEADER_EXCLUDED_KEYS = {"data", "labels", "questions"}

    def __init__(
        self,
        panel,
        tree_model,
    ):
        super().__init__()
        self.panel = panel
        self.tree_model = tree_model
        self._active_mode_index = 0
        self._done_icon = None
        self._empty_icon = None

        self._settings = None
        self.settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

        self.dataset_json = {}
        self.current_json_path = None
        self.project_root = None
        self.current_working_directory = None
        self.json_loaded = False
        self.is_data_dirty = False

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
        self._last_routed_media_path = None
        self._suspend_tree_item_changed = False

        self.manual_annotations = _ManualAnnotationsProxy(self)
        self.localization_events = _SampleListProxy(self, "events")
        self.dense_description_events = _SampleListProxy(self, "dense_captions")

        self._setup_connections()

    @property
    def settings(self):
        return self._settings

    @settings.setter
    def settings(self, value):
        self._settings = value
        self.settingsChanged.emit(value)

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
    def question_definitions(self) -> list:
        questions = self.dataset_json.get("questions")
        if not isinstance(questions, list):
            questions = []
            self.dataset_json["questions"] = questions
        return questions

    @question_definitions.setter
    def question_definitions(self, value):
        self.dataset_json["questions"] = list(value) if isinstance(value, list) else []

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
        self.tree_model.itemChanged.connect(self._on_tree_item_changed)

    def reset(self, full_reset: bool = False):
        self.current_json_path = None
        self.project_root = None
        self.current_working_directory = None
        self.json_loaded = False
        self.is_data_dirty = False

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
        self._last_routed_media_path = None
        self._suspend_tree_item_changed = False

        if hasattr(self.tree_model, "clear"):
            self.tree_model.clear()
            if hasattr(self.tree_model, "configure_columns"):
                self.tree_model.configure_columns()
        if hasattr(self.panel, "tree") and self.panel.tree is not None:
            self.panel.tree.setCurrentIndex(QModelIndex())

        if full_reset:
            self.dataset_json = {}

    def push_undo(self, cmd_type, **kwargs):
        self.undo_stack.append({"type": cmd_type, **kwargs})
        self.redo_stack.clear()
        self.is_data_dirty = True

    def snapshot_dataset_json(self):
        return copy.deepcopy(self.dataset_json)

    def push_dataset_json_replace_undo_if_changed(self, before_json) -> bool:
        after_json = copy.deepcopy(self.dataset_json)
        if after_json == before_json:
            return False
        self.push_undo(
            CmdType.DATASET_JSON_REPLACE,
            old_data=copy.deepcopy(before_json),
            new_data=after_json,
        )
        return True

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
        path = str(path)

        # Fast exact match on canonical runtime path.
        for entry in self.action_item_data:
            if entry.get("path") == path:
                return entry["sample_ref"]

        # Compatibility: accept equivalent source paths (relative/absolute).
        candidate_keys = []
        raw_key = self._fs_path_key(path)
        if raw_key:
            candidate_keys.append(raw_key)
        resolved_key = self._fs_path_key(self._resolve_media_path(path))
        if resolved_key and resolved_key not in candidate_keys:
            candidate_keys.append(resolved_key)
        if not candidate_keys:
            return None

        for entry in self.action_item_data:
            entry_key = self._fs_path_key(entry.get("path"))
            if entry_key in candidate_keys:
                return entry["sample_ref"]
            for source_path in list(entry.get("source_files", [])):
                if self._fs_path_key(source_path) in candidate_keys:
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

    def get_media_source_by_id(self, data_id: str, preferred_path: str = ""):
        entry = self.action_id_to_item.get(data_id)
        if not entry:
            return None

        media_sources = list(entry.get("media_sources", []))
        if not media_sources:
            return None

        preferred_key = self._fs_path_key(preferred_path)
        if preferred_key:
            for media_source in media_sources:
                if self._fs_path_key(media_source.get("path")) == preferred_key:
                    return copy.deepcopy(media_source)

        return copy.deepcopy(media_sources[0])

    def get_data_id_by_path(self, path: str):
        sample = self.get_sample_by_path(path)
        if isinstance(sample, dict):
            sample_id = sample.get("id")
            if sample_id:
                return str(sample_id)
        for entry in self.action_item_data:
            if entry.get("path") == path:
                return entry.get("data_id")
        return None

    def _emit_selected_sample(self, sample_id: str):
        if not sample_id:
            self.sampleSelectionChanged.emit(None)
            return
        sample = self.get_sample(sample_id)
        if not sample:
            self.sampleSelectionChanged.emit(None)
            return
        self.sampleSelectionChanged.emit(copy.deepcopy(sample))

    def _emit_schema_context(self):
        self.schemaContextChanged.emit(copy.deepcopy(self.label_definitions))

    def _emit_question_bank_context(self):
        self.questionBankChanged.emit(copy.deepcopy(self.question_definitions))

    def _emit_classification_action_list(self):
        self.classificationActionListChanged.emit(copy.deepcopy(self.action_item_data))

    def _reemit_current_selection(self):
        selected = self.current_selected_sample_id or ""
        self.dataSelected.emit(selected)
        self._emit_selected_sample(selected)

    def reemit_current_selection(self):
        self._reemit_current_selection()

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
            inputs = [self._new_input_payload_for_source(src) for src in paths]

        sample = {"id": sample_id, "inputs": inputs}
        sample.update(extra_fields)
        self.get_samples().append(sample)
        self.ensure_modalities_for_inputs(inputs)
        self._rebuild_runtime_index()
        return self.sample_id_to_entry.get(sample_id)

    def remove_action_item_by_path(self, path: str) -> bool:
        sample_id = self.get_data_id_by_path(path)
        if not sample_id:
            sample = self.get_sample_by_path(path)
            sample_id = str(sample.get("id")) if isinstance(sample, dict) and sample.get("id") else ""
        if not sample_id:
            return False
        return self._remove_sample_by_id(sample_id)

    def _remove_sample_by_id(self, sample_id: str) -> bool:
        if not sample_id:
            return False
        before = len(self.get_samples())
        self.dataset_json["data"] = [
            sample for sample in self.get_samples()
            if str(sample.get("id")) != str(sample_id)
        ]
        removed = len(self.get_samples()) != before

        return removed

    def _remove_sample_input_by_path(self, sample_id: str, input_path: str):
        sample = self.get_sample(sample_id)
        if not isinstance(sample, dict):
            return False, False

        inputs = sample.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            return False, False

        target_key = self._fs_path_key(input_path)
        if not target_key:
            return False, False

        kept_inputs = []
        removed_input = False
        for input_item in inputs:
            if (
                not removed_input
                and isinstance(input_item, dict)
                and self._fs_path_key(self._resolve_media_path(input_item.get("path"))) == target_key
            ):
                removed_input = True
                continue
            kept_inputs.append(input_item)

        if not removed_input:
            return False, False

        if kept_inputs:
            sample["inputs"] = kept_inputs
            self._rebuild_runtime_index()
            return True, False

        sample_removed = self._remove_sample_by_id(sample_id)
        return sample_removed, sample_removed

    def _top_level_index_for_sample(self, sample_id: str) -> QModelIndex:
        entry = self.sample_id_to_entry.get(sample_id)
        if not entry:
            return QModelIndex()
        item = self.action_item_map.get(entry.get("path"))
        if item is None:
            return QModelIndex()
        idx = item.index()
        return idx if idx.isValid() else QModelIndex()

    def _first_visible_top_level_index(self, start_row: int) -> QModelIndex:
        root = QModelIndex()
        row_count = self.tree_model.rowCount(root)
        if row_count <= 0:
            return QModelIndex()

        tree = self.panel.tree
        for row in range(start_row, -1, -1):
            if tree.isRowHidden(row, root):
                continue
            idx = self.tree_model.index(row, 0, root)
            if idx.isValid():
                return idx

        for row in range(max(start_row + 1, 0), row_count):
            if tree.isRowHidden(row, root):
                continue
            idx = self.tree_model.index(row, 0, root)
            if idx.isValid():
                return idx

        return QModelIndex()

    def _first_child_index_for_parent(self, parent_idx: QModelIndex) -> QModelIndex:
        if not parent_idx.isValid():
            return QModelIndex()
        if self.tree_model.rowCount(parent_idx) <= 0:
            return QModelIndex()
        child_idx = self.tree_model.index(0, 0, parent_idx)
        return child_idx if child_idx.isValid() else QModelIndex()

    def _expanded_sample_ids_in_tree(self):
        tree = self.panel.tree
        expanded_sample_ids = set()
        root = QModelIndex()
        for row in range(self.tree_model.rowCount(root)):
            parent_idx = self.tree_model.index(row, 0, root)
            if not parent_idx.isValid():
                continue
            if not tree.isExpanded(parent_idx):
                continue
            sample_id = parent_idx.data(getattr(self.tree_model, "DataIdRole", 0x0101))
            if sample_id:
                expanded_sample_ids.add(str(sample_id))
        return expanded_sample_ids

    def _reapply_expanded_samples(self, sample_ids):
        if not sample_ids:
            return
        tree = self.panel.tree
        for sample_id in sample_ids:
            parent_idx = self._top_level_index_for_sample(str(sample_id))
            if parent_idx.isValid():
                tree.setExpanded(parent_idx, True)

    def remove_description_action_by_path(self, path: str):
        removed = self.remove_action_item_by_path(path)
        return [path] if removed else []

    def clear_annotations_for_path(self, path: str):
        sample = self.get_sample_by_path(path)
        if not sample:
            return
        for field in (
            "labels",
            "events",
            "captions",
            "dense_captions",
            "answers",
        ):
            sample.pop(field, None)

    def is_action_done(self, action_path: str) -> bool:
        sample = self.get_sample_by_path(action_path)
        if not sample:
            return False
        hand_labelled, smart_labelled = self._label_state_for_sample(sample)
        return bool(hand_labelled or smart_labelled)

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
        if not self.check_and_close_current_project():
            return

        self.resetEditorsRequested.emit()
        self.create_new_project()

    def import_annotations(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.panel,
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
                self.panel,
                "Dataset Not Found",
                f"Dataset file does not exist and will be removed from recents:\n{normalized_path}",
            )
            self._remove_recent_project(normalized_path)
            return False

        if not self.check_and_close_current_project():
            return False

        self.resetEditorsRequested.emit()

        try:
            with open(normalized_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            QMessageBox.critical(self.panel, "Error", f"Invalid JSON: {exc}")
            return False

        if not self.load_project(data, normalized_path):
            QMessageBox.critical(self.panel, "Error", "Could not load dataset JSON.")
            return False

        self._add_recent_project(normalized_path)
        return True

    def load_project(self, data, file_path):
        normalized, error = self._normalize_dataset_json(data)
        if error:
            QMessageBox.critical(self.panel, "Invalid Dataset", error)
            return False

        self.reset(full_reset=True)
        self.dataset_json = normalized
        self.current_json_path = file_path
        self.project_root = os.path.dirname(os.path.abspath(file_path))
        self.current_working_directory = self.project_root
        self.json_loaded = True
        self.is_data_dirty = False

        self._rebuild_runtime_index()
        self.workspaceViewRequested.emit()
        self._refresh_header_panel()
        self._refresh_schema_panels()
        self.populate_tree()
        self._reconcile_tab_with_current_selection()
        self.saveStateRefreshRequested.emit()
        self.statusMessageRequested.emit(
            "Loaded",
            f"Loaded {len(self.action_item_data)} samples.",
            1500,
        )
        return True

    def create_new_project(self, mode=None):
        _ = mode  # Legacy argument kept for compatibility; tab is sample-driven.
        initial_tab = self._active_mode_idx()

        self.reset(full_reset=True)
        self.dataset_json = self._default_dataset_json()
        self.json_loaded = True
        self.is_data_dirty = True
        self._rebuild_runtime_index()

        self.workspaceViewRequested.emit()
        self.editorTabRequested.emit(initial_tab)
        self._refresh_header_panel()
        self._refresh_schema_panels()
        self.populate_tree()
        self.saveStateRefreshRequested.emit()
        self.statusMessageRequested.emit("New Dataset", "Blank dataset ready.", 1500)

    def close_project(self):
        if not self.check_and_close_current_project():
            return

        self.resetEditorsRequested.emit()
        self.reset(full_reset=True)
        self.panel.clear_header_rows()
        if hasattr(self.panel, "clear_raw_json_text"):
            self.panel.clear_raw_json_text()
        self.saveStateRefreshRequested.emit()
        self.welcomeViewRequested.emit()
        self.statusMessageRequested.emit("Project Closed", "Returned to Home Screen", 1000)

    def check_and_close_current_project(self) -> bool:
        if not self.json_loaded:
            return True
        if not self.is_data_dirty:
            self.mediaStopRequested.emit()
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

        self.mediaStopRequested.emit()
        return True

    def _prompt_unsaved_close_action(self) -> str:
        return UnsavedChangesDialog.get_action(self.panel)

    def save_project(self):
        if self._active_mode_idx() == 2:
            self.descSaveRequested.emit()
        if self._active_mode_idx() == 4:
            self.qaSaveRequested.emit()

        if not self.current_json_path:
            return self.export_project()
        return self._write_dataset_json(self.current_json_path)

    def export_project(self):
        if self._active_mode_idx() == 2:
            self.descSaveRequested.emit()
        if self._active_mode_idx() == 4:
            self.qaSaveRequested.emit()

        path, _ = QFileDialog.getSaveFileName(
            self.panel,
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
        self.headerDraftMutationRequested.emit(copy.deepcopy(draft))

    # ------------------------------------------------------------------
    # Runtime/sample indexing
    # ------------------------------------------------------------------
    def _default_dataset_json(self):
        today = datetime.date.today().isoformat()
        return {
            "version": "2.0",
            "date": today,
            "dataset_name": "Untitled Dataset",
            "description": "",
            "modalities": ["video"],
            "metadata": {},
            "labels": {},
            "questions": [],
            "data": [],
        }

    @staticmethod
    def _canonical_input_type(input_type, path: str = "") -> str:
        clean = str(input_type or "").strip().lower()
        if clean == "frame_npy":
            return "frames_npy"
        if clean:
            return clean
        _, extension = os.path.splitext(str(path or ""))
        if extension.lower() == ".npy":
            return "frames_npy"
        if extension.lower() == ".parquet":
            return "tracking_parquet"
        return "video"

    @staticmethod
    def _coerce_frames_fps(value, default: float = 2.0) -> float:
        try:
            fps = float(value)
        except Exception:
            fps = default
        if fps <= 0:
            return default
        return fps

    def _normalized_modalities(self, raw_modalities, samples=None) -> list[str]:
        normalized = []
        seen = set()

        def _add(modality):
            clean = str(modality or "").strip()
            if not clean:
                return
            canonical = self._canonical_input_type(clean)
            if canonical not in seen:
                seen.add(canonical)
                normalized.append(canonical)

        if isinstance(raw_modalities, list):
            for item in raw_modalities:
                _add(item)

        for sample in list(samples or []):
            if not isinstance(sample, dict):
                continue
            for input_item in list(sample.get("inputs", [])):
                if not isinstance(input_item, dict):
                    continue
                path = str(input_item.get("path") or "")
                canonical = self._canonical_input_type(input_item.get("type"), path)
                _add(canonical)

        if not normalized:
            normalized.append("video")
        return normalized

    def ensure_modalities_for_inputs(self, inputs) -> None:
        if not isinstance(inputs, list):
            return
        self.modalities = self._normalized_modalities(
            self.modalities,
            [{"inputs": copy.deepcopy(inputs)}],
        )

    @staticmethod
    def _normalize_question_id(question_id: str) -> str:
        return str(question_id or "").strip()

    def _normalize_questions_payload(self, questions) -> list:
        normalized = []
        seen_ids = set()
        for raw_question in list(questions or []):
            if not isinstance(raw_question, dict):
                continue

            question_id = self._normalize_question_id(raw_question.get("id"))
            question_text = str(raw_question.get("question") or "").strip()
            if not question_id or not question_text:
                continue
            if question_id in seen_ids:
                continue

            seen_ids.add(question_id)
            normalized.append({"id": question_id, "question": question_text})
        return normalized

    @staticmethod
    def _normalize_sample_answers_payload(answers, valid_question_ids: set) -> list:
        normalized = []
        seen_question_ids = set()
        for raw_answer in list(answers or []):
            if not isinstance(raw_answer, dict):
                continue
            question_id = str(raw_answer.get("question_id") or "").strip()
            if (
                not question_id
                or question_id not in valid_question_ids
                or question_id in seen_question_ids
            ):
                continue
            answer_text = str(raw_answer.get("answer") or "").strip()
            if not answer_text:
                continue
            normalized.append({"question_id": question_id, "answer": answer_text})
            seen_question_ids.add(question_id)
        return normalized

    def next_question_id(self) -> str:
        max_suffix = 0
        for question in self.question_definitions:
            if not isinstance(question, dict):
                continue
            question_id = self._normalize_question_id(question.get("id"))
            if not question_id.startswith("q"):
                continue
            suffix = question_id[1:]
            if suffix.isdigit():
                max_suffix = max(max_suffix, int(suffix))
        return f"q{max_suffix + 1}"

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
        normalized["questions"] = self._normalize_questions_payload(normalized.get("questions"))
        valid_question_ids = {question["id"] for question in normalized["questions"]}
        if not isinstance(normalized.get("metadata"), dict):
            normalized["metadata"] = {}
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
            for input_item in inputs:
                if not isinstance(input_item, dict):
                    continue
                input_item["type"] = self._canonical_input_type(
                    input_item.get("type"),
                    input_item.get("path"),
                )
            sample["metadata"] = sample.get("metadata", {}) if isinstance(sample.get("metadata"), dict) else {}

            # Drop legacy smart keys. Smart state is represented via confidence_score
            # on canonical labels/events only.
            sample.pop("smart_label", None)
            sample.pop("smart_event", None)
            sample.pop("smart_labels", None)
            sample.pop("smart_events", None)

            labels = sample.get("labels")
            if not isinstance(labels, dict):
                labels = {}
                sample["labels"] = labels

            if "events" in sample and isinstance(sample["events"], list):
                for event in sample["events"]:
                    if isinstance(event, dict):
                        event["position_ms"] = _safe_int(event.get("position_ms", 0))
            if "dense_captions" in sample and isinstance(sample["dense_captions"], list):
                for event in sample["dense_captions"]:
                    if isinstance(event, dict):
                        event["position_ms"] = _safe_int(event.get("position_ms", 0))

            normalized_answers = self._normalize_sample_answers_payload(
                sample.get("answers"),
                valid_question_ids,
            )
            if normalized_answers:
                sample["answers"] = normalized_answers
            else:
                sample.pop("answers", None)

            cleaned_data.append(sample)

        normalized["data"] = cleaned_data
        normalized["modalities"] = self._normalized_modalities(
            normalized.get("modalities"),
            cleaned_data,
        )
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

    def _resolved_media_source_from_input(self, input_item: dict):
        if not isinstance(input_item, dict):
            return None

        raw_path = input_item.get("path")
        if not raw_path:
            return None

        resolved_path = self._resolve_media_path(raw_path)
        if not resolved_path:
            return None

        source_type = self._canonical_input_type(
            input_item.get("type"),
            raw_path,
        )
        media_source = {
            "path": resolved_path,
            "type": source_type,
        }
        if source_type in {"frames_npy", "tracking_parquet"}:
            media_source["fps"] = self._coerce_frames_fps(input_item.get("fps"), 2.0)
        else:
            try:
                fps = float(input_item.get("fps"))
            except Exception:
                fps = None
            if fps and fps > 0:
                media_source["fps"] = fps
        return media_source

    def _resolved_media_sources_for_sample(self, sample: dict):
        sources = []
        for input_item in sample.get("inputs", []):
            media_source = self._resolved_media_source_from_input(input_item)
            if media_source:
                sources.append(media_source)
        return sources

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

    def _fs_path_key(self, path: str) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.normpath(str(path)))

    def _resolved_source_paths_for_sample(self, sample: dict):
        return [
            source["path"]
            for source in self._resolved_media_sources_for_sample(sample)
            if source.get("path")
        ]

    def _primary_runtime_path_for_sample(self, sample: dict):
        sources = self._resolved_media_sources_for_sample(sample)
        if sources:
            return sources[0]["path"]
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
            media_sources = self._resolved_media_sources_for_sample(sample)
            source_files = [source["path"] for source in media_sources if source.get("path")]
            path = media_sources[0]["path"] if media_sources else self._primary_runtime_path_for_sample(sample)
            entry = {
                "name": self._display_name_for_sample(sample),
                "path": path,
                "source_files": source_files,
                "media_sources": media_sources,
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

    def _on_tree_item_changed(self, item):
        if self._suspend_tree_item_changed:
            return
        if item is None:
            return

        item_idx = item.index()
        if not item_idx.isValid() or item_idx.parent().isValid() or item_idx.column() != 0:
            return

        old_sample_id = str(item.data(getattr(self.tree_model, "DataIdRole", 0x0101)) or "")
        if not old_sample_id:
            return

        requested_id = self._sample_id_from_tree_item_text(item.text())
        if not requested_id:
            self._suspend_tree_item_changed = True
            try:
                item.setText(old_sample_id)
            finally:
                self._suspend_tree_item_changed = False
            return

        if requested_id == old_sample_id:
            # Ignore programmatic item changes (e.g. icon/status updates).
            return

        sample = self.get_sample(old_sample_id)
        if not isinstance(sample, dict):
            self._suspend_tree_item_changed = True
            try:
                item.setText(old_sample_id)
            finally:
                self._suspend_tree_item_changed = False
            return

        self._suspend_tree_item_changed = True
        try:
            # History manager owns the mutation; keep UI stable until refresh.
            item.setText(old_sample_id)
        finally:
            self._suspend_tree_item_changed = False

        # Defer mutation dispatch to avoid re-entering Qt model reset/clear while
        # still inside the tree_model.itemChanged callback.
        QTimer.singleShot(
            0,
            lambda old_id=old_sample_id, new_id=requested_id: self.sampleRenameRequested.emit(old_id, new_id),
        )

    @staticmethod
    def _sample_id_from_tree_item_text(text: str) -> str:
        sample_id = str(text or "").strip()
        marker = " (conf:"
        if sample_id.endswith(")") and marker in sample_id:
            sample_id = sample_id.rsplit(marker, 1)[0].strip()
        return sample_id

    # ------------------------------------------------------------------
    # Tree population and selection
    # ------------------------------------------------------------------
    def populate_tree(self):
        self._rebuild_runtime_index()
        self.tree_model.clear()
        if hasattr(self.tree_model, "configure_columns"):
            self.tree_model.configure_columns()
        self.action_item_map.clear()

        sorted_items = sorted(
            self.action_item_data,
            key=lambda item: natural_sort_key(item.get("name", "")),
        )

        self._suspend_tree_item_changed = True
        try:
            for entry in sorted_items:
                item = self.tree_model.add_entry(
                    name=entry["name"],
                    path=entry["path"],
                    source_files=entry.get("source_files"),
                    data_id=entry["data_id"],
                    confidence_score=self._average_smart_confidence_for_sample(entry.get("sample_ref")),
                )
                self.action_item_map[entry["path"]] = item
                self.update_item_status(entry["path"])
        finally:
            self._suspend_tree_item_changed = False

        self.handle_filter_change(self.panel.filter_combo.currentIndex())

        if self.tree_model.rowCount() > 0:
            first_index = self.tree_model.index(0, 0)
            if first_index.isValid():
                self.panel.tree.setCurrentIndex(first_index)
                self._expand_current_parent()
        else:
            self._clear_selection_for_empty_filtered_view()

        self._refresh_json_preview()
        self.batchDropdownSyncRequested.emit()
        self._emit_classification_action_list()

    def update_item_status(self, action_path: str):
        item = self.action_item_map.get(action_path)
        sample = self.get_sample_by_path(action_path)
        if item is None and isinstance(sample, dict):
            entry = self.sample_id_to_entry.get(str(sample.get("id") or ""))
            if entry:
                item = self.action_item_map.get(entry.get("path"))
        if not item:
            return

        if isinstance(sample, dict):
            self._suspend_tree_item_changed = True
            try:
                item.setText(self._tree_display_name_for_sample(sample))
            finally:
                self._suspend_tree_item_changed = False

        done_icon, empty_icon = self._done_icon, self._empty_icon
        if done_icon is not None and empty_icon is not None:
            item.setIcon(done_icon if self.is_action_done(action_path) else empty_icon)

    def refresh_all_item_statuses(self):
        for action_path in list(self.action_item_map.keys()):
            self.update_item_status(action_path)

    def _set_annotation_panels_enabled(self, enabled: bool):
        self.annotationPanelsEnabledRequested.emit(enabled)

    def set_active_mode(self, index: int):
        self._active_mode_index = int(index)

    def set_status_icons(self, done_icon, empty_icon):
        self._done_icon = done_icon
        self._empty_icon = empty_icon

    def _active_mode_idx(self) -> int:
        return int(self._active_mode_index)

    def _tree_display_name_for_sample(self, sample: dict) -> str:
        display_name = self._display_name_for_sample(sample)
        confidence_score = self._average_smart_confidence_for_sample(sample)
        if hasattr(self.tree_model, "entry_display_name"):
            return self.tree_model.entry_display_name(display_name, confidence_score)
        if confidence_score is None:
            return display_name
        return f"{display_name} (conf:{float(confidence_score):.2f})"

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

    def _index_for_path(self, path: str) -> QModelIndex:
        target_key = self._fs_path_key(path)
        if not target_key:
            return QModelIndex()

        root = QModelIndex()
        for row in range(self.tree_model.rowCount(root)):
            parent_idx = self.tree_model.index(row, 0, root)
            if not parent_idx.isValid():
                continue
            parent_path = parent_idx.data(getattr(self.tree_model, "FilePathRole", 0x0100))
            if self._fs_path_key(parent_path) == target_key:
                return parent_idx
            for child_row in range(self.tree_model.rowCount(parent_idx)):
                child_idx = self.tree_model.index(child_row, 0, parent_idx)
                child_path = child_idx.data(getattr(self.tree_model, "FilePathRole", 0x0100))
                if self._fs_path_key(child_path) == target_key:
                    return child_idx
        return QModelIndex()

    def _restore_tree_selection(self, preferred_sample_id: str = "", preferred_input_path: str = None) -> bool:
        tree = self.panel.tree
        target_idx = QModelIndex()

        if preferred_input_path:
            candidate = self._index_for_path(preferred_input_path)
            if candidate.isValid():
                action_idx = self._get_action_index(candidate)
                if not tree.isRowHidden(action_idx.row(), QModelIndex()):
                    target_idx = candidate

        if not target_idx.isValid() and preferred_sample_id:
            parent_idx = self._top_level_index_for_sample(preferred_sample_id)
            if parent_idx.isValid() and not tree.isRowHidden(parent_idx.row(), QModelIndex()):
                target_idx = parent_idx

        if not target_idx.isValid():
            return False

        if tree.currentIndex() != target_idx:
            tree.setCurrentIndex(target_idx)
            tree.scrollTo(target_idx)
        return True

    def restore_dataset_json_from_history(
        self,
        dataset_json_state,
        preferred_sample_id: str = "",
        preferred_input_path: str = None,
        expanded_sample_ids=None,
    ):
        self.dataset_json = copy.deepcopy(dataset_json_state) if isinstance(dataset_json_state, dict) else {}
        self._rebuild_runtime_index()
        self._refresh_header_panel()
        self._refresh_schema_panels()
        self.populate_tree()
        self._reapply_expanded_samples(expanded_sample_ids or set())
        self._restore_tree_selection(preferred_sample_id, preferred_input_path)

    def _remove_tree_row(self, action_idx: QModelIndex):
        if action_idx.isValid():
            self.tree_model.removeRow(action_idx.row(), action_idx.parent())

    def _expand_current_parent(self):
        tree = self.panel.tree
        current_idx = tree.currentIndex()
        selected_parent = self._get_action_index(current_idx) if current_idx.isValid() else QModelIndex()
        if selected_parent.isValid():
            tree.setExpanded(selected_parent, True)

    def _clear_selection_for_empty_filtered_view(self):
        self.current_selected_sample_id = ""
        self.current_selected_input_path = None
        self._last_routed_media_path = None
        self.mediaStopRequested.emit()
        self.clearMarkersRequested.emit()

        current_idx = self.panel.tree.currentIndex()
        if current_idx.isValid():
            self.panel.tree.setCurrentIndex(QModelIndex())
        else:
            self._set_annotation_panels_enabled(False)
            self._reemit_current_selection()

    def _on_selection_changed(self, current, _previous):
        self._set_annotation_panels_enabled(current.isValid())
        self._expand_current_parent()
        if not current.isValid():
            self.current_selected_sample_id = ""
            self.current_selected_input_path = None
            self._last_routed_media_path = None
            self._reemit_current_selection()
            return

        action_idx = self._get_action_index(current)
        if not action_idx.isValid():
            self.current_selected_sample_id = ""
            self.current_selected_input_path = None
            self._last_routed_media_path = None
            self._reemit_current_selection()
            return

        sample_id = action_idx.data(getattr(self.tree_model, "DataIdRole", 0x0101))
        if not sample_id:
            self.current_selected_sample_id = ""
            self.current_selected_input_path = None
            self._last_routed_media_path = None
            self._reemit_current_selection()
            return

        selected_path = current.data(getattr(self.tree_model, "FilePathRole", 0x0100))
        self.current_selected_sample_id = sample_id
        self.current_selected_input_path = selected_path or self.get_path_by_id(sample_id)

        sample = self.get_sample(sample_id)
        if self._reconcile_annotation_tab_for_sample(sample):
            return

        self._route_media_for_selection(current, sample_id, ensure_playback=True)
        self._reemit_current_selection()

    def _sample_supports_mode(self, sample: dict, mode_idx: int) -> bool:
        if not isinstance(sample, dict):
            return False
        if mode_idx == 0:
            return bool(_ManualAnnotationRecord(sample)) or self._has_smart_labels(sample)
        if mode_idx == 1:
            return bool(sample.get("events"))
        if mode_idx == 2:
            captions = sample.get("captions", [])
            return any(isinstance(cap, dict) and str(cap.get("text", "")).strip() for cap in captions)
        if mode_idx == 3:
            return bool(sample.get("dense_captions"))
        if mode_idx == 4:
            return self._has_non_empty_answers(sample)
        return False

    def _available_mode_indices_for_sample(self, sample: dict):
        return [mode_idx for mode_idx in (0, 1, 2, 3, 4) if self._sample_supports_mode(sample, mode_idx)]

    def _reconcile_annotation_tab_for_sample(self, sample: dict) -> bool:
        available_modes = self._available_mode_indices_for_sample(sample)
        if not available_modes:
            return False
        current_mode = self._active_mode_idx()
        if current_mode in available_modes:
            return False
        target_mode = available_modes[0]
        if target_mode == current_mode:
            return False
        self.editorTabRequested.emit(target_mode)
        return True

    def _reconcile_tab_with_current_selection(self):
        if not self.current_selected_sample_id:
            return
        sample = self.get_sample(self.current_selected_sample_id)
        if sample is None:
            return
        self._reconcile_annotation_tab_for_sample(sample)

    def _route_media_for_selection(
        self,
        selected_idx: QModelIndex,
        sample_id: str,
        ensure_playback: bool = False,
    ):
        preferred_path = selected_idx.data(getattr(self.tree_model, "FilePathRole", 0x0100)) or ""
        media_source = self.get_media_source_by_id(sample_id, preferred_path)
        if not media_source:
            return

        primary_path = str(media_source.get("path") or "")
        if not primary_path:
            return
        self.current_selected_input_path = primary_path
        if (
            not ensure_playback
            and self._fs_path_key(self._last_routed_media_path) == self._fs_path_key(primary_path)
        ):
            return
        self.mediaRouteRequested.emit(media_source, ensure_playback)
        self._last_routed_media_path = primary_path

    def handle_active_mode_changed(self, mode_idx: int = None):
        if mode_idx is not None:
            self.set_active_mode(mode_idx)
        current_idx = self.panel.tree.currentIndex()
        if not current_idx.isValid() or not self.current_selected_sample_id:
            self.current_selected_sample_id = ""
            self._reemit_current_selection()
            return
        self._route_media_for_selection(current_idx, self.current_selected_sample_id, ensure_playback=False)
        self._reemit_current_selection()

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

    def handle_filter_change(self, index, selection_fallback: str = "first_visible"):
        root = self.tree_model.invisibleRootItem()
        first_visible_idx = QModelIndex()
        for row in range(root.rowCount()):
            item = root.child(row)
            if item is None:
                continue

            data_id = item.data(getattr(self.tree_model, "DataIdRole", 0x0101))
            sample = self.get_sample(str(data_id or ""))
            hand_labelled, smart_labelled = self._label_state_for_sample(sample)

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
                if selection_fallback == "clear_selection":
                    self._clear_selection_for_empty_filtered_view()
                    return
                self.panel.tree.setCurrentIndex(first_visible_idx)
                self.panel.tree.scrollTo(first_visible_idx)
            self._expand_current_parent()
            return

        self._clear_selection_for_empty_filtered_view()

    def _label_state_for_sample(self, sample):
        if not isinstance(sample, dict):
            return False, False

        captions = sample.get("captions", [])
        has_caption_text = any(
            isinstance(cap, dict) and str(cap.get("text", "")).strip()
            for cap in captions
        )

        hand = (
            bool(_ManualAnnotationRecord(sample))
            or bool(sample.get("events"))
            or bool(sample.get("dense_captions"))
            or has_caption_text
            or self._has_non_empty_answers(sample)
        )
        smart = self._has_smart_labels(sample) or self._has_smart_events(sample)
        return bool(hand), bool(smart)

    @staticmethod
    def _has_non_empty_answers(sample: dict) -> bool:
        answers = sample.get("answers")
        if not isinstance(answers, list):
            return False
        for entry in answers:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("answer") or "").strip():
                return True
        return False

    @staticmethod
    def _has_smart_labels(sample: dict) -> bool:
        labels = sample.get("labels")
        if isinstance(labels, dict):
            for payload in labels.values():
                if isinstance(payload, dict) and "confidence_score" in payload:
                    return True
        return False

    @staticmethod
    def _has_smart_events(sample: dict) -> bool:
        events = sample.get("events")
        if isinstance(events, list):
            for event in events:
                if isinstance(event, dict) and "confidence_score" in event:
                    return True
        return False

    @staticmethod
    def _average_smart_confidence_for_sample(sample: dict):
        if not isinstance(sample, dict):
            return None

        scores = []
        labels = sample.get("labels")
        if isinstance(labels, dict):
            for payload in labels.values():
                if isinstance(payload, dict) and "confidence_score" in payload:
                    try:
                        scores.append(float(payload.get("confidence_score")))
                    except (TypeError, ValueError):
                        pass

        events = sample.get("events")
        if isinstance(events, list):
            for event in events:
                if isinstance(event, dict) and "confidence_score" in event:
                    try:
                        scores.append(float(event.get("confidence_score")))
                    except (TypeError, ValueError):
                        pass

        if not scores:
            return None
        return sum(scores) / len(scores)

    # ------------------------------------------------------------------
    # Sample add/remove/clear
    # ------------------------------------------------------------------
    def _sample_file_filter(self) -> str:
        return "Media Files (*.mp4 *.avi *.mov *.mkv *.jpg *.jpeg *.png *.bmp *.npy *.parquet);;All Files (*)"

    def _supported_media_extensions(self):
        return (".mp4", ".avi", ".mov", ".mkv", ".jpg", ".jpeg", ".png", ".bmp", ".npy", ".parquet")

    def _is_supported_media_file(self, path: str) -> bool:
        _, extension = os.path.splitext(str(path))
        return extension.lower() in self._supported_media_extensions()

    def _collect_media_files_from_folders(self, folders):
        collected = []
        seen = set()

        for folder in folders or []:
            folder_path = str(folder)
            if not os.path.isdir(folder_path):
                continue

            for root, dirnames, filenames in os.walk(folder_path):
                dirnames.sort(key=natural_sort_key)
                for filename in sorted(filenames, key=natural_sort_key):
                    candidate = os.path.join(root, filename)
                    if not self._is_supported_media_file(candidate):
                        continue
                    path_key = self._fs_path_key(candidate)
                    if path_key in seen:
                        continue
                    seen.add(path_key)
                    collected.append(candidate)
        return collected

    def _pick_files_or_folders_for_add_data(self, start_dir: str):
        dialog = QFileDialog(self.panel, "Select Samples to Add", start_dir)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        name_filters = self._sample_file_filter().split(";;")
        dialog.setNameFilters(name_filters)
        if name_filters:
            dialog.selectNameFilter(name_filters[0])
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)

        for list_view in dialog.findChildren(QListView):
            list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for tree_view in dialog.findChildren(QTreeView):
            tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        def _collect_selected_paths(include_current: bool = False):
            selected_paths = []
            seen = set()
            for view in dialog.findChildren((QListView, QTreeView)):
                selection_model = view.selectionModel()
                model = view.model()
                if selection_model is None or model is None:
                    continue

                indexes = list(selection_model.selectedRows())
                if not indexes:
                    indexes = [idx.siblingAtColumn(0) for idx in selection_model.selectedIndexes()]
                if include_current:
                    current = selection_model.currentIndex()
                    if current.isValid():
                        indexes.append(current.siblingAtColumn(0))

                for index in indexes:
                    if not index.isValid():
                        continue
                    source_model = model
                    source_index = index
                    while hasattr(source_model, "mapToSource") and hasattr(source_model, "sourceModel"):
                        source_index = source_model.mapToSource(source_index)
                        source_model = source_model.sourceModel()
                    if not isinstance(source_model, QFileSystemModel):
                        continue

                    path = source_model.filePath(source_index)
                    if not path or (not os.path.isfile(path) and not os.path.isdir(path)):
                        continue
                    key = self._fs_path_key(path)
                    if key in seen:
                        continue
                    seen.add(key)
                    selected_paths.append(str(path))
            return selected_paths

        def _accept_selected():
            selected = _collect_selected_paths(include_current=True)
            if not selected:
                selected = [str(path) for path in dialog.selectedFiles() if path]
            if not selected:
                return
            dialog._selected_paths_override = selected
            # Close via reject to bypass QFileDialog's accept() directory-navigation behavior.
            dialog.reject()

        button_box = dialog.findChild(QDialogButtonBox)
        if button_box is not None:
            add_btn = button_box.addButton("Add Selected", QDialogButtonBox.ButtonRole.ActionRole)
            add_btn.setDefault(True)
            add_btn.clicked.connect(_accept_selected)

        result = dialog.exec()
        selected_paths = getattr(dialog, "_selected_paths_override", None)
        if selected_paths:
            return list(selected_paths)
        if result != QFileDialog.DialogCode.Accepted:
            return []
        selected_paths = _collect_selected_paths(include_current=True)
        if selected_paths:
            return selected_paths
        return [str(path) for path in dialog.selectedFiles() if path]

    def _source_groups_from_selected_paths(self, selected_paths):
        source_groups = []
        seen_paths = set()

        for path in selected_paths or []:
            selected_path = str(path)
            if os.path.isdir(selected_path):
                group = []
                for media_path in self._collect_media_files_from_folders([selected_path]):
                    media_key = self._fs_path_key(media_path)
                    if media_key in seen_paths:
                        continue
                    seen_paths.add(media_key)
                    group.append(media_path)
                if group:
                    source_groups.append(group)
                continue

            if not os.path.isfile(selected_path) or not self._is_supported_media_file(selected_path):
                continue

            selected_key = self._fs_path_key(selected_path)
            if selected_key in seen_paths:
                continue
            seen_paths.add(selected_key)
            source_groups.append([selected_path])

        return source_groups

    def _group_selected_files(self, files):
        grouped = {}
        ordered_parent_keys = []

        for path in files or []:
            raw_path = str(path)
            parent_dir = os.path.dirname(raw_path) or raw_path
            parent_key = self._fs_path_key(parent_dir)
            if parent_key not in grouped:
                grouped[parent_key] = []
                ordered_parent_keys.append(parent_key)
            grouped[parent_key].append(raw_path)

        grouped_files = []
        for parent_key in ordered_parent_keys:
            sorted_group = sorted(
                grouped[parent_key],
                key=lambda value: natural_sort_key(os.path.basename(str(value)) or str(value)),
            )
            grouped_files.append(sorted_group)
        return grouped_files

    def _sample_id_from_group(self, source_group):
        if not source_group:
            return "sample"

        primary = str(source_group[0])
        if len(source_group) == 1:
            return os.path.splitext(os.path.basename(primary))[0] or os.path.basename(primary) or "sample"
        parent_name = os.path.basename(os.path.dirname(primary))
        if parent_name:
            return parent_name
        return os.path.splitext(os.path.basename(primary))[0] or os.path.basename(primary) or "sample"

    def _raw_path_for_new_input(self, path: str):
        if self.project_root:
            try:
                return os.path.relpath(path, self.project_root).replace("\\", "/")
            except Exception:
                return path
        return path

    def _new_input_payload_for_source(self, source_path: str) -> dict:
        input_payload = {
            "type": self._canonical_input_type(None, source_path),
            "path": self._raw_path_for_new_input(source_path),
        }
        if input_payload["type"] in {"frames_npy", "tracking_parquet"}:
            input_payload["fps"] = 2.0
        return input_payload

    def _build_new_sample(self, source_group):
        sample_id = self._make_unique_sample_id(self._sample_id_from_group(source_group))
        inputs = [self._new_input_payload_for_source(source_path) for source_path in source_group]
        return {
            "id": sample_id,
            "metadata": {},
            "inputs": inputs,
            "labels": {},
            "events": [],
            "captions": [],
            "dense_captions": [],
            "answers": [],
        }

    def handle_add_sample(self):
        if not self.json_loaded:
            QMessageBox.warning(self.panel, "Warning", "Please create or load a dataset first.")
            return

        start_dir = self.current_working_directory or self.project_root or ""
        selected_paths = self._pick_files_or_folders_for_add_data(start_dir)
        if not selected_paths:
            return

        source_groups = self._source_groups_from_selected_paths(selected_paths)
        if not source_groups:
            QMessageBox.information(
                self.panel,
                "No Media Found",
                "No supported media files were found in the selected files/folders.",
            )
            return

        if not self.current_working_directory:
            first_path = str(selected_paths[0])
            if os.path.isdir(first_path):
                self.current_working_directory = first_path
            else:
                self.current_working_directory = os.path.dirname(first_path)
        self.addSamplesRequested.emit(source_groups)

    def handle_clear_workspace(self):
        if not self.json_loaded:
            return

        msg = QMessageBox(self.panel)
        msg.setWindowTitle("Clear Workspace")
        msg.setText("Clear workspace? Unsaved changes will be lost.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        self.clearWorkspaceRequested.emit()

    def handle_remove_item(self, index: QModelIndex):
        if not index.isValid():
            return
        action_idx = self._get_action_index(index)
        if not action_idx.isValid():
            return

        sample_id = action_idx.data(getattr(self.tree_model, "DataIdRole", 0x0101))
        if not sample_id:
            return
        input_path = ""
        if index.parent().isValid():
            input_path = index.data(getattr(self.tree_model, "FilePathRole", 0x0100)) or ""
        self.removeItemMutationRequested.emit(str(sample_id), input_path)

    def _reset_panels_after_removed_path(self, _removed_path: str):
        self.current_selected_sample_id = ""
        self.current_selected_input_path = None
        self._last_routed_media_path = None
        self.mediaStopRequested.emit()
        self.clearMarkersRequested.emit()
        self.annotationPanelsEnabledRequested.emit(False)
        self._reemit_current_selection()

    # ------------------------------------------------------------------
    # Save helpers
    # ------------------------------------------------------------------
    def _dataset_json_for_write(self, save_path: str):
        normalized, error = self._normalize_dataset_json(self.dataset_json)
        if error:
            raise ValueError(error)

        base_dir = os.path.dirname(os.path.abspath(save_path))
        written = copy.deepcopy(normalized)
        written["questions"] = self._normalize_questions_payload(written.get("questions"))
        valid_question_ids = {question["id"] for question in written["questions"]}
        for sample in written.get("data", []):
            new_inputs = []

            for index, input_item in enumerate(sample.get("inputs", [])):
                if not isinstance(input_item, dict):
                    continue
                raw_path = input_item.get("path")
                abs_path = self._resolve_media_path(raw_path)
                new_input = copy.deepcopy(input_item)
                new_input["type"] = self._canonical_input_type(
                    new_input.get("type"),
                    raw_path,
                )
                if abs_path:
                    try:
                        new_input["path"] = os.path.relpath(abs_path, base_dir).replace("\\", "/")
                    except Exception:
                        new_input["path"] = abs_path
                new_inputs.append(new_input)
            sample["inputs"] = new_inputs

            if not sample.get("labels"):
                sample.pop("labels", None)
            if not sample.get("events"):
                sample.pop("events", None)
            if not sample.get("captions"):
                sample.pop("captions", None)
            if not sample.get("dense_captions"):
                sample.pop("dense_captions", None)
            normalized_answers = self._normalize_sample_answers_payload(
                sample.get("answers"),
                valid_question_ids,
            )
            if normalized_answers:
                sample["answers"] = normalized_answers
            else:
                sample.pop("answers", None)
            if not sample.get("metadata"):
                sample.pop("metadata", None)
            # Never persist retired smart-* keys.
            sample.pop("smart_labels", None)
            sample.pop("smart_events", None)

        written.setdefault("labels", {})
        for definition in written.get("labels", {}).values():
            if isinstance(definition, dict):
                definition.pop("label_colors", None)
        written.setdefault("metadata", {})
        written["modalities"] = self._normalized_modalities(
            written.get("modalities"),
            written.get("data", []),
        )
        written.setdefault("questions", [])
        if not written.get("description"):
            written["description"] = ""
        return written

    def _write_dataset_json(self, save_path: str):
        try:
            written = self._dataset_json_for_write(save_path)
            with open(save_path, "w", encoding="utf-8") as handle:
                json.dump(written, handle, indent=2, ensure_ascii=False)
        except Exception as exc:
            QMessageBox.critical(self.panel, "Save Error", f"Save failed: {exc}")
            return False

        self.dataset_json = written
        self.current_json_path = os.path.abspath(save_path)
        self.project_root = os.path.dirname(os.path.abspath(save_path))
        self.current_working_directory = self.project_root
        self.is_data_dirty = False
        self._add_recent_project(self.current_json_path)
        self._rebuild_runtime_index()
        self._refresh_header_panel()
        self._refresh_schema_panels()
        self.saveStateRefreshRequested.emit()
        self.statusMessageRequested.emit("Saved", f"Saved to {os.path.basename(save_path)}", 1500)
        return True

    # ------------------------------------------------------------------
    # Shared schema/UI refresh
    # ------------------------------------------------------------------
    def _refresh_schema_panels(self):
        self.schemaRefreshRequested.emit()
        self._emit_schema_context()
        self._emit_question_bank_context()
