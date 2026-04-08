import copy
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QMessageBox

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
        self.right_panel = main_window.dense_panel
        self.media_controller = media_controller

        self.current_sample_id = ""
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
        self.current_sample_id = ""
        self.current_video_path = None

    def submit_current_annotation(self):
        self.right_panel.input_widget._on_submit()

    # -------------------------------------------------------------------------
    # Selection + Dense Editing
    # -------------------------------------------------------------------------
    def on_data_selected(self, data_id: str):
        if not data_id:
            self.current_sample_id = ""
            self.current_video_path = None
            self.right_panel.setEnabled(False)
            self.right_panel.table.set_data([])
            self.right_panel.input_widget.set_text("")
            if self._is_active_mode():
                self.center_panel.set_markers([])
            return

        path = self.model.get_path_by_id(data_id)
        if not path:
            return

        self.current_sample_id = data_id
        self.current_video_path = path
        self.right_panel.setEnabled(True)
        self.right_panel.input_widget.set_text("")
        self.display_events_for_item(path, update_markers=self._is_active_mode())

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

    def display_events_for_item(self, path: str, update_markers=None):
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

    def _is_active_mode(self) -> bool:
        return self.main.right_tabs.currentIndex() == 3
