import copy

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from .loc_inference import LocalizationInferenceManager


class LocalizationEditorController(QObject):
    """
    Localization controller.
    Owns localization editor logic, sample-driven selection handling, navigation,
    and smart inference actions.
    Dataset loading and explorer state updates are handled centrally by DatasetExplorerController.
    """

    statusMessageRequested = pyqtSignal(str, str, int)
    saveStateRefreshRequested = pyqtSignal()
    itemStatusRefreshRequested = pyqtSignal(str)
    locHeadAddRequested = pyqtSignal(str)
    locHeadRenameRequested = pyqtSignal(str, str)
    locHeadDeleteRequested = pyqtSignal(str)
    # payload: sample_id, head, label_name, event_position_ms, create_event
    locLabelAddRequested = pyqtSignal(str, str, str, int, bool)
    locLabelRenameRequested = pyqtSignal(str, str, str)
    locLabelDeleteRequested = pyqtSignal(str, str)
    # payload: sample_id, ...
    locEventAddRequested = pyqtSignal(str, dict)
    locEventModRequested = pyqtSignal(str, dict, dict)
    locEventDelRequested = pyqtSignal(str, dict, int)

    # Smart localization persistence intents.
    locSmartEventsSetRequested = pyqtSignal(str, object)
    locSmartEventsConfirmRequested = pyqtSignal(str)
    locSmartEventsClearRequested = pyqtSignal(str)

    # Media intents emitted to MainWindow wiring.
    mediaSeekRequested = pyqtSignal(int)
    markersUpdateRequested = pyqtSignal(object)
    mediaTogglePlaybackRequested = pyqtSignal()

    def __init__(self, localization_panel):
        super().__init__()
        self.localization_panel = localization_panel

        self.inference_manager = LocalizationInferenceManager(self.localization_panel)
        self.inference_manager.inference_finished.connect(self._on_inference_success)
        self.inference_manager.inference_error.connect(self._on_inference_error)

        self._schema_definitions = {}
        self._action_paths_cache = []

        self._is_media_playing = False
        self._last_media_position_ms = 0
        self._active_mode_index = 0

        self.current_video_path = None
        self.current_sample_id = ""
        self.current_head = None
        self._current_sample_snapshot = {}

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
        self.current_sample_id = ""
        self.current_head = None
        self._current_sample_snapshot = {}

    def setup_connections(self):
        self.localization_panel.eventNavigateRequested.connect(self._navigate_annotation)

        if hasattr(self.localization_panel, "smart_widget"):
            smart_ui = self.localization_panel.smart_widget
            smart_ui.setTimeRequested.connect(self._on_smart_set_time)
            smart_ui.runInferenceRequested.connect(self._run_localization_inference)
            smart_ui.confirmSmartRequested.connect(self._confirm_smart_events)
            smart_ui.clearSmartRequested.connect(self._clear_smart_events)
            self.localization_panel.tabs.currentChanged.connect(self._on_tab_switched)

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

        table.annotationSelected.connect(self._on_table_annotation_selected)
        table.annotationDeleted.connect(self._on_delete_single_annotation)
        table.annotationModified.connect(self._on_annotation_modified)
        table.updateTimeForSelectedRequested.connect(self._on_update_time_for_selected)

    def on_mode_changed(self, index: int):
        self._active_mode_index = index
        if self._is_active_mode() and self.current_video_path:
            if self._is_showing_smart_tab():
                self._display_smart_events(self.current_video_path, update_markers=True)
            else:
                self._display_events_for_item(self.current_video_path, update_markers=True)

    def on_playback_state_changed(self, is_playing: bool):
        self._is_media_playing = bool(is_playing)

    def on_media_position_changed(self, ms: int):
        self._last_media_position_ms = max(0, int(ms))
        time_str = self._fmt_ms_full(self._last_media_position_ms)
        self.localization_panel.annot_mgmt.tabs.update_current_time(time_str)

    def on_schema_context_changed(self, schema: dict):
        self._schema_definitions = self._normalize_schema(schema)
        self._refresh_schema_ui()

    def on_action_items_changed(self, action_items: list):
        paths = []
        for item in list(action_items or []):
            path = item.get("path") if isinstance(item, dict) else None
            if path:
                paths.append(path)
        self._action_paths_cache = paths

    def on_selected_sample_changed(self, sample, resolved_path: str = ""):
        self._set_selected_sample_snapshot(sample, resolved_path=resolved_path)
        if not self.current_video_path:
            if self._is_active_mode():
                self.markersUpdateRequested.emit([])
            return

        if self._is_showing_smart_tab():
            self._display_smart_events(self.current_video_path, update_markers=self._is_active_mode())
        else:
            self._display_events_for_item(self.current_video_path, update_markers=self._is_active_mode())

    # -------------------------------------------------------------------------
    # Selection / Playback / Annotation logic
    # -------------------------------------------------------------------------
    def _on_table_annotation_selected(self, ms: int):
        self._last_media_position_ms = max(0, int(ms))
        self.mediaSeekRequested.emit(int(ms))

    def _on_update_time_for_selected(self, old_event):
        if not self.current_video_path:
            return
        current_ms = max(0, int(self._last_media_position_ms))
        new_event = old_event.copy()
        new_event["position_ms"] = current_ms
        self._on_annotation_modified(old_event, new_event)

    # --- Head Management ---
    def handle_add_head(self):
        text, ok = QInputDialog.getText(
            self.localization_panel,
            "New Category",
            "Enter name for new Category (Head):",
        )
        if ok and text.strip():
            self._on_head_added(text.strip())

    def _on_head_selected(self, head_name):
        self.current_head = head_name

    def _on_head_added(self, head_name):
        if any(h.lower() == head_name.lower() for h in self._schema_definitions):
            self.statusMessageRequested.emit(
                "Error",
                f"Head '{head_name}' already exists!",
                1500,
            )
            return
        self.locHeadAddRequested.emit(head_name)
        self._schema_definitions[head_name] = {"type": "single_label", "labels": []}
        self._refresh_schema_ui()
        self.localization_panel.annot_mgmt.tabs.set_current_head(head_name)

    def _on_head_renamed(self, old_name, new_name):
        if old_name == new_name:
            return
        if old_name not in self._schema_definitions:
            return
        if any(h.lower() == new_name.lower() for h in self._schema_definitions if h != old_name):
            self.statusMessageRequested.emit("Error", "Name already exists!", 1500)
            return

        # Keep a fallback copy because signal handlers can synchronously refresh
        # schema context and mutate `_schema_definitions` before local updates run.
        old_definition = copy.deepcopy(self._schema_definitions.get(old_name, {"type": "single_label", "labels": []}))
        self.locHeadRenameRequested.emit(old_name, new_name)

        if old_name in self._schema_definitions:
            self._schema_definitions[new_name] = self._schema_definitions.pop(old_name)
        elif new_name not in self._schema_definitions:
            self._schema_definitions[new_name] = old_definition

        hand_events = self._snapshot_hand_events()
        for evt in hand_events:
            if evt.get("head") == old_name:
                evt["head"] = new_name
        self._set_snapshot_hand_events(hand_events)

        smart_events = self._snapshot_smart_events()
        for evt in smart_events:
            if evt.get("head") == old_name:
                evt["head"] = new_name
        self._set_snapshot_smart_events(smart_events)

        self._refresh_schema_ui()
        self.localization_panel.annot_mgmt.tabs.set_current_head(new_name)
        self._refresh_current_clip_events()

    def _on_head_deleted(self, head_name):
        res = QMessageBox.warning(
            self.localization_panel,
            "Delete Head",
            f"Delete head '{head_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        self.locHeadDeleteRequested.emit(head_name)

        self._schema_definitions.pop(head_name, None)
        hand_events = [e for e in self._snapshot_hand_events() if e.get("head") != head_name]
        self._set_snapshot_hand_events(hand_events)
        smart_events = [e for e in self._snapshot_smart_events() if e.get("head") != head_name]
        self._set_snapshot_smart_events(smart_events)

        self._refresh_schema_ui()
        self._refresh_current_clip_events()

    # --- Label Management ---
    def _on_label_add_req(self, head):
        definition = self._schema_definitions.get(head, {})
        if not definition:
            return

        was_playing = bool(self._is_media_playing)
        if was_playing:
            self.mediaTogglePlaybackRequested.emit()
        current_pos = max(0, int(self._last_media_position_ms))

        text, ok = QInputDialog.getText(self.localization_panel, "Add Label", f"Add label to '{head}':")
        if not ok or not text.strip():
            if was_playing:
                self.mediaTogglePlaybackRequested.emit()
            return

        label_name = text.strip()
        labels_list = definition.get("labels", [])
        if any(l.lower() == label_name.lower() for l in labels_list):
            self.statusMessageRequested.emit("Error", "Label exists!", 1500)
            if was_playing:
                self.mediaTogglePlaybackRequested.emit()
            return

        if not self.current_sample_id:
            if was_playing:
                self.mediaTogglePlaybackRequested.emit()
            return

        self.locLabelAddRequested.emit(
            self.current_sample_id,
            head,
            label_name,
            int(current_pos),
            bool(self.current_video_path),
        )

        updated_labels = list(labels_list)
        updated_labels.append(label_name)
        updated_labels.sort()
        self._schema_definitions[head]["labels"] = updated_labels

        if self.current_video_path:
            events = self._snapshot_hand_events()
            events.append({"head": head, "label": label_name, "position_ms": int(current_pos)})
            self._set_snapshot_hand_events(events)
            self._display_events_for_item(self.current_video_path)
            self.refresh_tree_icons()

        self._refresh_schema_ui()
        self.localization_panel.annot_mgmt.tabs.set_current_head(head)

        if was_playing:
            self.mediaTogglePlaybackRequested.emit()

    def _on_label_rename_req(self, head, old_label):
        if head not in self._schema_definitions:
            return

        new_label, ok = QInputDialog.getText(
            self.localization_panel,
            "Rename Label",
            f"Rename '{old_label}' to:",
            text=old_label,
        )
        if not ok or not new_label.strip() or new_label == old_label:
            return

        new_label = new_label.strip()
        labels_list = self._schema_definitions[head].get("labels", [])
        if any(l.lower() == new_label.lower() for l in labels_list if l != old_label):
            self.statusMessageRequested.emit("Error", "Label exists!", 1500)
            return

        self.locLabelRenameRequested.emit(head, old_label, new_label)

        updated_labels = [new_label if lbl == old_label else lbl for lbl in labels_list]
        self._schema_definitions[head]["labels"] = sorted(updated_labels)

        hand_events = self._snapshot_hand_events()
        for evt in hand_events:
            if evt.get("head") == head and evt.get("label") == old_label:
                evt["label"] = new_label
        self._set_snapshot_hand_events(hand_events)

        smart_events = self._snapshot_smart_events()
        for evt in smart_events:
            if evt.get("head") == head and evt.get("label") == old_label:
                evt["label"] = new_label
        self._set_snapshot_smart_events(smart_events)

        self._refresh_schema_ui()
        self.localization_panel.annot_mgmt.tabs.set_current_head(head)
        self._refresh_current_clip_events()

    def _on_label_delete_req(self, head, label):
        res = QMessageBox.warning(
            self.localization_panel,
            "Delete Label",
            f"Delete '{label}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        self.locLabelDeleteRequested.emit(head, label)

        labels = list(self._schema_definitions.get(head, {}).get("labels", []))
        self._schema_definitions.setdefault(head, {"type": "single_label", "labels": []})
        self._schema_definitions[head]["labels"] = [lbl for lbl in labels if lbl != label]

        hand_events = [
            evt
            for evt in self._snapshot_hand_events()
            if not (evt.get("head") == head and evt.get("label") == label)
        ]
        self._set_snapshot_hand_events(hand_events)

        smart_events = [
            evt
            for evt in self._snapshot_smart_events()
            if not (evt.get("head") == head and evt.get("label") == label)
        ]
        self._set_snapshot_smart_events(smart_events)

        self._refresh_schema_ui()
        self.localization_panel.annot_mgmt.tabs.set_current_head(head)
        self._refresh_current_clip_events()

    # --- Spotting (Data Creation) ---
    def _on_spotting_triggered(self, head, label):
        if not self.current_video_path or not self.current_sample_id:
            QMessageBox.warning(self.localization_panel, "Warning", "No sample selected.")
            return

        pos_ms = max(0, int(self._last_media_position_ms))
        new_event = {"head": head, "label": label, "position_ms": pos_ms}
        self.locEventAddRequested.emit(self.current_sample_id, copy.deepcopy(new_event))

        events = self._snapshot_hand_events()
        events.append(copy.deepcopy(new_event))
        self._set_snapshot_hand_events(events)

        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons()
        self._reselect_event(new_event)

    # --- Table Modification ---
    def _on_annotation_modified(self, old_event, new_event):
        if not self.current_video_path:
            return
        if old_event == new_event:
            return

        events = self._snapshot_hand_events()
        index = self._find_event_index(events, old_event)
        if index < 0:
            return
        if not self.current_sample_id:
            return

        self.locEventModRequested.emit(
            self.current_sample_id,
            copy.deepcopy(old_event),
            copy.deepcopy(new_event),
        )

        events[index] = copy.deepcopy(new_event)
        self._set_snapshot_hand_events(events)

        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons()
        self._reselect_event(new_event)

    def _on_delete_single_annotation(self, item_data):
        if not self.current_video_path:
            return

        events = self._snapshot_hand_events()
        index = self._find_event_index(events, item_data)
        if index < 0:
            return

        reply = QMessageBox.question(
            self.localization_panel,
            "Delete Event",
            "Delete this event?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self.current_sample_id:
            return

        self.locEventDelRequested.emit(
            self.current_sample_id,
            copy.deepcopy(events[index]),
            index,
        )

        events.pop(index)
        self._set_snapshot_hand_events(events)
        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons()

    # --- Helper Refresh Methods ---
    def _refresh_schema_ui(self):
        self.localization_panel.table.set_schema(self._schema_definitions)
        self.localization_panel.annot_mgmt.update_schema(self._schema_definitions)

    def _refresh_current_clip_events(self):
        if not self.current_video_path:
            return
        if self._is_showing_smart_tab():
            self._display_smart_events(self.current_video_path)
        else:
            self._display_events_for_item(self.current_video_path)

    def refresh_tree_icons(self):
        for path in self._action_paths_cache:
            self.itemStatusRefreshRequested.emit(path)

    def _display_events_for_item(self, path, update_markers=None):
        if path and path != self.current_video_path:
            return

        events = self._snapshot_hand_events()
        display_data = sorted(events, key=lambda x: self._event_position_ms(x))
        self.localization_panel.table.set_data(display_data)

        if update_markers is None:
            update_markers = self._is_active_mode() and not self._is_showing_smart_tab()
        if update_markers:
            markers = [{"start_ms": e.get("position_ms", 0), "color": QColor("#00BFFF")} for e in display_data]
            self.markersUpdateRequested.emit(markers)

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

        hand_events = self._snapshot_hand_events()
        smart_events = self._snapshot_smart_events()
        events = [*hand_events, *smart_events]
        if not events:
            return

        sorted_events = sorted(events, key=lambda x: self._event_position_ms(x))
        current_pos = max(0, int(self._last_media_position_ms))
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
            self._last_media_position_ms = max(0, int(target_time))
            self.mediaSeekRequested.emit(int(target_time))
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
        current_ms = max(0, int(self._last_media_position_ms))
        time_str = self._fmt_ms_full(current_ms)
        self.localization_panel.smart_widget.update_time_display(target, time_str, current_ms)

    def _run_localization_inference(self, start_ms: int, end_ms: int):
        if not self.current_video_path:
            return
        if start_ms >= end_ms and end_ms != 0:
            QMessageBox.warning(self.localization_panel, "Invalid Range", "End time must be greater than Start time.")
            return

        self.statusMessageRequested.emit("Smart Inference", "Running OpenSportsLib Localization Model...", 1500)
        self.localization_panel.smart_widget.btn_run_infer.setEnabled(False)
        self.inference_manager.start_inference(self.current_video_path, start_ms, end_ms)

    def _on_inference_success(self, predicted_events: list):
        self.localization_panel.smart_widget.btn_run_infer.setEnabled(True)
        if not self.current_video_path or not self.current_sample_id:
            return

        normalized = [copy.deepcopy(evt) for evt in list(predicted_events or []) if isinstance(evt, dict)]
        normalized.sort(key=self._event_position_ms)

        self.locSmartEventsSetRequested.emit(self.current_sample_id, copy.deepcopy(normalized))
        self._set_snapshot_smart_events(normalized)

        self.statusMessageRequested.emit("Smart Inference", f"Success: Found {len(normalized)} events.", 1500)
        self.saveStateRefreshRequested.emit()

        if self.localization_panel.tabs.currentIndex() == 1:
            self._display_smart_events(self.current_video_path)

    def _on_inference_error(self, error_msg: str):
        self.localization_panel.smart_widget.btn_run_infer.setEnabled(True)
        QMessageBox.critical(self.localization_panel, "Inference Error", f"Failed to run model:\n{error_msg}")

    def _confirm_smart_events(self):
        if not self.current_video_path or not self.current_sample_id:
            return

        smart_events = self._snapshot_smart_events()
        self.locSmartEventsConfirmRequested.emit(self.current_sample_id)

        if smart_events:
            hand_events = self._snapshot_hand_events()
            hand_events.extend(copy.deepcopy(smart_events))
            self._set_snapshot_hand_events(hand_events)
        self._set_snapshot_smart_events([])

        if self._is_showing_smart_tab():
            self._display_smart_events(self.current_video_path)
        else:
            self._display_events_for_item(self.current_video_path)

        self.statusMessageRequested.emit(
            "Smart Spotting",
            "Predictions confirmed and merged into Hand Annotations.",
            1500,
        )
        self.saveStateRefreshRequested.emit()
        self.refresh_tree_icons()

    def _clear_smart_events(self):
        if not self.current_video_path or not self.current_sample_id:
            return

        self.locSmartEventsClearRequested.emit(self.current_sample_id)
        self._set_snapshot_smart_events([])
        self._display_smart_events(self.current_video_path)
        self.statusMessageRequested.emit("Smart Spotting", "Cleared smart predictions.", 1500)
        self.saveStateRefreshRequested.emit()

    def _display_smart_events(self, video_path: str, update_markers=None):
        if video_path and video_path != self.current_video_path:
            return

        events = self._snapshot_smart_events()
        self.localization_panel.smart_widget.smart_table.set_data(events)

        if update_markers is None:
            update_markers = self._is_active_mode() and self._is_showing_smart_tab()
        if update_markers:
            markers = [
                {"start_ms": evt.get("position_ms", 0), "color": QColor("deepskyblue")}
                for evt in events
            ]
            self.markersUpdateRequested.emit(markers)

    def _on_tab_switched(self, index: int):
        if not self.current_video_path:
            return

        if index == 0:
            self._display_events_for_item(self.current_video_path, update_markers=self._is_active_mode())
        elif index == 1:
            self._display_smart_events(self.current_video_path, update_markers=self._is_active_mode())

    # -------------------------------------------------------------------------
    # Snapshot helpers
    # -------------------------------------------------------------------------
    def _set_selected_sample_snapshot(self, sample, resolved_path: str = ""):
        if not isinstance(sample, dict):
            self._clear_selected_sample_state()
            return

        sample_id = str(sample.get("id") or "")
        path = str(resolved_path or self._extract_primary_path(sample) or "")
        if not sample_id or not path:
            self._clear_selected_sample_state()
            return

        self.current_sample_id = sample_id
        self.current_video_path = path
        self._current_sample_snapshot = copy.deepcopy(sample)
        self.localization_panel.setEnabled(True)

    def _clear_selected_sample_state(self):
        self.current_video_path = None
        self.current_sample_id = ""
        self.current_head = None
        self._current_sample_snapshot = {}
        self.localization_panel.table.set_data([])
        if hasattr(self.localization_panel, "smart_widget"):
            self.localization_panel.smart_widget.smart_table.set_data([])
        self.localization_panel.setEnabled(False)

    def _snapshot_hand_events(self):
        events = self._current_sample_snapshot.get("events", [])
        if not isinstance(events, list):
            return []
        return copy.deepcopy(events)

    def _set_snapshot_hand_events(self, events):
        if not isinstance(self._current_sample_snapshot, dict):
            self._current_sample_snapshot = {}
        normalized = [copy.deepcopy(evt) for evt in list(events or []) if isinstance(evt, dict)]
        normalized.sort(key=self._event_position_ms)
        self._current_sample_snapshot["events"] = normalized

    def _snapshot_smart_events(self):
        events = self._current_sample_snapshot.get("smart_events", [])
        if not isinstance(events, list):
            return []
        return copy.deepcopy(events)

    def _set_snapshot_smart_events(self, events):
        if not isinstance(self._current_sample_snapshot, dict):
            self._current_sample_snapshot = {}
        normalized = [copy.deepcopy(evt) for evt in list(events or []) if isinstance(evt, dict)]
        normalized.sort(key=self._event_position_ms)
        self._current_sample_snapshot["smart_events"] = normalized

    @staticmethod
    def _normalize_schema(schema: dict) -> dict:
        if not isinstance(schema, dict):
            return {}
        return copy.deepcopy(schema)

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
    def _event_position_ms(event) -> int:
        if not isinstance(event, dict):
            return 0
        try:
            return int(event.get("position_ms", 0) or 0)
        except Exception:
            return 0

    def _is_active_mode(self) -> bool:
        return self._active_mode_index == 1

    def _is_showing_smart_tab(self) -> bool:
        return hasattr(self.localization_panel, "tabs") and self.localization_panel.tabs.currentIndex() == 1
