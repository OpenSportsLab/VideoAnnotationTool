import copy

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from controllers.command_types import CmdType
from controllers.media_controller import MediaController


class DenseEditorController:
    """
    Dense Description controller.
    Owns dense editor behavior, navigation, and data-ID driven selection handling.
    Dataset add/remove/filter/clear is handled centrally by DatasetExplorerController.
    """

    def __init__(self, main_window, media_controller: MediaController):
        self.main = main_window
        self.model = main_window.model
        self.tree_model = main_window.tree_model
        self.center_panel = main_window.center_panel
        self.dense_panel = main_window.dense_panel
        self.media_controller = media_controller

        self.current_sample_id = ""
        self.current_video_path = None

    # -------------------------------------------------------------------------
    # Lifecycle / Wiring
    # -------------------------------------------------------------------------
    def setup_connections(self):
        self.dense_panel.eventNavigateRequested.connect(self._navigate_annotation)

        input_widget = self.dense_panel.input_widget
        table = self.dense_panel.table

        # Primary dense flow: explicit Add action + table-only editing.
        input_widget.addEventRequested.connect(self._on_add_event_requested)
        table.annotationSelected.connect(self._on_event_selected_from_table)
        table.annotationDeleted.connect(self._on_delete_single_annotation)
        table.annotationModified.connect(self._on_annotation_modified)
        table.updateTimeForSelectedRequested.connect(self._on_update_time_for_selected)

    def reset_ui(self):
        self.dense_panel.table.set_data([])
        self.dense_panel.setEnabled(False)
        self.current_sample_id = ""
        self.current_video_path = None

    def submit_current_annotation(self):
        self._on_add_event_requested()

    # -------------------------------------------------------------------------
    # Selection + Dense Editing
    # -------------------------------------------------------------------------
    def on_data_selected(self, data_id: str):
        if not data_id:
            self.current_sample_id = ""
            self.current_video_path = None
            self.dense_panel.setEnabled(False)
            self.dense_panel.table.set_data([])
            if self._is_active_mode():
                self.center_panel.set_markers([])
            return

        path = self.model.get_path_by_id(data_id)
        if not path:
            return

        self.current_sample_id = data_id
        self.current_video_path = path
        self.dense_panel.setEnabled(True)
        self.display_events_for_item(path, update_markers=self._is_active_mode())

    def _on_event_selected_from_table(self, ms: int):
        self.center_panel.set_position(ms)

    def _on_add_event_requested(self, initial_text: str = ""):
        if not self.current_video_path:
            QMessageBox.warning(self.main, "Warning", "Please select a sample first.")
            return

        player = self.center_panel.player
        was_playing = player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if was_playing:
            player.pause()

        try:
            provided_text = (initial_text or "").strip()
            if provided_text:
                text = provided_text
                accepted = True
            else:
                text, accepted = QInputDialog.getMultiLineText(
                    self.main,
                    "Add New Description",
                    "Description:",
                    "",
                )
                text = (text or "").strip()

            if not accepted or not text:
                return

            pos_ms = int(self.center_panel.player.position())
            new_event = {"position_ms": pos_ms, "lang": "en", "text": text}

            self.model.push_undo(
                CmdType.DENSE_EVENT_ADD,
                video_path=self.current_video_path,
                event=copy.deepcopy(new_event),
            )

            if self.current_video_path not in self.model.dense_description_events:
                self.model.dense_description_events[self.current_video_path] = []

            self.model.dense_description_events[self.current_video_path].append(new_event)
            self.model.is_data_dirty = True
            self.display_events_for_item(self.current_video_path)
            self._select_row_for_event(new_event)
            self.main.update_action_item_status(self.current_video_path)
            self.main.update_save_export_button_state()
            self.main.show_temp_msg("Added", "Dense description added.")
        finally:
            if was_playing:
                player.play()

    def _on_annotation_modified(self, old_event: dict, new_event: dict):
        if not self.current_video_path:
            return
        if old_event == new_event:
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

        # Defer to avoid mutating model while the table delegate is still committing edits.
        QTimer.singleShot(
            0,
            lambda: self._refresh_after_event_modification(self.current_video_path, new_event),
        )

        self.main.show_temp_msg("Updated", "Description modified.")
        self.main.update_save_export_button_state()

    def _refresh_after_event_modification(self, path: str, target_event: dict):
        self.display_events_for_item(path)
        self._select_row_for_event(target_event)

    def _on_delete_single_annotation(self, item_data: dict):
        if not self.current_video_path:
            return

        events = self.model.dense_description_events.get(self.current_video_path, [])
        try:
            event_index = events.index(item_data)
        except ValueError:
            return

        self.model.push_undo(
            CmdType.DENSE_EVENT_DEL,
            video_path=self.current_video_path,
            event=copy.deepcopy(item_data),
            event_index=event_index,
        )

        events.pop(event_index)
        self.model.is_data_dirty = True
        self.display_events_for_item(self.current_video_path)
        self.main.update_action_item_status(self.current_video_path)
        self.main.update_save_export_button_state()

    def _on_update_time_for_selected(self, old_event: dict):
        if not self.current_video_path:
            return

        current_ms = self.center_panel.player.position()
        new_event = old_event.copy()
        new_event["position_ms"] = current_ms
        self._on_annotation_modified(old_event, new_event)

    def display_events_for_item(self, path: str, update_markers=None):
        current_selection_ms = None
        selection_model = self.dense_panel.table.table.selectionModel()
        if selection_model:
            indexes = selection_model.selectedRows()
            if indexes:
                row = indexes[0].row()
                item = self.dense_panel.table.model.get_annotation_at(row)
                if item:
                    current_selection_ms = item.get("position_ms")

        events = self.model.dense_description_events.get(path, [])
        sorted_events = sorted(events, key=lambda x: x.get("position_ms", 0))

        self.dense_panel.table.set_data(sorted_events)
        if update_markers is None:
            update_markers = self._is_active_mode()
        if update_markers:
            markers = [
                {"start_ms": event.get("position_ms", 0), "color": QColor("#FFD700")}
                for event in sorted_events
            ]
            self.center_panel.set_markers(markers)

        if current_selection_ms is not None:
            self._select_row_by_time(current_selection_ms)

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

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    def _select_row_by_time(self, time_ms: int):
        model = self.dense_panel.table.model
        for row in range(model.rowCount()):
            item = model.get_annotation_at(row)
            if item and abs(item.get("position_ms", 0) - time_ms) < 20:
                self.dense_panel.table.table.selectRow(row)
                break

    def _select_row_for_event(self, target_event: dict):
        if not isinstance(target_event, dict):
            return
        model = self.dense_panel.table.model
        for row in range(model.rowCount()):
            item = model.get_annotation_at(row)
            if item is target_event or item == target_event:
                self.dense_panel.table.table.selectRow(row)
                return

    def _selected_event_in_table(self):
        selection_model = self.dense_panel.table.table.selectionModel()
        if not selection_model:
            return None
        selected_rows = selection_model.selectedRows()
        if not selected_rows:
            return None
        return self.dense_panel.table.model.get_annotation_at(selected_rows[0].row())

    def _is_active_mode(self) -> bool:
        return self.main.right_tabs.currentIndex() == 3
