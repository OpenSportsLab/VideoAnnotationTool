import copy

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from utils import natural_sort_key

from .inference_manager import InferenceManager
from .train_manager import TrainManager


class ClassificationEditorController(QObject):
    """
    Single controller for Classification mode.
    Owns annotation logic and smart/train helper wiring.
    Dataset loading and explorer state updates are handled centrally by DatasetExplorerController.
    """

    statusMessageRequested = pyqtSignal(str, str, int)
    saveStateRefreshRequested = pyqtSignal()
    itemStatusRefreshRequested = pyqtSignal(str)
    # payload: sample_id, cleaned_annotation, show_feedback
    manualAnnotationSaveRequested = pyqtSignal(str, object, bool)
    schemaHeadAddRequested = pyqtSignal(str, dict)
    schemaHeadRemoveRequested = pyqtSignal(str)
    schemaLabelAddRequested = pyqtSignal(str, str)
    schemaLabelRemoveRequested = pyqtSignal(str, str)

    def __init__(self, classification_panel):
        super().__init__()
        self.classification_panel = classification_panel
        self._active_mode_index = 0
        self._action_items_cache = []
        self._action_path_by_sample_id = {}
        self._schema_definitions = {}

        self.current_sample_id = ""
        self.current_action_path = None
        self._current_sample_snapshot = {}

        # Helper services remain separate, but are now owned by this controller.
        self.inference_manager = InferenceManager(self)
        self.train_manager = TrainManager(self)

    # ---------------------------------------------------------------------
    # Lifecycle / Wiring
    # ---------------------------------------------------------------------
    def setup_connections(self):
        self.classification_panel.annotation_saved.connect(self.save_manual_annotation)
        self.classification_panel.hand_clear_requested.connect(self.clear_current_manual_annotation)
        self.classification_panel.head_smart_infer_requested.connect(self.inference_manager.start_head_inference)
        self.classification_panel.head_smart_confirm_requested.connect(self.confirm_smart_annotation_head)
        self.classification_panel.head_smart_reject_requested.connect(self.reject_smart_annotation_head)
        self.classification_panel.add_head_clicked.connect(self.handle_add_label_head)
        self.classification_panel.remove_head_clicked.connect(self.handle_remove_label_head)
        self.classification_panel.confirm_infer_requested.connect(self.save_manual_annotation)

    def on_mode_changed(self, index: int):
        self._active_mode_index = index

    def shutdown_background_tasks(self, wait_ms: int = 2500) -> bool:
        return self.inference_manager.shutdown_threads(wait_ms=wait_ms)

    def reset_ui(self):
        self.classification_panel.clear_dynamic_labels()
        self.classification_panel.manual_box.setEnabled(False)
        self.current_sample_id = ""
        self.current_action_path = None
        self._current_sample_snapshot = {}
        self.classification_panel.reset_smart_inference()
        self.classification_panel.reset_train_ui()

    def setup_dynamic_ui(self):
        self.classification_panel.setup_dynamic_labels(self._schema_definitions)
        self._connect_dynamic_type_buttons()

    def on_schema_context_changed(self, schema: dict):
        self._schema_definitions = copy.deepcopy(schema) if isinstance(schema, dict) else {}
        self.setup_dynamic_ui()
        self.display_manual_annotation()

    def sync_batch_inference_dropdowns(self):
        sorted_list = sorted(
            list(self._action_items_cache or []),
            key=lambda data: natural_sort_key(data.get("name", "")),
        )
        action_names = [data.get("name", "") for data in sorted_list if data.get("name")]
        self.classification_panel.update_action_list(action_names)

    def on_action_items_changed(self, action_items: list):
        self._action_items_cache = list(action_items or [])
        self._action_path_by_sample_id = {}
        for item in self._action_items_cache:
            if not isinstance(item, dict):
                continue
            sample_id = str(item.get("data_id") or item.get("id") or "")
            path = str(item.get("path") or "")
            if sample_id and path:
                self._action_path_by_sample_id[sample_id] = path

    def _connect_dynamic_type_buttons(self):
        for head, group in self.classification_panel.label_groups.items():
            try:
                group.add_btn.clicked.disconnect()
            except Exception:
                pass
            try:
                group.remove_label_signal.disconnect()
            except Exception:
                pass
            try:
                group.value_changed.disconnect()
            except Exception:
                pass

            group.add_btn.clicked.connect(lambda _, selected_head=head: self.add_custom_type(selected_head))
            group.remove_label_signal.connect(
                lambda lbl, _, selected_head=head: self.remove_custom_type(selected_head, lbl)
            )
            # Manual annotations now persist immediately on value changes.
            group.value_changed.connect(self._on_manual_label_value_changed)

    def _on_manual_label_value_changed(self, *_args):
        self.save_manual_annotation(show_feedback=False)

    # ---------------------------------------------------------------------
    # Selection / Display
    # ---------------------------------------------------------------------
    def on_selected_sample_changed(self, sample):
        self.current_sample_id = ""
        self.current_action_path = None
        self._current_sample_snapshot = {}

        if not isinstance(sample, dict):
            self.classification_panel.manual_box.setEnabled(False)
            self.classification_panel.clear_selection()
            self.classification_panel.chart_widget.setVisible(False)
            return

        sample_id = str(sample.get("id") or "")
        path = str(self._action_path_by_sample_id.get(sample_id) or self._extract_primary_path(sample) or "")
        if not sample_id or not path:
            self.classification_panel.manual_box.setEnabled(False)
            self.classification_panel.clear_selection()
            self.classification_panel.chart_widget.setVisible(False)
            return

        self.current_sample_id = sample_id
        self.current_action_path = path
        self._current_sample_snapshot = copy.deepcopy(sample)
        self.display_manual_annotation()
        self.classification_panel.manual_box.setEnabled(True)

    # ---------------------------------------------------------------------
    # Classification Annotation + Schema
    # ---------------------------------------------------------------------
    def confirm_smart_annotation_as_manual(self):
        self.inference_manager.confirm_smart_annotation_as_manual()

    def confirm_smart_annotation_head(self, head: str):
        self.inference_manager.confirm_smart_annotation_for_head(head)

    def reject_smart_annotation_head(self, head: str):
        self.inference_manager.reject_smart_annotation_for_head(head)

    def save_manual_annotation(self, override_data=None, show_feedback: bool = True):
        if not self.current_sample_id:
            return

        raw_data = override_data if override_data is not None else self.classification_panel.get_annotation()
        cleaned = {key: value for key, value in raw_data.items() if value}
        if not cleaned:
            cleaned = None

        old_data = self._manual_payload_to_panel(self._current_sample_snapshot.get("labels"))
        normalized_old = old_data if old_data else None
        if normalized_old == cleaned:
            return

        self.manualAnnotationSaveRequested.emit(self.current_sample_id, copy.deepcopy(cleaned), show_feedback)
        self._set_snapshot_manual_annotation(cleaned)

    def clear_current_manual_annotation(self):
        if not self.current_sample_id:
            return

        old_data = self._manual_payload_to_panel(self._current_sample_snapshot.get("labels"))
        if old_data:
            self.manualAnnotationSaveRequested.emit(self.current_sample_id, None, True)
            self._set_snapshot_manual_annotation(None)

        self.classification_panel.clear_selection()

    def clear_current_smart_annotation(self):
        self.inference_manager.clear_current_smart_annotation()

    def display_manual_annotation(self):
        data = self._manual_payload_to_panel(self._current_sample_snapshot.get("labels"))
        self.classification_panel.set_annotation(data)
        labels_payload = self._current_sample_snapshot.get("labels")
        if isinstance(labels_payload, dict):
            for head, payload in labels_payload.items():
                if not isinstance(payload, dict):
                    continue
                label = payload.get("label")
                if label in (None, ""):
                    continue
                if "confidence_score" not in payload:
                    continue
                try:
                    score = float(payload.get("confidence_score") or 0.0)
                except Exception:
                    score = 0.0
                self.classification_panel.set_head_smart_state(head, str(label), score, True)

    def handle_add_label_head(self, name):
        clean = name.strip().replace(" ", "_").lower()
        if not clean or clean in self._schema_definitions:
            return

        msg = QMessageBox(self.classification_panel)
        msg.setText(f"Type for '{name}'?")
        btn_single = msg.addButton("Single Label", QMessageBox.ButtonRole.ActionRole)
        btn_multi = msg.addButton("Multi Label", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        label_type = (
            "single_label"
            if msg.clickedButton() == btn_single
            else "multi_label" if msg.clickedButton() == btn_multi else None
        )
        if not label_type:
            return

        definition = {"type": label_type, "labels": []}
        self.schemaHeadAddRequested.emit(clean, copy.deepcopy(definition))
        self.classification_panel.new_head_edit.clear()

    def handle_remove_label_head(self, head):
        if head not in self._schema_definitions:
            return
        if QMessageBox.question(self.classification_panel, "Remove", f"Remove '{head}'?") == QMessageBox.StandardButton.No:
            return
        self.schemaHeadRemoveRequested.emit(head)

    def add_custom_type(self, head):
        group = self.classification_panel.label_groups.get(head)
        definition = self._schema_definitions.get(head, {})
        if not group or not definition:
            return

        text = group.input_field.text().strip()
        if not text:
            return

        labels = definition.get("labels", [])
        if any(label.lower() == text.lower() for label in labels):
            self._emit_status("Duplicate", "Label exists.")
            return

        self.schemaLabelAddRequested.emit(head, text)
        group.input_field.clear()

    def remove_custom_type(self, head, label):
        definition = self._schema_definitions.get(head, {})
        labels = definition.get("labels", [])
        if label not in labels:
            return
        self.schemaLabelRemoveRequested.emit(head, label)

    def _emit_status(self, title: str, message: str, duration: int = 1500):
        self.statusMessageRequested.emit(title, message, duration)

    def get_current_action_path(self):
        return self.current_action_path

    def get_current_sample_id(self):
        return self.current_sample_id

    @staticmethod
    def _extract_primary_path(sample: dict):
        inputs = sample.get("inputs")
        if isinstance(inputs, list):
            for input_item in inputs:
                if isinstance(input_item, dict):
                    path = input_item.get("path")
                    if path:
                        return path
        return None

    @staticmethod
    def _manual_payload_to_panel(labels_payload) -> dict:
        if not isinstance(labels_payload, dict):
            return {}
        out = {}
        for head, payload in labels_payload.items():
            value = None
            if isinstance(payload, dict):
                if isinstance(payload.get("labels"), list):
                    value = list(payload.get("labels") or [])
                elif "label" in payload:
                    value = payload.get("label")
            elif isinstance(payload, list):
                value = list(payload)
            else:
                value = payload
            if value not in (None, "", []):
                out[head] = value
        return out

    @staticmethod
    def _panel_annotation_to_sample_labels(data) -> dict:
        if not isinstance(data, dict):
            return {}
        out = {}
        for head, value in data.items():
            if value in (None, "", []):
                continue
            if isinstance(value, list):
                out[head] = {"labels": list(value)}
            else:
                out[head] = {"label": value}
        return out

    def _set_snapshot_manual_annotation(self, cleaned):
        if not isinstance(self._current_sample_snapshot, dict):
            self._current_sample_snapshot = {}
        serialized = self._panel_annotation_to_sample_labels(cleaned)
        if serialized:
            self._current_sample_snapshot["labels"] = serialized
        else:
            self._current_sample_snapshot.pop("labels", None)

    def set_current_smart_annotation_snapshot(self, _path: str, smart_data):
        if not isinstance(self._current_sample_snapshot, dict):
            self._current_sample_snapshot = {}
        labels = self._current_sample_snapshot.get("labels")
        if not isinstance(labels, dict):
            labels = {}
            self._current_sample_snapshot["labels"] = labels

        if isinstance(smart_data, dict):
            for head, payload in smart_data.items():
                if payload is None:
                    labels.pop(head, None)
                elif isinstance(payload, dict) and payload:
                    labels[head] = copy.deepcopy(payload)
                else:
                    labels.pop(head, None)
        elif smart_data is None:
            # Clear smart state from all heads in current snapshot only.
            for head, payload in list(labels.items()):
                if isinstance(payload, dict) and "confidence_score" in payload:
                    updated = copy.deepcopy(payload)
                    updated.pop("confidence_score", None)
                    if updated:
                        labels[head] = updated
                    else:
                        labels.pop(head, None)

        if not labels:
            self._current_sample_snapshot.pop("labels", None)

    @staticmethod
    def _smart_chart_payload_from_labels(labels_payload):
        if not isinstance(labels_payload, dict):
            return None
        for payload in labels_payload.values():
            if not isinstance(payload, dict):
                continue
            label = payload.get("label")
            if label in (None, ""):
                continue
            if "confidence_score" not in payload:
                continue
            try:
                score = float(payload.get("confidence_score") or 0.0)
            except Exception:
                score = 0.0
            score = max(0.0, min(1.0, score))
            conf_dict = {str(label): score}
            remaining = max(0.0, 1.0 - score)
            if remaining > 0.001:
                conf_dict["Other Uncertainties"] = remaining
            return str(label), conf_dict
        return None

    def _is_active_mode(self) -> bool:
        return self._active_mode_index == 0
