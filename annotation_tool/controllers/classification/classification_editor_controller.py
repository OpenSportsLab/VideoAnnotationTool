import copy
import os
from collections import defaultdict

from PyQt6.QtCore import QModelIndex
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from controllers.media_controller import MediaController
from models import CmdType
from utils import SUPPORTED_EXTENSIONS, natural_sort_key

from .inference_manager import InferenceManager
from .train_manager import TrainManager


class ClassificationEditorController:
    """
    Single controller for Classification mode.
    Owns annotation logic, tree navigation, smart/train helper wiring,
    and Classification-mode Dataset Explorer add/remove/filter/clear actions.
    """

    def __init__(self, main_window, media_controller: MediaController):
        self.main = main_window
        self.model = main_window.model
        self.media_controller = media_controller
        self.tree_model = main_window.tree_model
        self.panel = main_window.classification_panel
        self.dataset_explorer_panel = main_window.dataset_explorer_panel

        # Helper services remain separate, but are now owned by this controller.
        self.inference_manager = InferenceManager(self)
        self.train_manager = TrainManager(self)

    # ---------------------------------------------------------------------
    # Lifecycle / Wiring
    # ---------------------------------------------------------------------
    def setup_connections(self):
        self.panel.annotation_saved.connect(self.save_manual_annotation)
        self.panel.smart_confirm_requested.connect(self.confirm_smart_annotation_as_manual)
        self.panel.hand_clear_requested.connect(self.clear_current_manual_annotation)
        self.panel.smart_clear_requested.connect(self.clear_current_smart_annotation)
        self.panel.add_head_clicked.connect(self.handle_add_label_head)
        self.panel.remove_head_clicked.connect(self.handle_remove_label_head)
        self.panel.smart_infer_requested.connect(self.inference_manager.start_inference)
        self.panel.confirm_infer_requested.connect(self.save_manual_annotation)

    def reset_ui(self):
        self.panel.clear_dynamic_labels()
        self.panel.manual_box.setEnabled(False)
        self.panel.reset_smart_inference()
        self.panel.reset_train_ui()

    def setup_dynamic_ui(self):
        self.panel.setup_dynamic_labels(self.model.label_definitions)
        self.panel.task_label.setText(f"Task: {self.model.current_task_name}")
        self._connect_dynamic_type_buttons()

    def sync_batch_inference_dropdowns(self):
        sorted_list = sorted(
            self.model.action_item_data, key=lambda data: natural_sort_key(data.get("name", ""))
        )
        action_names = [data["name"] for data in sorted_list]
        self.panel.update_action_list(action_names)

    def _connect_dynamic_type_buttons(self):
        for head, group in self.panel.label_groups.items():
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
            group.value_changed.connect(
                lambda _, value, selected_head=head: self.handle_ui_selection_change(selected_head, value)
            )

    # ---------------------------------------------------------------------
    # Selection / Playback / Navigation
    # ---------------------------------------------------------------------
    def on_item_selected(self, current, previous):
        if not current.isValid():
            return

        path = current.data(self.main.tree_model.FilePathRole)
        self.display_manual_annotation(path)
        self.panel.manual_box.setEnabled(True)
        self.media_controller.load_and_play(path)

        center_panel = self.main.center_panel
        if hasattr(center_panel, "view_layout"):
            center_panel.view_layout.setCurrentWidget(center_panel.single_view_widget)

    def show_all_views(self):
        tree_view = self.dataset_explorer_panel.tree
        curr_idx = tree_view.currentIndex()
        if not curr_idx.isValid():
            return

        model = self.tree_model
        if model.rowCount(curr_idx) == 0:
            return

        paths = []
        for idx in range(model.rowCount(curr_idx)):
            child_idx = model.index(idx, 0, curr_idx)
            paths.append(child_idx.data(self.main.tree_model.FilePathRole))

        supported = [path for path in paths if path.lower().endswith(SUPPORTED_EXTENSIONS[:3])]
        self.main.center_panel.show_all_views(supported)

    # ---------------------------------------------------------------------
    # Classification Annotation + Schema
    # ---------------------------------------------------------------------
    def confirm_smart_annotation_as_manual(self):
        if self.panel.is_batch_mode_active:
            batch_preds = self.panel.pending_batch_results
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
            self.panel.reset_smart_inference()
        else:
            path = self.main.get_current_action_path()
            if not path:
                return

            smart_data = self.model.smart_annotations.get(path)
            if not smart_data:
                self.main.show_temp_msg("Notice", "No smart annotation available to confirm.")
                return

            old_data = copy.deepcopy(smart_data)
            self.model.smart_annotations[path]["_confirmed"] = True
            self.model.is_data_dirty = True
            new_data = copy.deepcopy(self.model.smart_annotations[path])

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

        raw_data = override_data if override_data is not None else self.panel.get_annotation()
        cleaned = {key: value for key, value in raw_data.items() if value}
        if not cleaned:
            cleaned = None

        old_data = copy.deepcopy(self.model.manual_annotations.get(path))
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

        self.panel.clear_selection()

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

        self.panel.chart_widget.setVisible(False)
        self.panel.batch_result_text.setVisible(False)

    def display_manual_annotation(self, path):
        data = self.model.manual_annotations.get(path, {})
        self.panel.set_annotation(data)

        smart_data = self.model.smart_annotations.get(path, {})
        if smart_data:
            for _, smart_item in smart_data.items():
                if not isinstance(smart_item, dict):
                    continue
                self.panel.chart_widget.update_chart(
                    smart_item.get("label", ""),
                    smart_item.get("conf_dict", {}),
                )
                self.panel.chart_widget.setVisible(True)
                break

    def handle_ui_selection_change(self, head, new_val):
        if self.main.history_manager._is_undoing_redoing:
            return

        path = self.main.get_current_action_path()
        if not path:
            return

        old_val = self.model.manual_annotations.get(path, {}).get(head)
        for command in reversed(self.model.undo_stack):
            if (
                command["type"] == CmdType.UI_CHANGE
                and command["path"] == path
                and command["head"] == head
            ):
                old_val = command["new_val"]
                break

        self.model.push_undo(
            CmdType.UI_CHANGE,
            path=path,
            head=head,
            old_val=old_val,
            new_val=new_val,
        )

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
        self.panel.new_head_edit.clear()
        self.setup_dynamic_ui()

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

    def add_custom_type(self, head):
        group = self.panel.label_groups.get(head)
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

        self.model.push_undo(
            CmdType.SCHEMA_DEL_LBL,
            head=head,
            label=label,
            affected_data=affected,
        )

        if label in definition["labels"]:
            definition["labels"].remove(label)

        for _, value in self.model.manual_annotations.items():
            if definition["type"] == "single_label" and value.get(head) == label:
                value[head] = None
            elif definition["type"] == "multi_label" and label in value.get(head, []):
                value[head].remove(label)

        group = self.panel.label_groups.get(head)
        if group:
            if hasattr(group, "update_radios"):
                group.update_radios(definition["labels"])
            else:
                group.update_checkboxes(definition["labels"])

        self.display_manual_annotation(self.main.get_current_action_path())

    # ---------------------------------------------------------------------
    # Dataset Explorer Delegated Actions (Classification mode)
    # ---------------------------------------------------------------------
    def add_dataset_items(self):
        if not self.model.json_loaded:
            QMessageBox.warning(self.main, "Warning", "Please create or load a project first.")
            return

        filters = "Media Files (*.mp4 *.avi *.mov *.mkv *.jpg *.jpeg *.png *.bmp);;All Files (*)"
        start_dir = self.model.current_working_directory or ""
        files, _ = QFileDialog.getOpenFileNames(self.main, "Select Data to Add", start_dir, filters)
        if not files:
            return

        if not self.model.current_working_directory:
            self.model.current_working_directory = os.path.dirname(files[0])

        added_count = 0
        is_multi_view = getattr(self.model, "is_multi_view", False)

        if is_multi_view:
            grouped = defaultdict(list)
            for file_path in files:
                grouped[os.path.dirname(file_path)].append(file_path)

            for _, paths in grouped.items():
                paths.sort()
                name = os.path.basename(os.path.dirname(paths[0])) if len(paths) > 1 else os.path.basename(paths[0])
                if self.model.has_action_name(name):
                    continue

                main_path = paths[0]
                self.model.add_action_item(name=name, path=main_path, source_files=paths)
                item = self.tree_model.add_entry(name=name, path=main_path, source_files=paths)
                self.model.action_item_map[main_path] = item
                self.main.update_action_item_status(main_path)
                added_count += 1
        else:
            for file_path in files:
                if self.model.has_action_path(file_path):
                    continue

                name = os.path.basename(file_path)
                self.model.add_action_item(name=name, path=file_path, source_files=[file_path])
                item = self.tree_model.add_entry(name=name, path=file_path, source_files=[file_path])
                self.model.action_item_map[file_path] = item
                self.main.update_action_item_status(file_path)
                added_count += 1

        if added_count > 0:
            self._mark_dirty_and_refresh()
            self.filter_dataset_items(self.dataset_explorer_panel.filter_combo.currentIndex())
            self.main.show_temp_msg("Added", f"Added {added_count} items.")
            self.sync_batch_inference_dropdowns()

    def clear_dataset_items(self):
        if not self.model.json_loaded:
            return

        msg = QMessageBox(self.main)
        msg.setWindowTitle("Clear Workspace")
        msg.setText("Clear workspace? Unsaved changes will be lost.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.media_controller.stop()
            self.clear_workspace()

    def remove_dataset_item(self, index: QModelIndex):
        path, action_idx = self._path_from_index(index)
        if not path:
            return

        is_current_selection = self.main.get_current_action_path() == path

        removed = self.model.remove_action_item_by_path(path)
        if not removed:
            return

        self._remove_tree_row(action_idx)

        if is_current_selection:
            self.media_controller.stop()
            self.main.center_panel.load_video(None)
            self.panel.clear_selection()
            self.panel.reset_smart_inference()
            self.panel.manual_box.setEnabled(False)

        self._mark_dirty_and_refresh()
        self.main.show_temp_msg("Removed", "Item removed.")
        self.sync_batch_inference_dropdowns()

    def filter_dataset_items(self, index):
        filter_idx = self.dataset_explorer_panel.filter_combo.currentIndex() if index is None else index
        if filter_idx < 0:
            return

        for row in range(self.tree_model.rowCount()):
            idx = self.tree_model.index(row, 0)
            item = self.tree_model.itemFromIndex(idx)
            if not item:
                continue

            path = item.data(getattr(self.tree_model, "FilePathRole", 0x0100))
            is_hand = path in self.model.manual_annotations and bool(self.model.manual_annotations[path])
            is_smart = self.model.smart_annotations.get(path, {}).get("_confirmed", False)
            is_none = not is_hand and not is_smart

            hidden = False
            if filter_idx == 1 and not is_hand:
                hidden = True
            elif filter_idx == 2 and not is_smart:
                hidden = True
            elif filter_idx == 3 and not is_none:
                hidden = True

            self.dataset_explorer_panel.tree.setRowHidden(row, QModelIndex(), hidden)

    def clear_workspace(self):
        self.tree_model.clear()
        self.model.reset(full_reset=True)
        self.main.update_save_export_button_state()

        self.panel.manual_box.setEnabled(False)
        self.main.center_panel.load_video(None)
        self.panel.reset_smart_inference()
        self.panel.reset_train_ui()
        self.setup_dynamic_ui()
        self.sync_batch_inference_dropdowns()

    # ---------------------------------------------------------------------
    # Internal Helpers
    # ---------------------------------------------------------------------
    def _mark_dirty_and_refresh(self):
        self.model.is_data_dirty = True
        self.main.update_save_export_button_state()

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
        path = action_idx.data(getattr(self.tree_model, "FilePathRole", 0x0100))
        return path, action_idx

    def _remove_tree_row(self, action_idx: QModelIndex):
        if action_idx.isValid():
            self.tree_model.removeRow(action_idx.row(), action_idx.parent())
