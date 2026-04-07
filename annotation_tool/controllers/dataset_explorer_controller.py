import os
import datetime
import json

from PyQt6.QtCore import QModelIndex, QObject, pyqtSignal, QUrl
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from utils import natural_sort_key


class DatasetExplorerController(QObject):
    """
    Controller for the Dataset Explorer.
    Owns project load/save/export/create lifecycle and populates the shared tree model.
    """
    dataSelected = pyqtSignal(str)

    def __init__(self, main_window, panel, tree_model, app_state, media_controller):
        super().__init__()
        self.main = main_window
        self.panel = panel
        self.tree_model = tree_model
        self.app_state = app_state
        self.media_controller = media_controller

        self._setup_connections()

    def _setup_connections(self):
        """Connect Panel signals to Controller slots."""
        self.panel.addDataRequested.connect(self.handle_add_sample)
        self.panel.clear_btn.clicked.connect(self.handle_clear_workspace)
        self.panel.removeItemRequested.connect(self.handle_remove_item)
        self.panel.filter_combo.currentIndexChanged.connect(self.handle_filter_change)
        self.panel.sampleNavigateRequested.connect(self.navigate_samples)

        # Dataset Explorer owns selection normalization/media routing and emits Data IDs.
        self.panel.tree.selectionModel().currentChanged.connect(self._on_selection_changed)

    def _set_annotation_panels_enabled(self, enabled: bool):
        self.main.classification_panel.manual_box.setEnabled(enabled)
        self.main.localization_panel.setEnabled(enabled)
        self.main.description_panel.setEnabled(enabled)
        self.main.dense_panel.setEnabled(enabled)

    # ---------------------------------------------------------------------
    # Tree Population
    # ---------------------------------------------------------------------
    def populate_tree(self):
        """
        Populate Dataset Explorer tree model from AppState.action_item_data.
        """
        self.app_state.ensure_data_ids()
        self.tree_model.clear()
        self.app_state.action_item_map.clear()

        sorted_list = sorted(
            self.app_state.action_item_data,
            key=lambda d: natural_sort_key(d.get("name", ""))
        )

        if hasattr(self.main, "classification_editor_controller"):
            self.main.classification_editor_controller.sync_batch_inference_dropdowns()

        for data in sorted_list:
            path = data["path"]
            name = data["name"]
            sources = data.get("source_files")
            data_id = data.get("data_id")

            item = self.tree_model.add_entry(
                name=name,
                path=path,
                source_files=sources,
                data_id=data_id,
            )
            self.app_state.action_item_map[path] = item
            self.update_item_status(path)

        self.handle_filter_change(self.panel.filter_combo.currentIndex())

        if self.tree_model.rowCount() > 0:
            first_index = self.tree_model.index(0, 0)
            if first_index.isValid():
                self.panel.tree.setCurrentIndex(first_index)

    def update_item_status(self, action_path: str):
        """Update done/not-done icon for one action."""
        item = self.app_state.action_item_map.get(action_path)
        if not item:
            return

        is_done = self.app_state.is_action_done(action_path)

        done_icon = getattr(self.main, "done_icon", None)
        empty_icon = getattr(self.main, "empty_icon", None)

        if done_icon and empty_icon:
            item.setIcon(done_icon if is_done else empty_icon)

    # ---------------------------------------------------------------------
    # Panel Dispatchers (Controller-owned)
    # ---------------------------------------------------------------------
    def _active_mode_idx(self) -> int:
        return self.main.right_tabs.currentIndex()

    def handle_add_sample(self):
        if not self.app_state.json_loaded:
            QMessageBox.warning(self.main, "Warning", "Please create or load a project first.")
            return

        start_dir = self.app_state.current_working_directory or ""
        files, _ = QFileDialog.getOpenFileNames(
            self.main,
            "Select Samples to Add",
            start_dir,
            self._sample_file_filter_for_mode(self._active_mode_idx()),
        )
        if not files:
            return

        if not self.app_state.current_working_directory:
            self.app_state.current_working_directory = os.path.dirname(files[0])

        groups = self._group_selected_files(files)
        added_count = 0
        first_idx = None

        for source_group in groups:
            sample = self._build_sample_for_mode(source_group)
            if not sample:
                continue

            entry = self.app_state.add_action_item(**sample)
            data_id = entry.get("data_id")
            item = self.tree_model.add_entry(
                name=entry["name"],
                path=entry["path"],
                source_files=entry.get("source_files"),
                data_id=data_id,
            )
            self.app_state.action_item_map[entry["path"]] = item
            self.update_item_status(entry["path"])
            if first_idx is None:
                first_idx = item.index()
            added_count += 1

        if added_count <= 0:
            return

        self._mark_dirty_and_refresh()
        self.handle_filter_change(self.panel.filter_combo.currentIndex())
        self.main.show_temp_msg("Added", f"Added {added_count} samples.")

        if self._active_mode_idx() == 0 and hasattr(self.main, "classification_editor_controller"):
            self.main.classification_editor_controller.sync_batch_inference_dropdowns()

        if first_idx and first_idx.isValid():
            self.panel.tree.setCurrentIndex(first_idx)
            self.panel.tree.setFocus()

    def handle_clear_workspace(self):
        if not self.app_state.json_loaded:
            return

        msg = QMessageBox(self.main)
        msg.setWindowTitle("Clear Workspace")
        msg.setText("Clear workspace? Unsaved changes will be lost.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        self.media_controller.stop()
        self._clear_all_samples_keep_project()
        self.main.show_temp_msg("Cleared", "Workspace reset.")

    def handle_remove_item(self, index: QModelIndex):
        path, action_idx = self._path_from_index(index)
        if not path:
            return

        if self._active_mode_idx() == 3:
            reply = QMessageBox.question(
                self.main,
                "Remove Sample",
                f"Are you sure you want to remove this sample and its annotations?\n\n{os.path.basename(path)}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        removed = self._remove_sample_by_mode(path)
        if not removed:
            return

        self._remove_tree_row(action_idx)
        self._reset_panels_after_removed_path(path)
        self._mark_dirty_and_refresh()
        self.main.show_temp_msg("Removed", "Sample removed.")
        self.handle_filter_change(self.panel.filter_combo.currentIndex())

        if self._active_mode_idx() == 0 and hasattr(self.main, "classification_editor_controller"):
            self.main.classification_editor_controller.sync_batch_inference_dropdowns()

    def handle_filter_change(self, index):
        root = self.tree_model.invisibleRootItem()
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

    def _on_selection_changed(self, current, previous):
        self._set_annotation_panels_enabled(current.isValid())
        if not current.isValid():
            self.dataSelected.emit("")
            return

        action_idx = self._get_action_index(current)
        if not action_idx.isValid():
            self.dataSelected.emit("")
            return

        data_id = action_idx.data(getattr(self.tree_model, "DataIdRole", 0x0101))
        if not data_id:
            path = action_idx.data(getattr(self.tree_model, "FilePathRole", 0x0100))
            data_id = self.app_state.get_data_id_by_path(path)
        if not data_id:
            self.dataSelected.emit("")
            return

        self._route_media_for_selection(current, data_id)
        self.dataSelected.emit(data_id)

    def _route_media_for_selection(self, selected_idx: QModelIndex, data_id: str):
        media_paths = [
            p for p in (self._resolve_media_path(path) for path in self.app_state.get_sources_by_id(data_id)) if p
        ]
        if not media_paths:
            return

        mode_idx = self._active_mode_idx()
        is_multiview = mode_idx == 0 and len(media_paths) > 1 and bool(self.app_state.is_multi_view)
        if is_multiview:
            self.main.center_panel.show_all_views(media_paths)

        selected_path = selected_idx.data(getattr(self.tree_model, "FilePathRole", 0x0100))
        preferred = self._resolve_media_path(selected_path) if selected_idx.isValid() else None
        if preferred and not os.path.isfile(preferred):
            preferred = None
        primary_path = preferred or media_paths[0]
        self.main.media_controller.load_and_play(primary_path)

    def _resolve_media_path(self, path):
        if not path:
            return None
        cwd = self.app_state.current_working_directory
        if cwd and not os.path.isabs(path):
            path = os.path.normpath(os.path.join(cwd, path))
        if path and os.path.exists(path):
            return path
        return None

    def _get_action_index(self, index: QModelIndex) -> QModelIndex:
        """Normalize child selection to its top-level action index."""
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

    def _mark_dirty_and_refresh(self):
        self.app_state.is_data_dirty = True
        self.main.update_save_export_button_state()

    def navigate_samples(self, step: int):
        """
        Move selection across top-level dataset items only.
        Respects active row hiding (filters) and normalizes child selection to parent.
        """
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

    def _sample_file_filter_for_mode(self, mode_idx: int) -> str:
        if mode_idx in (1, 3):
            return "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)"
        return "Media Files (*.mp4 *.avi *.mov *.mkv *.jpg *.jpeg *.png *.bmp);;All Files (*)"

    def _group_selected_files(self, files):
        if self._active_mode_idx() == 0 and bool(self.app_state.is_multi_view):
            grouped = {}
            for file_path in files:
                grouped.setdefault(os.path.dirname(file_path), []).append(file_path)
            groups = []
            for _, group_paths in grouped.items():
                group_paths.sort()
                groups.append(group_paths)
            return groups
        return [[path] for path in files]

    def _build_sample_for_mode(self, source_group):
        mode_idx = self._active_mode_idx()
        primary = source_group[0]

        if mode_idx == 0 and bool(self.app_state.is_multi_view):
            sample_name = (
                os.path.basename(os.path.dirname(primary))
                if len(source_group) > 1
                else os.path.basename(primary)
            )
            if self.app_state.has_action_name(sample_name):
                return None
            return {
                "name": sample_name,
                "path": primary,
                "source_files": source_group,
            }

        if mode_idx == 2:
            if self.app_state.has_description_path(primary):
                return None
            sample_name = os.path.basename(primary)
            return {
                "name": sample_name,
                "path": primary,
                "source_files": [primary],
                "id": sample_name,
                "metadata": {"path": primary, "questions": []},
                "inputs": [{"type": "video", "name": sample_name, "path": primary}],
                "captions": [],
            }

        if self.app_state.has_action_path(primary):
            return None

        sample_name = os.path.basename(primary)
        return {
            "name": sample_name,
            "path": primary,
            "source_files": [primary],
        }

    def _remove_sample_by_mode(self, path: str) -> bool:
        if self._active_mode_idx() == 2:
            removed = self.app_state.remove_description_action_by_path(path)
            return bool(removed)
        return self.app_state.remove_action_item_by_path(path)

    def _label_state_for_mode(self, path: str, data_id: str):
        mode_idx = self._active_mode_idx()
        if mode_idx == 0:
            hand = bool(self.app_state.manual_annotations.get(path))
            smart = bool(self.app_state.smart_annotations.get(path, {}).get("_confirmed", False))
            return hand, smart
        if mode_idx == 1:
            hand = bool(self.app_state.localization_events.get(path))
            smart = bool(self.app_state.smart_localization_events.get(path))
            return hand, smart
        if mode_idx == 2:
            data = self.app_state.get_item_by_id(data_id)
            captions = data.get("captions", []) if data else []
            hand = any(c.get("text", "").strip() for c in captions if isinstance(c, dict))
            return hand, False
        if mode_idx == 3:
            hand = bool(self.app_state.dense_description_events.get(path))
            return hand, False
        return False, False

    def _reset_panels_after_removed_path(self, removed_path: str):
        current_id = self.panel.tree.currentIndex()
        current_path = self._path_from_index(current_id)[0] if current_id.isValid() else None
        if current_path and current_path != removed_path:
            return

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

        self.main.desc_editor_controller.current_action_path = None
        self.main.description_panel.caption_edit.clear()
        self.main.description_panel.caption_edit.setEnabled(False)
        self.main.description_panel.setEnabled(False)

        self.main.dense_editor_controller.current_video_path = None
        self.main.dense_panel.table.set_data([])
        self.main.dense_panel.input_widget.set_text("")
        self.main.dense_panel.setEnabled(False)
        self.dataSelected.emit("")

    def _clear_all_samples_keep_project(self):
        self.app_state.action_item_data = []
        self.app_state.action_path_to_name = {}
        self.app_state.action_item_map.clear()
        self.app_state.action_id_to_path = {}
        self.app_state.action_id_to_item = {}

        self.app_state.manual_annotations = {}
        self.app_state.smart_annotations = {}
        self.app_state.localization_events = {}
        self.app_state.smart_localization_events = {}
        self.app_state.dense_description_events = {}
        self.app_state.imported_input_metadata = {}
        self.app_state.imported_action_metadata = {}
        self.app_state.undo_stack.clear()
        self.app_state.redo_stack.clear()

        self.tree_model.clear()
        self.app_state.is_data_dirty = True
        self.app_state.json_loaded = True

        self.main.classification_panel.clear_selection()
        self.main.classification_panel.reset_smart_inference()
        self.main.classification_panel.reset_train_ui()
        self.main.classification_panel.manual_box.setEnabled(False)
        self.main.classification_editor_controller.sync_batch_inference_dropdowns()

        self.main.localization_editor_controller.current_video_path = None
        self.main.localization_editor_controller.current_head = None
        self.main.localization_panel.annot_mgmt.update_schema(self.app_state.label_definitions)
        self.main.localization_panel.table.set_data([])
        if hasattr(self.main.localization_panel, "smart_widget"):
            self.main.localization_panel.smart_widget.smart_table.set_data([])
        self.main.localization_panel.setEnabled(False)

        self.main.desc_editor_controller.current_action_path = None
        self.main.description_panel.caption_edit.clear()
        self.main.description_panel.caption_edit.setEnabled(False)
        self.main.description_panel.setEnabled(False)

        self.main.dense_editor_controller.current_video_path = None
        self.main.dense_panel.table.set_data([])
        self.main.dense_panel.input_widget.set_text("")
        self.main.dense_panel.setEnabled(False)

        self.main.center_panel.player.setSource(QUrl())
        self.main.center_panel.video_widget.update()
        self.main.center_panel.set_markers([])
        self.dataSelected.emit("")
        self.main.update_save_export_button_state()

    # ---------------------------------------------------------------------
    # Project Lifecycle
    # ---------------------------------------------------------------------
    def load_project(self, data, file_path):
        """Load project from JSON data/path. Detects mode internally."""
        json_type = self.app_state.detect_json_type(data)

        if json_type == "classification":
            self.main.show_classification_view()
            loaded = self._load_classification_project(data, file_path)
            if not loaded:
                self.main.show_welcome_view()
            return loaded

        if json_type == "localization":
            self.main.show_localization_view()
            loaded = self._load_localization_project(data, file_path)
            if not loaded:
                self.main.show_welcome_view()
            return loaded

        if json_type == "description":
            self.main.show_description_view()
            loaded = self._load_description_project(data, file_path)
            if not loaded:
                self.main.show_welcome_view()
            return loaded

        if json_type == "dense_description":
            self.main.show_dense_description_view()
            loaded = self._load_dense_project(data, file_path)
            if not loaded:
                self.main.show_welcome_view()
            return loaded

        return False

    def create_new_project(self, mode):
        """Create a blank project for the selected mode."""
        if mode == "classification":
            self._create_new_classification_project()
        elif mode == "localization":
            self._create_new_localization_project()
        elif mode == "description":
            self._create_new_description_project()
        elif mode == "dense_description":
            self._create_new_dense_project()

    def save_project(self):
        """Save current project to existing path or export when path is missing."""
        mode_idx = self.main.right_tabs.currentIndex()
        save_path = self.app_state.current_json_path

        if mode_idx == 2 and save_path:
            # Description keeps editor text in-memory through this explicit save step.
            self.main.desc_editor_controller.save_current_annotation()

        if not save_path:
            return self.export_project()

        if mode_idx == 1:
            return self._write_localization_json(save_path)
        if mode_idx == 2:
            return self._write_description_json(save_path)
        if mode_idx == 3:
            return self._write_dense_json(save_path)
        return self._write_classification_json(save_path)

    def export_project(self):
        """Export current project to a user-selected file path."""
        mode_idx = self.main.right_tabs.currentIndex()

        if mode_idx == 2:
            self.main.desc_editor_controller.save_current_annotation()

        if mode_idx == 1:
            path, _ = QFileDialog.getSaveFileName(
                self.main, "Export Localization JSON", "", "JSON (*.json)"
            )
            if not path:
                return False
            result = self._write_localization_json(path)
            if result:
                self.app_state.current_json_path = path
                self.main.update_save_export_button_state()
            return result

        if mode_idx == 2:
            path, _ = QFileDialog.getSaveFileName(
                self.main, "Export Description JSON", "", "JSON (*.json)"
            )
            if not path:
                return False
            return self._write_description_json(path)

        if mode_idx == 3:
            path, _ = QFileDialog.getSaveFileName(
                self.main, "Export Dense JSON", "", "JSON (*.json)"
            )
            if not path:
                return False
            return self._write_dense_json(path)

        path, _ = QFileDialog.getSaveFileName(
            self.main, "Save Classification JSON", "", "JSON (*.json)"
        )
        if not path:
            return False
        result = self._write_classification_json(path)
        if result:
            self.app_state.current_json_path = path
            self.main.update_save_export_button_state()
        return result

    def close_project(self):
        """Close current project and return to welcome view."""
        if not self.main.check_and_close_current_project():
            return

        self.main.reset_all_managers()
        self.app_state.reset(full_reset=True)
        self.main.update_save_export_button_state()
        self.main.show_welcome_view()
        self.main.show_temp_msg("Project Closed", "Returned to Home Screen", duration=1000)

    # ---------------------------------------------------------------------
    # Internal: Validation Helpers
    # ---------------------------------------------------------------------
    def _show_validation_error(self, title, error_text):
        QMessageBox.critical(self.main, title, error_text)

    def _show_validation_warning_and_confirm(self, warning_text):
        result = QMessageBox.warning(
            self.main,
            "Validation Warnings",
            warning_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    # ---------------------------------------------------------------------
    # Internal: Mode Loaders
    # ---------------------------------------------------------------------
    def _load_classification_project(self, data, file_path):
        valid, err, warn = self.app_state.validate_gac_json(data)

        if not valid:
            if len(err) > 1000:
                err = err[:1000] + "\n... (truncated)"
            error_text = (
                "The imported JSON contains critical errors and cannot be loaded.\n\n"
                f"{err}\n\n"
                "--------------------------------------------------\n"
                "💡 Please download the correct Classification JSON format from:\n"
                "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars"
            )
            self._show_validation_error("Validation Error (Classification)", error_text)
            return False

        if warn:
            if len(warn) > 1000:
                warn = warn[:1000] + "\n... (truncated)"
            if not self._show_validation_warning_and_confirm(
                "The file contains warnings:\n\n" + warn + "\n\nContinue loading?"
            ):
                return False

        self.app_state.reset(full_reset=True)

        self.app_state.current_working_directory = os.path.dirname(file_path)
        self.app_state.current_task_name = data.get("task", "N/A")
        self.app_state.modalities = data.get("modalities", [])

        self.app_state.label_definitions = {}
        if "labels" in data:
            for key, value in data["labels"].items():
                clean_key = key.strip().replace(" ", "_").lower()
                self.app_state.label_definitions[clean_key] = {
                    "type": value["type"],
                    "labels": sorted(list(set(value.get("labels", []))))
                }

        self.main.classification_editor_controller.setup_dynamic_ui()

        self.app_state.is_multi_view = any(
            len(item.get("inputs", [])) > 1
            for item in data.get("data", [])
        )

        for item in data.get("data", []):
            aid = item.get("id")
            if not aid:
                continue

            src_files = []
            for inp in item.get("inputs", []):
                raw_path = inp.get("path", "")
                if os.path.isabs(raw_path):
                    final_path = raw_path
                else:
                    final_path = os.path.normpath(
                        os.path.join(self.app_state.current_working_directory, raw_path)
                    )

                src_files.append(final_path)
                self.app_state.imported_input_metadata[(aid, os.path.basename(final_path))] = inp.get(
                    "metadata", {}
                )

            path_key = src_files[0] if src_files else aid
            self.app_state.add_action_item(name=aid, path=path_key, source_files=src_files)
            self.app_state.imported_action_metadata[path_key] = item.get("metadata", {})

            lbls = item.get("labels", {})
            manual = {}
            has_labels = False
            for head, content in lbls.items():
                clean_head = head.strip().replace(" ", "_").lower()
                if clean_head in self.app_state.label_definitions:
                    definition = self.app_state.label_definitions[clean_head]
                    if isinstance(content, dict):
                        if definition["type"] == "single_label" and content.get("label") in definition["labels"]:
                            manual[clean_head] = content.get("label")
                            has_labels = True
                        elif definition["type"] == "multi_label":
                            vals = [x for x in content.get("labels", []) if x in definition["labels"]]
                            if vals:
                                manual[clean_head] = vals
                                has_labels = True
            if has_labels:
                self.app_state.manual_annotations[path_key] = manual

            smart_lbls = item.get("smart_labels", {})
            smart = {}
            for head, content in smart_lbls.items():
                clean_head = head.strip().replace(" ", "_").lower()
                if clean_head in self.app_state.label_definitions and isinstance(content, dict):
                    label_value = content.get("label")
                    smart[clean_head] = {
                        "label": label_value,
                        "conf_dict": content.get(
                            "conf_dict", {label_value: content.get("confidence", 1.0)}
                        )
                    }
            if smart:
                smart["_confirmed"] = True
                self.app_state.smart_annotations[path_key] = smart

        self.app_state.current_json_path = file_path
        self.app_state.json_loaded = True

        self.populate_tree()
        self.main.update_save_export_button_state()

        self.main.show_temp_msg(
            "Mode Switched",
            f"Project loaded with {len(self.app_state.action_item_data)} items.\n\nCurrent Mode: CLASSIFICATION",
            duration=1500,
            icon=QMessageBox.Icon.Information,
        )

        return True

    def _load_localization_project(self, data, file_path):
        is_valid, error_msg, warning_msg = self.app_state.validate_loc_json(data)

        if not is_valid:
            if len(error_msg) > 800:
                error_msg = error_msg[:800] + "\n... (truncated)"
            error_text = (
                "Critical errors found in JSON. Load aborted.\n\n"
                f"{error_msg}\n\n"
                "--------------------------------------------------\n"
                "💡 Please download the correct Localization JSON format from:\n"
                "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-localization-snbas"
            )
            self._show_validation_error("Validation Error", error_text)
            return False

        if warning_msg:
            if len(warning_msg) > 800:
                warning_msg = warning_msg[:800] + "\n... (truncated)"
            if not self._show_validation_warning_and_confirm(
                "The file contains warnings:\n\n"
                + warning_msg
                + "\n\nDo you want to continue loading?"
            ):
                return False

        self.app_state.reset(full_reset=True)

        project_root = os.path.dirname(os.path.abspath(file_path))
        self.app_state.current_working_directory = project_root

        self.app_state.current_task_name = data.get("dataset_name", data.get("task", "Localization Task"))
        self.app_state.modalities = data.get("modalities", ["video"])

        if "labels" in data:
            self.app_state.label_definitions = data["labels"]
            self.main.localization_editor_controller.right_panel.annot_mgmt.update_schema(
                self.app_state.label_definitions
            )

            default_head = None
            if "ball_action" in self.app_state.label_definitions:
                default_head = "ball_action"
            elif "action" in self.app_state.label_definitions:
                default_head = "action"
            elif list(self.app_state.label_definitions.keys()):
                default_head = list(self.app_state.label_definitions.keys())[0]

            if default_head:
                self.main.localization_editor_controller.current_head = default_head
                self.main.localization_editor_controller.right_panel.annot_mgmt.tabs.set_current_head(
                    default_head
                )

        missing_files = []
        loaded_count = 0

        for item in data.get("data", []):
            inputs = item.get("inputs", [])
            if not inputs or not isinstance(inputs, list):
                continue

            raw_path = inputs[0].get("path", "")
            aid = item.get("id")
            if not aid:
                aid = os.path.splitext(os.path.basename(raw_path))[0]

            final_path = raw_path
            if os.path.isabs(raw_path) and os.path.exists(raw_path):
                final_path = raw_path
            else:
                norm_raw = raw_path.replace("\\", "/")
                abs_path_strict = os.path.normpath(os.path.join(project_root, norm_raw))

                if os.path.exists(abs_path_strict):
                    final_path = abs_path_strict
                else:
                    filename = os.path.basename(norm_raw)
                    abs_path_flat = os.path.join(project_root, filename)
                    if os.path.exists(abs_path_flat):
                        final_path = abs_path_flat
                    else:
                        final_path = abs_path_strict
                        missing_files.append(f"{aid}: {filename}")

            self.app_state.add_action_item(name=aid, path=final_path, source_files=[final_path])

            raw_events = item.get("events", [])
            processed_events = []
            if isinstance(raw_events, list):
                for evt in raw_events:
                    if not isinstance(evt, dict):
                        continue
                    try:
                        pos_ms = int(evt.get("position_ms", 0))
                    except ValueError:
                        pos_ms = 0

                    processed_events.append(
                        {
                            "head": evt.get("head", "action"),
                            "label": evt.get("label", "?"),
                            "position_ms": pos_ms,
                        }
                    )

            if processed_events:
                self.app_state.localization_events[final_path] = processed_events

            loaded_count += 1

        self.app_state.current_json_path = file_path
        self.app_state.json_loaded = True

        self.populate_tree()
        self.main.localization_editor_controller._refresh_schema_ui()
        self.main.update_save_export_button_state()

        if missing_files:
            shown_missing = missing_files[:5]
            msg = (
                f"Loaded {loaded_count} samples.\n\n"
                f"WARNING: {len(missing_files)} samples not found locally:\n"
                + "\n".join(shown_missing)
            )
            if len(missing_files) > 5:
                msg += "\n..."
            QMessageBox.warning(self.main, "Load Warning", msg)
        else:
            self.main.statusBar().showMessage(
                f"Mode Switched — Loaded {loaded_count} samples. Current Mode: LOCALIZATION",
                1500,
            )

        return True

    def _load_description_project(self, data, file_path):
        is_valid, error_msg, warning_msg = self.app_state.validate_desc_json(data)

        if not is_valid:
            if len(error_msg) > 1000:
                error_msg = error_msg[:1000] + "\n... (truncated)"
            error_text = (
                "The imported JSON contains critical errors and cannot be loaded.\n\n"
                f"{error_msg}\n\n"
                "--------------------------------------------------\n"
                "💡 Please download the correct Description JSON format from:\n"
                "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-description-xfoul"
            )
            self._show_validation_error("Validation Error (Description)", error_text)
            return False

        if warning_msg:
            if len(warning_msg) > 1000:
                warning_msg = warning_msg[:1000] + "\n... (truncated)"
            if not self._show_validation_warning_and_confirm(
                "The file contains warnings:\n\n" + warning_msg + "\n\nContinue loading?"
            ):
                return False

        self.app_state.reset(full_reset=True)

        self.app_state.current_working_directory = os.path.dirname(os.path.abspath(file_path))
        self.app_state.current_task_name = data.get("dataset_name", data.get("task", "Description Task"))

        self.app_state.desc_global_metadata = {
            "version": data.get("version", "1.0"),
            "date": data.get("date", datetime.date.today().isoformat()),
            "metadata": data.get("metadata", {}),
        }

        loaded_count = 0
        missing_files = []

        for item in data.get("data", []):
            inputs = item.get("inputs", [])
            if not inputs:
                continue

            aid = item.get("id", "Unknown ID")

            source_files = []
            for inp in inputs:
                raw_path = inp.get("path", "")
                if not raw_path:
                    continue

                if os.path.isabs(raw_path):
                    final_path = raw_path
                else:
                    final_path = os.path.normpath(
                        os.path.join(self.app_state.current_working_directory, raw_path)
                    )

                source_files.append(final_path)

            if not source_files:
                missing_files.append(aid)
                continue

            if not any(os.path.exists(p) for p in source_files):
                missing_files.append(aid)

            meta = item.get("metadata", {})
            action_path = meta.get("path") or aid

            self.app_state.add_action_item(
                name=aid,
                path=action_path,
                source_files=source_files,
                inputs=inputs,
                captions=item.get("captions", []),
                metadata=meta,
                id=aid,
            )

            if meta:
                self.app_state.imported_action_metadata[aid] = meta

            loaded_count += 1

        self.app_state.current_json_path = file_path
        self.app_state.json_loaded = True

        self.populate_tree()
        self.main.update_save_export_button_state()

        if missing_files:
            QMessageBox.warning(
                self.main,
                "Load Warning",
                f"Could not find source files for {len(missing_files)} samples locally.",
            )
        else:
            self.main.statusBar().showMessage(
                f"Loaded {loaded_count} actions into Description Mode.",
                2000,
            )

        return True

    def _load_dense_project(self, data, file_path):
        is_valid, error_msg, warning_msg = self.app_state.validate_dense_json(data)

        if not is_valid:
            if len(error_msg) > 1000:
                error_msg = error_msg[:1000] + "\n... (truncated)"
            error_text = (
                "The imported JSON contains critical errors and cannot be loaded.\n\n"
                f"{error_msg}\n\n"
                "--------------------------------------------------\n"
                "💡 Please download the correct Dense Description JSON format from:\n"
                "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-densedescription-sndvc"
            )
            self._show_validation_error("Validation Error (Dense Description)", error_text)
            return False

        if warning_msg:
            if len(warning_msg) > 1000:
                warning_msg = warning_msg[:1000] + "\n... (truncated)"
            if not self._show_validation_warning_and_confirm(
                "The file contains warnings:\n\n"
                + warning_msg
                + "\n\nDo you want to continue loading?"
            ):
                return False

        self.app_state.reset(full_reset=True)

        project_root = os.path.dirname(os.path.abspath(file_path))
        self.app_state.current_working_directory = project_root
        self.app_state.current_task_name = data.get("dataset_name", data.get("task", "Dense Captioning"))

        self.app_state.dense_global_metadata = {
            "version": data.get("version", "1.0"),
            "date": data.get("date", datetime.date.today().isoformat()),
            "metadata": data.get("metadata", {}),
        }

        missing_files = []
        loaded_count = 0

        for item in data.get("data", []):
            inputs = item.get("inputs", [])
            if not inputs:
                continue

            raw_path = inputs[0].get("path", "")
            aid = item.get("id") or os.path.splitext(os.path.basename(raw_path))[0]

            final_path = os.path.normpath(os.path.join(project_root, raw_path))
            if not os.path.exists(final_path):
                missing_files.append(aid)

            if "metadata" in item:
                self.app_state.imported_action_metadata[aid] = item["metadata"]

            self.app_state.add_action_item(name=aid, path=final_path, source_files=[final_path])

            events = item.get("dense_captions", item.get("events", []))
            if events:
                self.app_state.dense_description_events[final_path] = []
                for evt in events:
                    self.app_state.dense_description_events[final_path].append(
                        {
                            "position_ms": int(evt.get("position_ms", 0)),
                            "lang": evt.get("lang", "en"),
                            "text": evt.get("text", ""),
                        }
                    )

            loaded_count += 1

        self.app_state.current_json_path = file_path
        self.app_state.json_loaded = True

        self.populate_tree()
        self.main.update_save_export_button_state()

        if missing_files:
            QMessageBox.warning(
                self.main,
                "Load Warning",
                f"Could not find source files for {len(missing_files)} samples locally.",
            )
        else:
            self.main.statusBar().showMessage(
                f"Dense Mode: Loaded {loaded_count} samples.",
                2000,
            )

        return True

    # ---------------------------------------------------------------------
    # Internal: Create New Project
    # ---------------------------------------------------------------------
    def _create_new_classification_project(self):
        from ui.dialogs import ClassificationTypeDialog

        dialog = ClassificationTypeDialog(self.main)
        if not dialog.exec():
            return

        self.app_state.reset(full_reset=True)

        self.app_state.current_task_name = "action_classification"
        self.app_state.modalities = ["video"]
        self.app_state.label_definitions = {}
        self.app_state.project_description = ""

        self.app_state.is_multi_view = bool(dialog.is_multi_view)

        self.app_state.json_loaded = True
        self.app_state.is_data_dirty = True
        self.app_state.current_json_path = None
        self.app_state.current_working_directory = None

        self.main.update_save_export_button_state()
        self.main.show_classification_view()
        self.main.prepare_new_project_ui()

    def _create_new_localization_project(self):
        self.app_state.reset(full_reset=True)

        self.app_state.current_task_name = "Untitled Task"
        self.app_state.project_description = ""
        self.app_state.modalities = ["video"]
        self.app_state.label_definitions = {}

        self.app_state.current_working_directory = None
        self.app_state.current_json_path = None

        self.app_state.json_loaded = True
        self.app_state.is_data_dirty = True

        self.main.localization_editor_controller.current_head = None
        self.main.localization_editor_controller.right_panel.annot_mgmt.update_schema(
            self.app_state.label_definitions
        )

        self.populate_tree()

        self.main.show_localization_view()
        self.main.update_save_export_button_state()

        if hasattr(self.main, "prepare_new_localization_ui"):
            self.main.prepare_new_localization_ui()
        self.main.statusBar().showMessage("Project Created — Localization Workspace Ready", 5000)

    def _create_new_description_project(self):
        self.app_state.reset(full_reset=True)

        self.app_state.current_task_name = "Untitled Description Task"
        self.app_state.project_description = ""
        self.app_state.modalities = ["video"]

        self.app_state.desc_global_metadata = {
            "version": "1.0",
            "date": datetime.date.today().isoformat(),
            "metadata": {
                "source": "SoccerNet Annotation Tool",
                "created_by": "User",
            },
        }

        self.app_state.json_loaded = True
        self.app_state.is_data_dirty = True
        self.app_state.current_json_path = None
        self.app_state.current_working_directory = None

        self.main.show_description_view()
        self.main.update_save_export_button_state()

        if hasattr(self.main, "prepare_new_description_ui"):
            self.main.prepare_new_description_ui()

        self.main.statusBar().showMessage("Project Created — Description Workspace Ready", 5000)

    def _create_new_dense_project(self):
        self.app_state.reset(full_reset=True)

        self.app_state.current_task_name = "Untitled Dense Task"
        self.app_state.project_description = ""
        self.app_state.modalities = ["video"]
        self.app_state.dense_description_events = {}

        self.app_state.dense_global_metadata = {
            "version": "1.0",
            "date": datetime.date.today().isoformat(),
            "metadata": {
                "source": "SoccerNet Annotation Tool",
                "created_by": "User",
                "license": "CC-BY-NC 4.0",
            },
        }

        self.app_state.current_working_directory = None
        self.app_state.current_json_path = None

        self.app_state.json_loaded = True
        self.app_state.is_data_dirty = True

        self.populate_tree()

        self.main.show_dense_description_view()
        self.main.update_save_export_button_state()

        if hasattr(self.main, "prepare_new_dense_ui"):
            self.main.prepare_new_dense_ui()

        self.main.statusBar().showMessage("Project Created — Dense Description Workspace Ready", 5000)

    # ---------------------------------------------------------------------
    # Internal: Writers
    # ---------------------------------------------------------------------
    def _write_classification_json(self, save_path):
        output = {
            "version": "2.0",
            "date": datetime.datetime.now().isoformat().split("T")[0],
            "task": self.app_state.current_task_name,
            "description": self.app_state.project_description,
            "modalities": self.app_state.modalities,
            "labels": self.app_state.label_definitions,
            "data": [],
        }

        json_dir = os.path.dirname(os.path.abspath(save_path))
        sorted_items = sorted(
            self.app_state.action_item_data,
            key=lambda x: natural_sort_key(x.get("name", "")),
        )

        for item in sorted_items:
            path_key = item["path"]
            aid = item["name"]

            inputs = []
            for src_abs_path in item.get("source_files", []):
                try:
                    fpath = os.path.relpath(src_abs_path, json_dir).replace("\\", "/")
                except ValueError:
                    fpath = src_abs_path.replace("\\", "/")

                meta = self.app_state.imported_input_metadata.get(
                    (aid, os.path.basename(src_abs_path)), {}
                )
                inputs.append({"type": "video", "path": fpath, "metadata": meta})

            data_entry = {
                "id": aid,
                "inputs": inputs,
                "metadata": self.app_state.imported_action_metadata.get(path_key, {}),
            }

            if path_key in self.app_state.manual_annotations:
                annots = self.app_state.manual_annotations[path_key]
                entry_labels = {}
                for head, value in annots.items():
                    definition = self.app_state.label_definitions.get(head)
                    if not definition:
                        continue

                    if definition["type"] == "single_label":
                        entry_labels[head] = {"label": value, "confidence": 1.0, "manual": True}
                    elif definition["type"] == "multi_label":
                        entry_labels[head] = {"labels": value, "confidence": 1.0, "manual": True}

                if entry_labels:
                    data_entry["labels"] = entry_labels

            if path_key in self.app_state.smart_annotations:
                smart_annots = self.app_state.smart_annotations[path_key]
                if smart_annots.get("_confirmed", False):
                    entry_smart_labels = {}
                    for head, data_dict in smart_annots.items():
                        if head == "_confirmed":
                            continue
                        label_value = data_dict["label"]
                        conf_dict = data_dict.get("conf_dict", {})
                        entry_smart_labels[head] = {
                            "label": label_value,
                            "confidence": conf_dict.get(label_value, 1.0),
                            "conf_dict": conf_dict,
                        }
                    if entry_smart_labels:
                        data_entry["smart_labels"] = entry_smart_labels

            output["data"].append(data_entry)

        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

            self.app_state.is_data_dirty = False
            self.main.update_save_export_button_state()
            self.main.show_temp_msg("Saved", f"Saved to {os.path.basename(save_path)}")
            return True
        except Exception as exc:
            QMessageBox.critical(self.main, "Error", f"Save failed: {exc}")
            return False

    def _write_localization_json(self, path):
        output = {
            "version": "2.0",
            "date": "2025-12-16",
            "task": "action_spotting",
            "dataset_name": self.app_state.current_task_name,
            "metadata": {
                "source": "Annotation Tool Export",
                "created_by": "User",
            },
            "labels": self.app_state.label_definitions,
            "data": [],
        }

        base_dir = os.path.dirname(path)
        sorted_items = sorted(
            self.app_state.action_item_data,
            key=lambda d: natural_sort_key(d.get("name", "")),
        )

        for data in sorted_items:
            abs_path = data["path"]
            events = self.app_state.localization_events.get(abs_path, [])

            try:
                rel_path = os.path.relpath(abs_path, base_dir).replace(os.sep, "/")
            except Exception:
                rel_path = abs_path

            export_events = []
            for event in events:
                export_events.append(
                    {
                        "head": event.get("head"),
                        "label": event.get("label"),
                        "position_ms": str(event.get("position_ms")),
                    }
                )

            entry = {
                "inputs": [
                    {
                        "type": "video",
                        "path": rel_path,
                        "fps": 25.0,
                    }
                ],
                "events": export_events,
            }
            output["data"].append(entry)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=4, ensure_ascii=False)

            self.app_state.is_data_dirty = False
            self.main.update_save_export_button_state()
            self.main.statusBar().showMessage(f"Saved — {os.path.basename(path)}", 1500)
            return True
        except Exception as exc:
            QMessageBox.critical(self.main, "Error", f"Save failed: {exc}")
            return False

    def _write_description_json(self, path):
        global_meta = getattr(self.app_state, "desc_global_metadata", {})

        output = {
            "version": global_meta.get("version", "1.0"),
            "date": global_meta.get("date", datetime.date.today().isoformat()),
            "task": "video_captioning",
            "dataset_name": self.app_state.current_task_name,
            "metadata": global_meta.get("metadata", {}),
            "data": [],
        }

        base_dir = os.path.dirname(path)
        sorted_items = sorted(
            self.app_state.action_item_data,
            key=lambda d: natural_sort_key(d.get("name", "")),
        )

        for data in sorted_items:
            export_inputs = []
            original_inputs = data.get("inputs", [])
            source_files = data.get("source_files", [])

            if len(original_inputs) == len(source_files):
                for i, inp in enumerate(original_inputs):
                    new_inp = inp.copy()
                    abs_path = source_files[i]
                    try:
                        rel_path = os.path.relpath(abs_path, base_dir).replace(os.sep, "/")
                    except Exception:
                        rel_path = abs_path
                    new_inp["path"] = rel_path
                    export_inputs.append(new_inp)
            else:
                for i, abs_path in enumerate(source_files):
                    try:
                        rel_path = os.path.relpath(abs_path, base_dir).replace(os.sep, "/")
                    except Exception:
                        rel_path = abs_path
                    export_inputs.append(
                        {
                            "type": "video",
                            "name": f"video{i + 1}",
                            "path": rel_path,
                        }
                    )

            entry = {
                "id": data.get("name") or data.get("id"),
                "metadata": data.get("metadata", {}),
                "inputs": export_inputs,
                "captions": data.get("captions", []),
            }
            output["data"].append(entry)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=4, ensure_ascii=False)

            self.app_state.is_data_dirty = False
            self.main.update_save_export_button_state()
            self.main.statusBar().showMessage(f"Saved to {os.path.basename(path)}", 2000)
            return True
        except Exception as exc:
            QMessageBox.critical(self.main, "Save Error", str(exc))
            return False

    def _write_dense_json(self, path):
        global_meta = getattr(self.app_state, "dense_global_metadata", {})

        output = {
            "version": global_meta.get("version", "1.0"),
            "date": global_meta.get("date", datetime.date.today().isoformat()),
            "task": "dense_video_captioning",
            "dataset_name": self.app_state.current_task_name,
            "metadata": global_meta.get(
                "metadata",
                {
                    "source": "SoccerNet Annotation Tool",
                    "created_by": "User",
                },
            ),
            "data": [],
        }

        base_dir = os.path.dirname(path)
        sorted_items = sorted(
            self.app_state.action_item_data,
            key=lambda d: natural_sort_key(d.get("name", "")),
        )

        for data in sorted_items:
            abs_path = data["path"]
            aid = data["name"]
            events = self.app_state.dense_description_events.get(abs_path, [])

            try:
                rel_path = os.path.relpath(abs_path, base_dir).replace(os.sep, "/")
            except Exception:
                rel_path = abs_path

            export_events = []
            sorted_events = sorted(events, key=lambda x: x.get("position_ms", 0))
            for event in sorted_events:
                export_events.append(
                    {
                        "position_ms": event["position_ms"],
                        "lang": event["lang"],
                        "text": event["text"],
                    }
                )

            entry = {
                "id": aid,
                "inputs": [{"type": "video", "path": rel_path, "fps": 25}],
                "dense_captions": export_events,
            }

            item_meta = self.app_state.imported_action_metadata.get(aid)
            if item_meta:
                entry["metadata"] = item_meta

            output["data"].append(entry)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=4, ensure_ascii=False)

            self.app_state.current_json_path = path
            self.app_state.is_data_dirty = False
            self.main.update_save_export_button_state()
            self.main.statusBar().showMessage(f"Saved — {os.path.basename(path)}", 1500)
            return True
        except Exception as exc:
            QMessageBox.critical(self.main, "Error", f"Save failed: {exc}")
            return False
