import copy
import os

from PyQt6.QtCore import QModelIndex, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from controllers.media_controller import MediaController
from models import CmdType


class DenseEditorController:
    """
    Dense Description controller.
    Owns dense editor behavior, navigation, tree-selection handling, and
    Dense-mode Dataset Explorer add/remove/filter/clear delegation.
    """

    def __init__(self, main_window, media_controller: MediaController):
        self.main = main_window
        self.model = main_window.model
        self.tree_model = main_window.tree_model
        self.dataset_explorer_panel = main_window.dataset_explorer_panel
        self.center_panel = main_window.center_panel
        self.right_panel = main_window.dense_panel
        self.media_controller = media_controller

        self.current_video_path = None

        self.sync_timer = QTimer(self.main)
        self.sync_timer.setSingleShot(True)
        self.sync_timer.setInterval(100)
        self.sync_timer.timeout.connect(self._sync_editor_to_timeline)


    # -------------------------------------------------------------------------
    # Lifecycle / Wiring
    # -------------------------------------------------------------------------
    def setup_connections(self):
        self.center_panel.positionChanged.connect(self._on_media_position_changed)
        self.right_panel.eventNavigateRequested.connect(self._navigate_annotation)

        input_widget = self.right_panel.input_widget
        table = self.right_panel.table

        input_widget.descriptionSubmitted.connect(self._on_description_submitted)
        table.annotationSelected.connect(self._on_event_selected_from_table)
        table.annotationDeleted.connect(self._on_delete_single_annotation)
        table.annotationModified.connect(self._on_annotation_modified)
        table.updateTimeForSelectedRequested.connect(self._on_update_time_for_selected)

    def reset_ui(self):
        self.right_panel.table.set_data([])
        self.right_panel.input_widget.set_text("")
        self.right_panel.setEnabled(False)
        self.current_video_path = None

    def submit_current_annotation(self):
        self.right_panel.input_widget._on_submit()

    # -------------------------------------------------------------------------
    # Dataset Explorer Delegated Actions (Dense mode)
    # -------------------------------------------------------------------------
    def add_dataset_items(self):
        if not self.model.json_loaded:
            QMessageBox.warning(self.main, "Warning", "Please create or load a project first.")
            return

        start_dir = self.model.current_working_directory or ""
        files, _ = QFileDialog.getOpenFileNames(
            self.main, "Select Sample(s)", start_dir, "Video (*.mp4 *.avi *.mov *.mkv)"
        )
        if not files:
            return

        if not self.model.current_working_directory:
            self.model.current_working_directory = os.path.dirname(files[0])

        added_count = 0
        first_idx = None

        for file_path in files:
            if self.model.has_action_path(file_path):
                continue

            name = os.path.basename(file_path)
            self.model.add_action_item(name=name, path=file_path, source_files=[file_path])
            item = self.tree_model.add_entry(name=name, path=file_path, source_files=[file_path])
            self.model.action_item_map[file_path] = item
            self.main.dataset_explorer_controller.update_item_status(file_path)

            if first_idx is None:
                first_idx = item.index()
            added_count += 1

        if added_count > 0:
            self._mark_dirty_and_refresh()
            self.filter_dataset_items(self.dataset_explorer_panel.filter_combo.currentIndex())
            self.main.show_temp_msg("Samples Added", f"Added {added_count} samples.")
            if first_idx and first_idx.isValid():
                self.dataset_explorer_panel.tree.setCurrentIndex(first_idx)
                self.dataset_explorer_panel.tree.setFocus()

    def clear_dataset_items(self):
        if not self.model.action_item_data:
            return

        res = QMessageBox.question(
            self.main,
            "Clear All",
            "Are you sure you want to clear the workspace? Unsaved changes will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        self.clear_workspace()
        self.main.show_welcome_view()
        self.main.show_temp_msg("Cleared", "Workspace reset.")

    def remove_dataset_item(self, index: QModelIndex):
        path, action_idx = self._path_from_index(index)
        if not path:
            return

        reply = QMessageBox.question(
            self.main,
            "Remove Sample",
            f"Are you sure you want to remove this sample and its annotations?\n\n{os.path.basename(path)}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.on_item_removed(path)

        removed = self.model.remove_action_item_by_path(path)
        if not removed:
            return

        self._remove_tree_row(action_idx)
        self._mark_dirty_and_refresh()
        self.main.show_temp_msg("Removed", "Sample removed from project.")

    def filter_dataset_items(self, index: int):
        root = self.tree_model.invisibleRootItem()
        for row in range(root.rowCount()):
            item = root.child(row)
            path = item.data(getattr(self.tree_model, "FilePathRole", 0x0100))
            has_anno = len(self.model.dense_description_events.get(path, [])) > 0

            hide = False
            if index == 1 and not has_anno:
                hide = True
            elif index == 2 and has_anno:
                hide = True

            self.dataset_explorer_panel.tree.setRowHidden(row, QModelIndex(), hide)

    def clear_workspace(self):
        """
        Dense non-dialog reset path.
        Callers own confirmation/show-welcome behavior.
        """
        self.media_controller.stop()
        self.model.reset(full_reset=True)
        self.model.dense_global_metadata = {}
        self.current_video_path = None

        self.tree_model.clear()
        self.right_panel.table.set_data([])
        self.right_panel.input_widget.set_text("")
        self.right_panel.setEnabled(False)

        self.center_panel.player.setSource(QUrl())
        self.center_panel.video_widget.update()
        self.center_panel.set_markers([])

        self.main.update_save_export_button_state()

    def on_item_removed(self, path: str):
        if path != self.current_video_path:
            return

        self.media_controller.stop()
        self.current_video_path = None
        self.right_panel.table.set_data([])
        self.center_panel.set_markers([])
        self.right_panel.input_widget.set_text("")
        self.right_panel.setEnabled(False)
        self.center_panel.player.setSource(QUrl())
        self.center_panel.video_widget.update()

    # -------------------------------------------------------------------------
    # Selection + Dense Editing
    # -------------------------------------------------------------------------
    def on_item_selected(self, current_idx: QModelIndex, previous_idx: QModelIndex):
        if not current_idx.isValid():
            self.current_video_path = None
            self.right_panel.setEnabled(False)
            self.right_panel.table.set_data([])
            self.right_panel.input_widget.set_text("")
            self.center_panel.set_markers([])
            return

        path, _ = self._path_from_index(current_idx)
        if path == self.current_video_path:
            return

        if not path or not os.path.exists(path):
            if path:
                QMessageBox.warning(self.main, "Error", f"File not found: {path}")
            return

        self.current_video_path = path
        self.right_panel.setEnabled(True)
        self.right_panel.input_widget.set_text("")
        self.media_controller.load_and_play(path)
        self.display_events_for_item(path)

    def _on_media_position_changed(self, ms: int):
        self.right_panel.input_widget.update_time(self._fmt_ms_full(ms))
        if not self.sync_timer.isActive():
            self.sync_timer.start()

    def _on_event_selected_from_table(self, ms: int):
        self.center_panel.set_position(ms)
        self._sync_editor_to_timeline()

    def _on_description_submitted(self, text: str):
        if not self.current_video_path:
            QMessageBox.warning(self.main, "Warning", "Please select a sample first.")
            return

        pos_ms = self.center_panel.player.position()
        events = self.model.dense_description_events.get(self.current_video_path, [])

        tolerance = 50
        existing_event = None
        existing_index = -1
        for idx, event in enumerate(events):
            if abs(event["position_ms"] - pos_ms) <= tolerance:
                existing_event = event
                existing_index = idx
                break

        if existing_event:
            if existing_event["text"] == text:
                return

            new_event = copy.deepcopy(existing_event)
            new_event["text"] = text

            self.model.push_undo(
                CmdType.DENSE_EVENT_MOD,
                video_path=self.current_video_path,
                old_event=copy.deepcopy(existing_event),
                new_event=new_event,
            )
            events[existing_index] = new_event
            self.main.show_temp_msg("Updated", "Description updated.")
        else:
            new_event = {"position_ms": pos_ms, "lang": "en", "text": text}

            self.model.push_undo(
                CmdType.DENSE_EVENT_ADD,
                video_path=self.current_video_path,
                event=new_event,
            )

            if self.current_video_path not in self.model.dense_description_events:
                self.model.dense_description_events[self.current_video_path] = []

            self.model.dense_description_events[self.current_video_path].append(new_event)
            self.main.show_temp_msg("Added", "Dense description created.")
            self.right_panel.input_widget.set_text("")

        self.model.is_data_dirty = True
        self.display_events_for_item(self.current_video_path)
        self.main.update_action_item_status(self.current_video_path)
        self.main.update_save_export_button_state()

    def _on_annotation_modified(self, old_event: dict, new_event: dict):
        if not self.current_video_path:
            return

        events = self.model.dense_description_events.get(self.current_video_path, [])
        try:
            idx = events.index(old_event)
        except ValueError:
            return

        self.model.push_undo(
            CmdType.DENSE_EVENT_MOD,
            video_path=self.current_video_path,
            old_event=copy.deepcopy(old_event),
            new_event=copy.deepcopy(new_event),
        )

        events[idx] = new_event
        self.model.is_data_dirty = True
        self.main.update_action_item_status(self.current_video_path)

        # Defer to avoid QAbstractItemView model mutation while editing.
        QTimer.singleShot(0, lambda: self.display_events_for_item(self.current_video_path))

        self.main.show_temp_msg("Updated", "Description modified.")
        self.main.update_save_export_button_state()

    def _on_delete_single_annotation(self, item_data: dict):
        if not self.current_video_path:
            return

        events = self.model.dense_description_events.get(self.current_video_path, [])
        if item_data not in events:
            return

        self.model.push_undo(
            CmdType.DENSE_EVENT_DEL,
            video_path=self.current_video_path,
            event=copy.deepcopy(item_data),
        )

        events.remove(item_data)
        self.model.is_data_dirty = True
        self.display_events_for_item(self.current_video_path)
        self.main.update_action_item_status(self.current_video_path)
        self.main.update_save_export_button_state()
        self.right_panel.input_widget.set_text("")

    def _on_update_time_for_selected(self, old_event: dict):
        if not self.current_video_path:
            return

        current_ms = self.center_panel.player.position()
        new_event = old_event.copy()
        new_event["position_ms"] = current_ms
        self._on_annotation_modified(old_event, new_event)

    def display_events_for_item(self, path: str):
        current_selection_ms = None
        selection_model = self.right_panel.table.table.selectionModel()
        if selection_model:
            indexes = selection_model.selectedRows()
            if indexes:
                row = indexes[0].row()
                item = self.right_panel.table.model.get_annotation_at(row)
                if item:
                    current_selection_ms = item.get("position_ms")

        events = self.model.dense_description_events.get(path, [])
        sorted_events = sorted(events, key=lambda x: x.get("position_ms", 0))

        self.right_panel.table.set_data(sorted_events)
        markers = [
            {"start_ms": event.get("position_ms", 0), "color": QColor("#FFD700")}
            for event in sorted_events
        ]
        self.center_panel.set_markers(markers)

        if current_selection_ms is not None:
            self._select_row_by_time(current_selection_ms)

        if path == self.current_video_path:
            self._sync_editor_to_timeline()

    def _sync_editor_to_timeline(self):
        if not self.current_video_path:
            return

        current_ms = self.center_panel.player.position()
        events = self.model.dense_description_events.get(self.current_video_path, [])

        tolerance = 50
        found = False
        target_text = ""
        for event in events:
            if abs(event["position_ms"] - current_ms) <= tolerance:
                target_text = event["text"]
                found = True
                break

        # Keep user-typed text if no matching timestamp event is found.
        if found:
            current_text = self.right_panel.input_widget.text_editor.toPlainText()
            if current_text != target_text:
                self.right_panel.input_widget.set_text(target_text)

    # -------------------------------------------------------------------------
    # Navigation
    # -------------------------------------------------------------------------
    def _navigate_annotation(self, step: int):
        events = self.model.dense_description_events.get(self.current_video_path, [])
        if not events:
            return

        sorted_events = sorted(events, key=lambda x: x.get("position_ms", 0))
        current_pos = self.center_panel.player.position()

        target = None
        if step > 0:
            for event in sorted_events:
                if event["position_ms"] > current_pos + 100:
                    target = event
                    break
        else:
            for event in reversed(sorted_events):
                if event["position_ms"] < current_pos - 100:
                    target = event
                    break

        if target is not None:
            self.center_panel.set_position(target["position_ms"])
            self._select_row_by_time(target["position_ms"])
            self.right_panel.input_widget.set_text(target["text"])

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    def _select_row_by_time(self, time_ms: int):
        model = self.right_panel.table.model
        for row in range(model.rowCount()):
            item = model.get_annotation_at(row)
            if item and abs(item.get("position_ms", 0) - time_ms) < 20:
                self.right_panel.table.table.selectRow(row)
                break

    def _fmt_ms_full(self, ms: int) -> str:
        seconds = ms // 1000
        minutes = seconds // 60
        hours = minutes // 60
        return f"{hours:02}:{minutes % 60:02}:{seconds % 60:02}.{ms % 1000:03}"

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
