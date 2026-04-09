import copy

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from controllers.command_types import CmdType
from utils import natural_sort_key

from .inference_manager import InferenceManager
from .train_manager import TrainManager


class ClassificationEditorController(QObject):
    """
    Single controller for Classification mode.
    Owns annotation logic and smart/train helper wiring.
    Dataset add/remove/filter/clear is handled centrally by DatasetExplorerController.
    """

    statusMessageRequested = pyqtSignal(str, str, int)
    saveStateRefreshRequested = pyqtSignal()
    itemStatusRefreshRequested = pyqtSignal(str)
    filterRefreshRequested = pyqtSignal(int, str)
    # payload: sample_id, cleaned_annotation, show_feedback
    manualAnnotationSaveRequested = pyqtSignal(str, object, bool)
    schemaHeadAddRequested = pyqtSignal(str, dict)
    schemaHeadRemoveRequested = pyqtSignal(str)
    schemaLabelAddRequested = pyqtSignal(str, str)
    schemaLabelRemoveRequested = pyqtSignal(str, str)

    def __init__(
        self,
        model,
        classification_panel,
        dataset_explorer_panel,
        center_panel,
        current_action_path_provider,
    ):
        super().__init__()
        self.model = model
        self.classification_panel = classification_panel
        self.dataset_explorer_panel = dataset_explorer_panel
        self.center_panel = center_panel
        self._get_current_action_path = current_action_path_provider
        self._active_mode_index = 0
        self._action_items_cache = []

        # Helper services remain separate, but are now owned by this controller.
        self.inference_manager = InferenceManager(self)
        self.train_manager = TrainManager(self)

    # ---------------------------------------------------------------------
    # Lifecycle / Wiring
    # ---------------------------------------------------------------------
    def setup_connections(self):
        self.classification_panel.annotation_saved.connect(self.save_manual_annotation)
        self.classification_panel.smart_confirm_requested.connect(self.confirm_smart_annotation_as_manual)
        self.classification_panel.hand_clear_requested.connect(self.clear_current_manual_annotation)
        self.classification_panel.smart_clear_requested.connect(self.clear_current_smart_annotation)
        self.classification_panel.add_head_clicked.connect(self.handle_add_label_head)
        self.classification_panel.remove_head_clicked.connect(self.handle_remove_label_head)
        self.classification_panel.smart_infer_requested.connect(self.inference_manager.start_inference)
        self.classification_panel.confirm_infer_requested.connect(self.save_manual_annotation)

    def on_mode_changed(self, index: int):
        self._active_mode_index = index
        if self._is_active_mode():
            self.center_panel.set_markers([])

    def reset_ui(self):
        self.classification_panel.clear_dynamic_labels()
        self.classification_panel.manual_box.setEnabled(False)
        self.classification_panel.reset_smart_inference()
        self.classification_panel.reset_train_ui()

    def setup_dynamic_ui(self):
        self.classification_panel.setup_dynamic_labels(self.model.label_definitions)
        self._connect_dynamic_type_buttons()

    def sync_batch_inference_dropdowns(self):
        sorted_list = sorted(
            (self._action_items_cache or self.model.action_item_data),
            key=lambda data: natural_sort_key(data.get("name", "")),
        )
        action_names = [data["name"] for data in sorted_list]
        self.classification_panel.update_action_list(action_names)

    def on_action_items_changed(self, action_items: list):
        self._action_items_cache = list(action_items or [])

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
        if self.classification_panel.tabs.currentIndex() != 0:
            return
        self.save_manual_annotation(show_feedback=False)

    # ---------------------------------------------------------------------
    # Selection / Display
    # ---------------------------------------------------------------------
    def on_data_selected(self, data_id: str):
        if not data_id:
            self.classification_panel.manual_box.setEnabled(False)
            self.classification_panel.clear_selection()
            self.classification_panel.chart_widget.setVisible(False)
            if self._is_active_mode():
                self.center_panel.set_markers([])
            return

        path = self.model.get_path_by_id(data_id)
        if not path:
            self.classification_panel.manual_box.setEnabled(False)
            self.classification_panel.clear_selection()
            self.classification_panel.chart_widget.setVisible(False)
            if self._is_active_mode():
                self.center_panel.set_markers([])
            return

        self.display_manual_annotation(path)
        self.classification_panel.manual_box.setEnabled(True)
        if self._is_active_mode():
            self.center_panel.set_markers([])

    # ---------------------------------------------------------------------
    # Classification Annotation + Schema
    # ---------------------------------------------------------------------
    def confirm_smart_annotation_as_manual(self):
        if self.classification_panel.is_batch_mode_active:
            batch_preds = self.classification_panel.pending_batch_results
            if not batch_preds:
                self._emit_status("Notice", "No batch predictions to confirm.")
                return

            old_batch_data = {}
            new_batch_data = {}
            confirmed_count = 0

            for path, pred_data in batch_preds.items():
                old_batch_data[path] = copy.deepcopy(self.model.smart_annotations.get(path))

                if isinstance(pred_data, str):
                    head = next(iter(self.model.label_definitions.keys()), "action")
                    formatted_data = {head: {"label": pred_data, "conf_dict": {pred_data: 1.0}}}
                elif isinstance(pred_data, dict) and "label" in pred_data:
                    head = next(iter(self.model.label_definitions.keys()), "action")
                    formatted_data = {head: copy.deepcopy(pred_data)}
                else:
                    formatted_data = copy.deepcopy(pred_data)

                for _, head_data in formatted_data.items():
                    if isinstance(head_data, dict) and "label" in head_data and "conf_dict" not in head_data:
                        confidence = head_data.get("confidence", 1.0)
                        head_data["conf_dict"] = {head_data["label"]: confidence}
                        remaining = 1.0 - confidence
                        if remaining > 0.001:
                            head_data["conf_dict"]["Other Uncertainties"] = remaining

                formatted_data["_confirmed"] = True
                new_batch_data[path] = copy.deepcopy(formatted_data)
                self.model.smart_annotations[path] = formatted_data
                self.itemStatusRefreshRequested.emit(path)
                confirmed_count += 1

            self.model.push_undo(
                CmdType.BATCH_SMART_ANNOTATION_RUN,
                old_data=old_batch_data,
                new_data=new_batch_data,
            )
            self.model.is_data_dirty = True
            self._emit_status("Saved", f"Batch Smart Annotations confirmed for {confirmed_count} items.", 2000)
            self.classification_panel.reset_smart_inference()
        else:
            path = self._get_current_action_path()
            if not path:
                return

            smart_data = self.model.smart_annotations.get(path)
            if not smart_data:
                self._emit_status("Notice", "No smart annotation available to confirm.")
                return

            old_data = copy.deepcopy(smart_data)
            new_data = copy.deepcopy(smart_data)
            new_data["_confirmed"] = True
            if new_data == old_data:
                return

            self.model.smart_annotations[path] = copy.deepcopy(new_data)
            self.model.is_data_dirty = True

            self.model.push_undo(
                CmdType.SMART_ANNOTATION_RUN,
                path=path,
                old_data=old_data,
                new_data=new_data,
            )
            self.itemStatusRefreshRequested.emit(path)
            self._emit_status("Saved", "Smart Annotation confirmed independently.", 1000)

        self.saveStateRefreshRequested.emit()
        self._request_filter_refresh()

    def save_manual_annotation(self, override_data=None, show_feedback: bool = True):
        path = self._get_current_action_path()
        if not path:
            return
        sample_id = self.model.get_data_id_by_path(path)
        if not sample_id:
            return

        raw_data = override_data if override_data is not None else self.classification_panel.get_annotation()
        cleaned = {key: value for key, value in raw_data.items() if value}
        if not cleaned:
            cleaned = None

        old_data = copy.deepcopy(self.model.manual_annotations.get(path))
        normalized_old = old_data if old_data else None
        if normalized_old == cleaned:
            return
        self.manualAnnotationSaveRequested.emit(sample_id, copy.deepcopy(cleaned), show_feedback)

    def clear_current_manual_annotation(self):
        path = self._get_current_action_path()
        if not path:
            return
        sample_id = self.model.get_data_id_by_path(path)
        if not sample_id:
            return

        old_data = copy.deepcopy(self.model.manual_annotations.get(path))
        if old_data:
            self.manualAnnotationSaveRequested.emit(sample_id, None, True)

        self.classification_panel.clear_selection()

    def clear_current_smart_annotation(self):
        path = self._get_current_action_path()
        if not path:
            return

        old_smart = copy.deepcopy(self.model.smart_annotations.get(path))
        if old_smart:
            self.model.push_undo(
                CmdType.SMART_ANNOTATION_RUN,
                path=path,
                old_data=old_smart,
                new_data=None,
            )
            self.model.smart_annotations.pop(path, None)
            self.model.is_data_dirty = True
            self._emit_status("Cleared", "Smart Annotation cleared.", 1000)
            self.saveStateRefreshRequested.emit()

        self.classification_panel.chart_widget.setVisible(False)
        self.classification_panel.batch_result_text.setVisible(False)

    def display_manual_annotation(self, path):
        data = self.model.manual_annotations.get(path, {})
        self.classification_panel.set_annotation(data)

        smart_data = self.model.smart_annotations.get(path, {})
        self.classification_panel.chart_widget.setVisible(False)
        if smart_data:
            for _, smart_item in smart_data.items():
                if not isinstance(smart_item, dict):
                    continue
                self.classification_panel.chart_widget.update_chart(
                    smart_item.get("label", ""),
                    smart_item.get("conf_dict", {}),
                )
                self.classification_panel.chart_widget.setVisible(True)
                break

    def handle_add_label_head(self, name):
        clean = name.strip().replace(" ", "_").lower()
        if not clean or clean in self.model.label_definitions:
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
        if head not in self.model.label_definitions:
            return
        if QMessageBox.question(self.classification_panel, "Remove", f"Remove '{head}'?") == QMessageBox.StandardButton.No:
            return
        self.schemaHeadRemoveRequested.emit(head)

    def add_custom_type(self, head):
        group = self.classification_panel.label_groups.get(head)
        if not group:
            return

        text = group.input_field.text().strip()
        if not text:
            return

        labels = self.model.label_definitions[head]["labels"]
        if any(label.lower() == text.lower() for label in labels):
            self._emit_status("Duplicate", "Label exists.")
            return

        self.schemaLabelAddRequested.emit(head, text)
        group.input_field.clear()

    def remove_custom_type(self, head, label):
        definition = self.model.label_definitions[head]
        if len(definition["labels"]) <= 1:
            return
        self.schemaLabelRemoveRequested.emit(head, label)

    def _request_filter_refresh(self, fallback: str = "first_visible"):
        self.filterRefreshRequested.emit(self.dataset_explorer_panel.filter_combo.currentIndex(), fallback)

    def _emit_status(self, title: str, message: str, duration: int = 1500):
        self.statusMessageRequested.emit(title, message, duration)

    def _is_active_mode(self) -> bool:
        return self._active_mode_index == 0
