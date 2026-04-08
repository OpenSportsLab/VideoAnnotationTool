import copy
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from controllers.command_types import CmdType
from controllers.media_controller import MediaController

from .loc_inference import LocalizationInferenceManager


class LocalizationEditorController:
    """
    Localization controller.
    Owns localization editor logic, data-ID driven selection handling, navigation,
    and smart inference actions.
    Dataset add/remove/filter/clear is handled centrally by DatasetExplorerController.
    """

    def __init__(self, main_window, media_controller: MediaController):
        self.main = main_window
        self.model = main_window.model
        self.tree_model = main_window.tree_model

        self.center_panel = main_window.center_panel
        self.localization_panel = main_window.localization_panel

        self.inference_manager = LocalizationInferenceManager(self.main)
        self.inference_manager.inference_finished.connect(self._on_inference_success)
        self.inference_manager.inference_error.connect(self._on_inference_error)
        self.media_controller = media_controller

        self.current_video_path = None
        self.current_head = None

    # -------------------------------------------------------------------------
    # Lifecycle / Wiring
    # -------------------------------------------------------------------------
    def reset_ui(self):
        self.localization_panel.annot_mgmt.update_schema({})
        self.localization_panel.table.set_data([])
        if hasattr(self.localization_panel, "smart_widget"):
            self.localization_panel.smart_widget.smart_table.set_data([])
        self.localization_panel.setEnabled(False)
        self.current_video_path = None
        self.current_head = None

    def setup_connections(self):
        self.localization_panel.eventNavigateRequested.connect(self._navigate_annotation)

        if hasattr(self.localization_panel, "smart_widget"):
            smart_ui = self.localization_panel.smart_widget
            smart_ui.setTimeRequested.connect(self._on_smart_set_time)
            smart_ui.runInferenceRequested.connect(self._run_localization_inference)
            smart_ui.confirmSmartRequested.connect(self._confirm_smart_events)
            smart_ui.clearSmartRequested.connect(self._clear_smart_events)
            self.localization_panel.tabs.currentChanged.connect(self._on_tab_switched)

        self.center_panel.positionChanged.connect(self._on_media_position_changed)

        tabs = self.localization_panel.annot_mgmt.tabs
        table = self.localization_panel.table

        tabs.headAdded.connect(self._on_head_added)
        tabs.headRenamed.connect(self._on_head_renamed)
        tabs.headDeleted.connect(self._on_head_deleted)
        tabs.headSelected.connect(self._on_head_selected)

        tabs.spottingTriggered.connect(self._on_spotting_triggered)
        tabs.labelAddReq.connect(self._on_label_add_req)
        tabs.labelRenameReq.connect(self._on_label_rename_req)
        tabs.labelDeleteReq.connect(self._on_label_delete_req)

        table.annotationSelected.connect(lambda ms: self.center_panel.set_position(ms))
        table.annotationDeleted.connect(self._on_delete_single_annotation)
        table.annotationModified.connect(self._on_annotation_modified)
        table.updateTimeForSelectedRequested.connect(self._on_update_time_for_selected)

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # Selection / Playback / Annotation logic
    # -------------------------------------------------------------------------
    def _on_media_position_changed(self, ms):
        time_str = self._fmt_ms_full(ms)
        self.localization_panel.annot_mgmt.tabs.update_current_time(time_str)

    def _on_update_time_for_selected(self, old_event):
        if not self.current_video_path:
            return
        current_ms = self.center_panel.player.position()
        new_event = old_event.copy()
        new_event["position_ms"] = current_ms
        self._on_annotation_modified(old_event, new_event)

    def on_data_selected(self, data_id: str):
        if not data_id:
            self.current_video_path = None
            self.localization_panel.table.set_data([])
            if hasattr(self.localization_panel, "smart_widget"):
                self.localization_panel.smart_widget.smart_table.set_data([])
            if self._is_active_mode():
                self.center_panel.set_markers([])
            self.localization_panel.setEnabled(False)
            return

        path = self.model.get_path_by_id(data_id)
        if not path:
            self.current_video_path = None
            self.localization_panel.setEnabled(False)
            return

        if path and os.path.exists(path):
            self.current_video_path = path
            self.localization_panel.setEnabled(True)
            if self._is_showing_smart_tab():
                self._display_smart_events(path, update_markers=self._is_active_mode())
            else:
                self._display_events_for_item(path, update_markers=self._is_active_mode())
        elif path:
            QMessageBox.warning(self.main, "Error", f"File not found: {path}")

    # --- Head Management ---
    def handle_add_head(self):
        text, ok = QInputDialog.getText(
            self.main,
            "New Category",
            "Enter name for new Category (Head):",
        )
        if ok and text.strip():
            self._on_head_added(text.strip())

    def _on_head_selected(self, head_name):
        self.current_head = head_name

    def _on_head_added(self, head_name):
        if any(h.lower() == head_name.lower() for h in self.model.label_definitions):
            self.main.show_temp_msg(
                "Error",
                f"Head '{head_name}' already exists!",
                icon=QMessageBox.Icon.Warning,
            )
            return
        definition = {"type": "single_label", "labels": []}
        self.model.push_undo(CmdType.SCHEMA_ADD_CAT, head=head_name, definition=definition)
        self.model.label_definitions[head_name] = definition
        self.model.is_data_dirty = True
        self._refresh_schema_ui()
        self.localization_panel.annot_mgmt.tabs.set_current_head(head_name)
        self.main.show_temp_msg("Head Added", f"Created '{head_name}'")
        self.main.update_save_export_button_state()

    def _on_head_renamed(self, old_name, new_name):
        if old_name == new_name:
            return
        if any(h.lower() == new_name.lower() for h in self.model.label_definitions):
            self.main.show_temp_msg("Error", "Name already exists!", icon=QMessageBox.Icon.Warning)
            return
        self.model.push_undo(CmdType.SCHEMA_REN_CAT, old_name=old_name, new_name=new_name)
        self.model.label_definitions[new_name] = self.model.label_definitions.pop(old_name)
        for _, events in self.model.localization_events.items():
            for evt in events:
                if evt.get("head") == old_name:
                    evt["head"] = new_name
        self.model.is_data_dirty = True
        self._refresh_schema_ui()
        self.localization_panel.annot_mgmt.tabs.set_current_head(new_name)
        self._refresh_current_clip_events()
        self.main.show_temp_msg("Head Renamed", "Updated events.")
        self.main.update_save_export_button_state()

    def _on_head_deleted(self, head_name):
        res = QMessageBox.warning(
            self.main,
            "Delete Head",
            f"Delete head '{head_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        loc_affected = {}
        for vid_path, events in self.model.localization_events.items():
            affected_evts = [copy.deepcopy(e) for e in events if e.get("head") == head_name]
            if affected_evts:
                loc_affected[vid_path] = affected_evts

        definition = copy.deepcopy(self.model.label_definitions.get(head_name))
        self.model.push_undo(
            CmdType.SCHEMA_DEL_CAT,
            head=head_name,
            definition=definition,
            loc_affected_events=loc_affected,
        )

        if head_name in self.model.label_definitions:
            del self.model.label_definitions[head_name]

        for vid_path in self.model.localization_events:
            self.model.localization_events[vid_path] = [
                e for e in self.model.localization_events[vid_path] if e.get("head") != head_name
            ]

        self.model.is_data_dirty = True
        self._refresh_schema_ui()
        self._refresh_current_clip_events()
        self.main.show_temp_msg("Head Deleted", "Removed.")
        self.main.update_save_export_button_state()

    # --- Label Management ---
    def _on_label_add_req(self, head):
        player = self.center_panel.player
        was_playing = player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if was_playing:
            player.pause()
        current_pos = player.position()

        text, ok = QInputDialog.getText(self.main, "Add Label", f"Add label to '{head}':")
        if not ok or not text.strip():
            if was_playing:
                player.play()
            return

        label_name = text.strip()
        labels_list = self.model.label_definitions[head].get("labels", [])
        if any(l.lower() == label_name.lower() for l in labels_list):
            self.main.show_temp_msg("Error", "Label exists!", icon=QMessageBox.Icon.Warning)
            if was_playing:
                player.play()
            return

        before_json = self.model.snapshot_dataset_json()
        labels_list.append(label_name)

        if self.current_video_path:
            new_event = {"head": head, "label": label_name, "position_ms": current_pos}
            if self.current_video_path not in self.model.localization_events:
                self.model.localization_events[self.current_video_path] = []
            self.model.localization_events[self.current_video_path].append(new_event)

        self.model.push_dataset_json_replace_undo_if_changed(before_json)

        self._refresh_schema_ui()
        self.localization_panel.annot_mgmt.tabs.set_current_head(head)
        if self.current_video_path:
            self._display_events_for_item(self.current_video_path)
            self.refresh_tree_icons()
        self.main.show_temp_msg("Added", f"{head}: {label_name}")
        self.main.update_save_export_button_state()

        if was_playing:
            player.play()

    def _on_label_rename_req(self, head, old_label):
        new_label, ok = QInputDialog.getText(
            self.main,
            "Rename Label",
            f"Rename '{old_label}' to:",
            text=old_label,
        )
        if not ok or not new_label.strip() or new_label == old_label:
            return

        new_label = new_label.strip()
        labels_list = self.model.label_definitions[head].get("labels", [])
        if any(l.lower() == new_label.lower() for l in labels_list if l != old_label):
            self.main.show_temp_msg("Error", "Label exists!", icon=QMessageBox.Icon.Warning)
            return

        self.model.push_undo(CmdType.SCHEMA_REN_LBL, head=head, old_lbl=old_label, new_lbl=new_label)
        index = labels_list.index(old_label)
        labels_list[index] = new_label

        for _, events in self.model.localization_events.items():
            for evt in events:
                if evt.get("head") == head and evt.get("label") == old_label:
                    evt["label"] = new_label

        self.model.is_data_dirty = True
        self._refresh_schema_ui()
        self.localization_panel.annot_mgmt.tabs.set_current_head(head)
        self._refresh_current_clip_events()
        self.main.update_save_export_button_state()

    def _on_label_delete_req(self, head, label):
        res = QMessageBox.warning(
            self.main,
            "Delete Label",
            f"Delete '{label}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        loc_affected = {}
        for vid_path, events in self.model.localization_events.items():
            aff = [copy.deepcopy(e) for e in events if e.get("head") == head and e.get("label") == label]
            if aff:
                loc_affected[vid_path] = aff

        labels_list = self.model.label_definitions[head].get("labels", [])
        label_index = labels_list.index(label) if label in labels_list else -1
        self.model.push_undo(
            CmdType.SCHEMA_DEL_LBL,
            head=head,
            label=label,
            label_index=label_index,
            loc_affected_events=loc_affected,
        )
        if label in labels_list:
            labels_list.remove(label)

        for vid_path in self.model.localization_events:
            events = self.model.localization_events[vid_path]
            self.model.localization_events[vid_path] = [
                e for e in events if not (e.get("head") == head and e.get("label") == label)
            ]

        self.model.is_data_dirty = True
        self._refresh_schema_ui()
        self.localization_panel.annot_mgmt.tabs.set_current_head(head)
        self._refresh_current_clip_events()
        self.main.update_save_export_button_state()

    # --- Spotting (Data Creation) ---
    def _on_spotting_triggered(self, head, label):
        if not self.current_video_path:
            QMessageBox.warning(self.main, "Warning", "No sample selected.")
            return

        pos_ms = self.center_panel.player.position()
        new_event = {"head": head, "label": label, "position_ms": pos_ms}
        self.model.push_undo(CmdType.LOC_EVENT_ADD, video_path=self.current_video_path, event=new_event)

        if self.current_video_path not in self.model.localization_events:
            self.model.localization_events[self.current_video_path] = []
        self.model.localization_events[self.current_video_path].append(new_event)

        self.model.is_data_dirty = True
        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons()
        self.main.show_temp_msg("Event Created", f"{head}: {label}")
        self.main.update_save_export_button_state()
        self._reselect_event(new_event)

    # --- Table Modification ---
    def _on_annotation_modified(self, old_event, new_event):
        if old_event == new_event:
            return

        events = self.model.localization_events.get(self.current_video_path, [])
        index = self._find_event_index(events, old_event)
        if index < 0:
            return

        self.model.push_undo(
            CmdType.LOC_EVENT_MOD,
            video_path=self.current_video_path,
            old_event=copy.deepcopy(old_event),
            new_event=new_event,
        )

        new_head = new_event["head"]
        new_label = new_event["label"]
        schema_changed = False

        if new_head not in self.model.label_definitions:
            self.model.label_definitions[new_head] = {"type": "single_label", "labels": []}
            schema_changed = True

        if new_label and new_label != "???":
            labels_list = self.model.label_definitions[new_head]["labels"]
            if not any(l.lower() == new_label.lower() for l in labels_list):
                labels_list.append(new_label)
                schema_changed = True

        events[index] = new_event
        self.model.is_data_dirty = True

        if schema_changed:
            self._refresh_schema_ui()
            self.localization_panel.annot_mgmt.tabs.set_current_head(new_head)

        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons()
        self.main.show_temp_msg("Event Updated", "Modified")
        self.main.update_save_export_button_state()
        self._reselect_event(new_event)

    def _on_delete_single_annotation(self, item_data):
        events = self.model.localization_events.get(self.current_video_path, [])
        index = self._find_event_index(events, item_data)
        if index < 0:
            return

        reply = QMessageBox.question(
            self.main,
            "Delete Event",
            "Delete this event?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.model.push_undo(
            CmdType.LOC_EVENT_DEL,
            video_path=self.current_video_path,
            event=copy.deepcopy(events[index]),
            event_index=index,
        )
        events.pop(index)
        self.model.is_data_dirty = True
        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons()
        self.main.update_save_export_button_state()

    # --- Helper Refresh Methods ---
    def _refresh_schema_ui(self):
        self.localization_panel.table.set_schema(self.model.label_definitions)
        self.localization_panel.annot_mgmt.update_schema(self.model.label_definitions)

    def _refresh_current_clip_events(self):
        if self.current_video_path:
            self._display_events_for_item(self.current_video_path)

    def refresh_tree_icons(self):
        for path, item in self.model.action_item_map.items():
            events = self.model.localization_events.get(path, [])
            item.setIcon(self.main.done_icon if events else self.main.empty_icon)

    def _display_events_for_item(self, path, update_markers=None):
        events = self.model.localization_events.get(path, [])
        # Keep original event dict references so table-originated edits/deletes map back
        # to the same objects stored in the model.
        display_data = sorted(events, key=lambda x: x.get("position_ms", 0))
        self.localization_panel.table.set_data(display_data)
        if update_markers is None:
            update_markers = self._is_active_mode() and not self._is_showing_smart_tab()
        if update_markers:
            markers = [{"start_ms": e.get("position_ms", 0), "color": QColor("#00BFFF")} for e in events]
            self.center_panel.set_markers(markers)

    def _find_event_index(self, events, event):
        """
        Locate an event by exact dict equality first, then by event identity fields.
        This keeps edit/delete robust if table rows carry shallow copies.
        """
        try:
            return events.index(event)
        except ValueError:
            pass

        target_head = event.get("head")
        target_label = event.get("label")
        target_pos = event.get("position_ms")
        for idx, candidate in enumerate(events):
            if (
                candidate.get("head") == target_head
                and candidate.get("label") == target_label
                and candidate.get("position_ms") == target_pos
            ):
                return idx
        return -1

    def _navigate_annotation(self, step):
        if not self.current_video_path:
            return

        hand_events = self.model.localization_events.get(self.current_video_path, [])
        smart_events = self.model.smart_localization_events.get(self.current_video_path, [])
        events = [*hand_events, *smart_events]
        if not events:
            return

        sorted_events = sorted(events, key=lambda x: x.get("position_ms", 0))
        current_pos = self.center_panel.player.position()
        target_time = None
        if step > 0:
            for event in sorted_events:
                if event.get("position_ms", 0) > current_pos + 100:
                    target_time = event.get("position_ms")
                    break
        else:
            for event in reversed(sorted_events):
                if event.get("position_ms", 0) < current_pos - 100:
                    target_time = event.get("position_ms")
                    break
        if target_time is not None:
            self.center_panel.set_position(target_time)
            # Keep current tab unchanged. If the event is not in the active table,
            # we still seek video but do not force tab-switching.
            active_tab = self.localization_panel.tabs.currentIndex()
            if active_tab == 1:
                self._select_row_by_time_in_table(self.localization_panel.smart_widget.smart_table, target_time)
            else:
                self._select_row_by_time_in_table(self.localization_panel.table, target_time)

    def _select_row_by_time(self, time_ms):
        self._select_row_by_time_in_table(self.localization_panel.table, time_ms)

    def _select_row_by_time_in_table(self, table_adapter, time_ms):
        model = table_adapter.model
        for row in range(model.rowCount()):
            item = model.get_annotation_at(row)
            if item and abs(item.get("position_ms", 0) - time_ms) < 10:
                idx = model.index(row, 0)
                table_adapter.table.selectRow(row)
                table_adapter.table.scrollTo(idx)
                break

    def _reselect_event(self, target_event):
        model = self.localization_panel.table.model
        table_view = self.localization_panel.table.table

        table_view.selectionModel().blockSignals(True)

        for row in range(model.rowCount()):
            item = model.get_annotation_at(row)
            if not item:
                continue

            if (
                item.get("position_ms") == target_event.get("position_ms")
                and item.get("head") == target_event.get("head")
                and item.get("label") == target_event.get("label")
            ):
                idx = model.index(row, 0)
                table_view.selectRow(row)
                table_view.scrollTo(idx)
                if hasattr(self.localization_panel.table, "btn_set_time"):
                    self.localization_panel.table.btn_set_time.setEnabled(True)
                break

        table_view.selectionModel().blockSignals(False)

    def _fmt_ms_full(self, ms):
        seconds = ms // 1000
        minutes = seconds // 60
        hours = minutes // 60
        return f"{hours:02}:{minutes % 60:02}:{seconds % 60:02}.{ms % 1000:03}"

    # -------------------------------------------------------------------------
    # Smart Annotation Control
    # -------------------------------------------------------------------------
    def _on_smart_set_time(self, target: str):
        player = self.center_panel.player
        current_ms = player.position()
        time_str = self._fmt_ms_full(current_ms)
        self.localization_panel.smart_widget.update_time_display(target, time_str, current_ms)

    def _run_localization_inference(self, start_ms: int, end_ms: int):
        if not self.current_video_path:
            return
        if start_ms >= end_ms and end_ms != 0:
            QMessageBox.warning(self.main, "Invalid Range", "End time must be greater than Start time.")
            return

        self.main.show_temp_msg("Smart Inference", "Running OpenSportsLib Localization Model...")
        self.localization_panel.smart_widget.btn_run_infer.setEnabled(False)
        self.inference_manager.start_inference(self.current_video_path, start_ms, end_ms)

    def _on_inference_success(self, predicted_events: list):
        self.localization_panel.smart_widget.btn_run_infer.setEnabled(True)
        if not self.current_video_path:
            return

        before_json = self.model.snapshot_dataset_json()
        self.model.smart_localization_events[self.current_video_path] = predicted_events
        self.model.push_dataset_json_replace_undo_if_changed(before_json)
        self.main.show_temp_msg("Smart Inference", f"Success: Found {len(predicted_events)} events.")
        self.main.update_save_export_button_state()

        if self.localization_panel.tabs.currentIndex() == 1:
            self._display_smart_events(self.current_video_path)

    def _on_inference_error(self, error_msg: str):
        self.localization_panel.smart_widget.btn_run_infer.setEnabled(True)
        QMessageBox.critical(self.main, "Inference Error", f"Failed to run model:\n{error_msg}")

    def _confirm_smart_events(self):
        if not self.current_video_path:
            return

        smart_events = self.model.smart_localization_events.get(self.current_video_path, [])
        if not smart_events:
            return

        before_json = self.model.snapshot_dataset_json()
        if self.current_video_path not in self.model.localization_events:
            self.model.localization_events[self.current_video_path] = []

        self.model.localization_events[self.current_video_path].extend(smart_events)
        self.model.localization_events[self.current_video_path].sort(key=lambda x: x.get("position_ms", 0))

        self.model.smart_localization_events[self.current_video_path] = []
        self._display_smart_events(self.current_video_path)

        self.main.show_temp_msg(
            "Smart Spotting",
            "Predictions confirmed and merged into Hand Annotations.",
        )
        self.model.push_dataset_json_replace_undo_if_changed(before_json)
        self.main.update_save_export_button_state()

    def _clear_smart_events(self):
        if not self.current_video_path:
            return
        if not self.model.smart_localization_events.get(self.current_video_path):
            return

        before_json = self.model.snapshot_dataset_json()
        self.model.smart_localization_events[self.current_video_path] = []
        self.model.push_dataset_json_replace_undo_if_changed(before_json)
        self._display_smart_events(self.current_video_path)
        self.main.show_temp_msg("Smart Spotting", "Cleared smart predictions.")
        self.main.update_save_export_button_state()

    def _display_smart_events(self, video_path: str, update_markers=None):
        events = self.model.smart_localization_events.get(video_path, [])
        self.localization_panel.smart_widget.smart_table.set_data(events)
        if update_markers is None:
            update_markers = self._is_active_mode() and self._is_showing_smart_tab()
        if update_markers:
            markers = [
                {"start_ms": evt.get("position_ms", 0), "color": QColor("deepskyblue")}
                for evt in events
            ]
            self.center_panel.set_markers(markers)

    def _on_tab_switched(self, index: int):
        if not self.current_video_path:
            return

        if index == 0:
            self._display_events_for_item(self.current_video_path, update_markers=self._is_active_mode())
        elif index == 1:
            self._display_smart_events(self.current_video_path, update_markers=self._is_active_mode())

    def _is_active_mode(self) -> bool:
        return self.main.right_tabs.currentIndex() == 1

    def _is_showing_smart_tab(self) -> bool:
        return hasattr(self.localization_panel, "tabs") and self.localization_panel.tabs.currentIndex() == 1
