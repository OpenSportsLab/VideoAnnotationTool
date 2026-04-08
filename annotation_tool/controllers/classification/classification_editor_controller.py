import copy

from PyQt6.QtWidgets import QMessageBox

from controllers.command_types import CmdType
from controllers.media_controller import MediaController
from utils import natural_sort_key

from .inference_manager import InferenceManager
from .train_manager import TrainManager


class ClassificationEditorController:
    """
    Single controller for Classification mode.
    Owns annotation logic and smart/train helper wiring.
    Dataset add/remove/filter/clear is handled centrally by DatasetExplorerController.
    """

    def __init__(self, main_window, media_controller: MediaController):
        self.main = main_window
        self.model = main_window.model
        self.media_controller = media_controller
        self.classification_panel = main_window.classification_panel
        self.dataset_explorer_panel = main_window.dataset_explorer_panel

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
            self.model.action_item_data, key=lambda data: natural_sort_key(data.get("name", ""))
        )
        action_names = [data["name"] for data in sorted_list]
        self.classification_panel.update_action_list(action_names)

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

    # ---------------------------------------------------------------------
    # Selection / Display
    # ---------------------------------------------------------------------
    def on_data_selected(self, data_id: str):
        if not data_id:
            self.classification_panel.manual_box.setEnabled(False)
            self.classification_panel.clear_selection()
            self.classification_panel.chart_widget.setVisible(False)
            if self.main.right_tabs.currentIndex() == 0:
                self.main.center_panel.set_markers([])
            return

        path = self.model.get_path_by_id(data_id)
        if not path:
            self.classification_panel.manual_box.setEnabled(False)
            self.classification_panel.clear_selection()
            self.classification_panel.chart_widget.setVisible(False)
            if self.main.right_tabs.currentIndex() == 0:
                self.main.center_panel.set_markers([])
            return

        self.display_manual_annotation(path)
        self.classification_panel.manual_box.setEnabled(True)
        center_panel = self.main.center_panel
        if self.main.right_tabs.currentIndex() == 0 and hasattr(center_panel, "view_layout"):
            center_panel.set_markers([])
            center_panel.view_layout.setCurrentWidget(center_panel.single_view_widget)

    # ---------------------------------------------------------------------
    # Classification Annotation + Schema
    # ---------------------------------------------------------------------
    def confirm_smart_annotation_as_manual(self):
        if self.classification_panel.is_batch_mode_active:
            batch_preds = self.classification_panel.pending_batch_results
            if not batch_preds:
                self.main.show_temp_msg("Notice", "No batch predictions to confirm.")
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
                self.main.update_action_item_status(path)
                confirmed_count += 1

            self.model.push_undo(
                CmdType.BATCH_SMART_ANNOTATION_RUN,
                old_data=old_batch_data,
                new_data=new_batch_data,
            )
            self.model.is_data_dirty = True
            self.main.show_temp_msg(
                "Saved", f"Batch Smart Annotations confirmed for {confirmed_count} items.", 2000
            )
            self.classification_panel.reset_smart_inference()
        else:
            path = self.main.get_current_action_path()
            if not path:
                return

            smart_data = self.model.smart_annotations.get(path)
            if not smart_data:
                self.main.show_temp_msg("Notice", "No smart annotation available to confirm.")
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
            self.main.update_action_item_status(path)
            self.main.show_temp_msg("Saved", "Smart Annotation confirmed independently.", 1000)

        self.main.update_save_export_button_state()
        self.main.dataset_explorer_controller.handle_filter_change(
            self.dataset_explorer_panel.filter_combo.currentIndex()
        )

    def save_manual_annotation(self, override_data=None):
        path = self.main.get_current_action_path()
        if not path:
            return

        raw_data = override_data if override_data is not None else self.classification_panel.get_annotation()
        cleaned = {key: value for key, value in raw_data.items() if value}
        if not cleaned:
            cleaned = None

        old_data = copy.deepcopy(self.model.manual_annotations.get(path))
        normalized_old = old_data if old_data else None
        if normalized_old == cleaned:
            return

        self.model.push_undo(
            CmdType.ANNOTATION_CONFIRM,
            path=path,
            old_data=old_data,
            new_data=cleaned,
        )

        if cleaned:
            self.model.manual_annotations[path] = cleaned
            self.main.show_temp_msg("Saved", "Annotation saved.", 1000)
        else:
            self.model.manual_annotations.pop(path, None)
            self.main.show_temp_msg("Cleared", "Annotation cleared.", 1000)

        self.main.update_action_item_status(path)
        self.main.update_save_export_button_state()
        self.main.dataset_explorer_controller.handle_filter_change(
            self.dataset_explorer_panel.filter_combo.currentIndex()
        )

    def clear_current_manual_annotation(self):
        path = self.main.get_current_action_path()
        if not path:
            return

        old_data = copy.deepcopy(self.model.manual_annotations.get(path))
        if old_data:
            self.model.push_undo(
                CmdType.ANNOTATION_CONFIRM,
                path=path,
                old_data=old_data,
                new_data=None,
            )
            self.model.manual_annotations.pop(path, None)
            self.main.update_action_item_status(path)
            self.main.update_save_export_button_state()
            self.main.show_temp_msg("Cleared", "Selection cleared.")

        self.classification_panel.clear_selection()

    def clear_current_smart_annotation(self):
        path = self.main.get_current_action_path()
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
            self.main.show_temp_msg("Cleared", "Smart Annotation cleared.", 1000)
            self.main.update_save_export_button_state()

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

        msg = QMessageBox(self.main)
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
        self.model.push_undo(CmdType.SCHEMA_ADD_CAT, head=clean, definition=definition)
        self.model.label_definitions[clean] = definition
        self.classification_panel.new_head_edit.clear()
        self.setup_dynamic_ui()
        self.main.update_save_export_button_state()

    def handle_remove_label_head(self, head):
        if head not in self.model.label_definitions:
            return
        if QMessageBox.question(self.main, "Remove", f"Remove '{head}'?") == QMessageBox.StandardButton.No:
            return

        affected = {}
        for key, value in self.model.manual_annotations.items():
            if head in value:
                affected[key] = copy.deepcopy(value[head])

        self.model.push_undo(
            CmdType.SCHEMA_DEL_CAT,
            head=head,
            definition=copy.deepcopy(self.model.label_definitions[head]),
            affected_data=affected,
        )

        del self.model.label_definitions[head]
        for key in affected:
            del self.model.manual_annotations[key][head]
            if not self.model.manual_annotations[key]:
                del self.model.manual_annotations[key]
            self.main.update_action_item_status(key)

        self.setup_dynamic_ui()
        self.display_manual_annotation(self.main.get_current_action_path())
        self.main.update_save_export_button_state()

    def add_custom_type(self, head):
        group = self.classification_panel.label_groups.get(head)
        if not group:
            return

        text = group.input_field.text().strip()
        if not text:
            return

        labels = self.model.label_definitions[head]["labels"]
        if any(label.lower() == text.lower() for label in labels):
            self.main.show_temp_msg("Duplicate", "Label exists.", icon=QMessageBox.Icon.Warning)
            return

        self.model.push_undo(CmdType.SCHEMA_ADD_LBL, head=head, label=text)
        labels.append(text)
        labels.sort()

        if hasattr(group, "update_radios"):
            group.update_radios(labels)
        else:
            group.update_checkboxes(labels)

        group.input_field.clear()
        self.main.update_save_export_button_state()

    def remove_custom_type(self, head, label):
        definition = self.model.label_definitions[head]
        if len(definition["labels"]) <= 1:
            return

        affected = {}
        for key, value in self.model.manual_annotations.items():
            if definition["type"] == "single_label" and value.get(head) == label:
                affected[key] = label
            elif definition["type"] == "multi_label" and label in value.get(head, []):
                affected[key] = copy.deepcopy(value[head])
        label_index = definition["labels"].index(label) if label in definition["labels"] else -1

        self.model.push_undo(
            CmdType.SCHEMA_DEL_LBL,
            head=head,
            label=label,
            label_index=label_index,
            affected_data=affected,
        )

        if label in definition["labels"]:
            definition["labels"].remove(label)

        for _, value in self.model.manual_annotations.items():
            if definition["type"] == "single_label" and value.get(head) == label:
                value[head] = None
            elif definition["type"] == "multi_label" and label in value.get(head, []):
                value[head].remove(label)

        group = self.classification_panel.label_groups.get(head)
        if group:
            if hasattr(group, "update_radios"):
                group.update_radios(definition["labels"])
            else:
                group.update_checkboxes(definition["labels"])

        self.display_manual_annotation(self.main.get_current_action_path())
        self.main.update_save_export_button_state()
