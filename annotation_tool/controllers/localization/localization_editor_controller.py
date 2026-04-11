import copy

from PyQt6.QtCore import QObject, QSettings, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from .loc_inference import LocalizationInferenceManager


class LocalizationEditorController(QObject):
    """
    Localization controller.
    Owns localization editor logic, sample-driven selection handling, navigation,
    and smart inference actions.
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
    # payload: sample_id, full events list
    locEventsSetRequested = pyqtSignal(str, object)

    # Media intents emitted to MainWindow wiring.
    mediaSeekRequested = pyqtSignal(int)
    markersUpdateRequested = pyqtSignal(object)
    mediaTogglePlaybackRequested = pyqtSignal()

    SETTINGS_ORG = "OpenSportsLab"
    SETTINGS_APP = "VideoAnnotationTool"
    SETTINGS_MODEL_KEY = "localization/last_inference_model"
    DEFAULT_MODEL = "jeetv/snpro-snbas-2024"

    def __init__(self, localization_panel):
        super().__init__()
        self.localization_panel = localization_panel

        self.inference_manager = LocalizationInferenceManager(self.localization_panel)
        self.inference_manager.inference_finished.connect(self._on_inference_success)
        self.inference_manager.inference_error.connect(self._on_inference_error)

        self._schema_definitions = {}
        self._action_paths_cache = []
        self._action_path_by_sample_id = {}

        self._is_media_playing = False
        self._last_media_position_ms = 0
        self._media_duration_ms = 0
        self._active_mode_index = 0
        self._pending_inference_head = None

        self.current_video_path = None
        self.current_sample_id = ""
        self.current_head = None
        self._current_sample_snapshot = {}

        self.settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

    # -------------------------------------------------------------------------
    # Lifecycle / Wiring
    # -------------------------------------------------------------------------
    def reset_ui(self):
        self.localization_panel.annot_mgmt.update_schema({})
        self.localization_panel.table.set_data([])
        self.localization_panel.setEnabled(False)
        self.current_video_path = None
        self.current_sample_id = ""
        self.current_head = None
        self._current_sample_snapshot = {}
        self._pending_inference_head = None

    def setup_connections(self):
        self.localization_panel.eventNavigateRequested.connect(self._navigate_annotation)

        tabs = self.localization_panel.annot_mgmt.tabs
        table = self.localization_panel.table

        tabs.headAdded.connect(self._on_head_added)
        tabs.headRenamed.connect(self._on_head_renamed)
        tabs.headDeleted.connect(self._on_head_deleted)
        tabs.headSelected.connect(self._on_head_selected)
        tabs.smartInferenceRequested.connect(self._on_head_smart_inference_requested)

        tabs.spottingTriggered.connect(self._on_spotting_triggered)
        tabs.labelAddReq.connect(self._on_label_add_req)
        tabs.labelRenameReq.connect(self._on_label_rename_req)
        tabs.labelDeleteReq.connect(self._on_label_delete_req)

        table.annotationSelected.connect(self._on_table_annotation_selected)
        table.annotationDeleted.connect(self._on_delete_single_annotation)
        table.annotationModified.connect(self._on_annotation_modified)
        table.annotationConfirmRequested.connect(self._on_confirm_single_annotation)
        table.annotationRejectRequested.connect(self._on_reject_single_annotation)
        table.updateTimeForSelectedRequested.connect(self._on_update_time_for_selected)

    def shutdown_background_tasks(self, wait_ms: int = 2500) -> bool:
        return self.inference_manager.shutdown_threads(wait_ms=wait_ms)

    def on_mode_changed(self, index: int):
        self._active_mode_index = index
        if self._is_active_mode() and self.current_video_path:
            self._display_events_for_item(self.current_video_path, update_markers=True)

    def on_playback_state_changed(self, is_playing: bool):
        self._is_media_playing = bool(is_playing)

    def on_media_position_changed(self, ms: int):
        self._last_media_position_ms = max(0, int(ms))
        time_str = self._fmt_ms_full(self._last_media_position_ms)
        self.localization_panel.annot_mgmt.tabs.update_current_time(time_str)

    def on_media_duration_changed(self, ms: int):
        self._media_duration_ms = max(0, int(ms))

    def on_schema_context_changed(self, schema: dict):
        self._schema_definitions = self._normalize_schema(schema)
        self._refresh_schema_ui()

    def on_action_items_changed(self, action_items: list):
        paths = []
        by_sample = {}
        for item in list(action_items or []):
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            sample_id = str(item.get("data_id") or item.get("id") or "")
            if path:
                paths.append(path)
            if sample_id and path:
                by_sample[sample_id] = str(path)
        self._action_paths_cache = paths
        self._action_path_by_sample_id = by_sample

    def on_selected_sample_changed(self, sample):
        self._set_selected_sample_snapshot(sample)
        if not self.current_video_path:
            if self._is_active_mode():
                self.markersUpdateRequested.emit([])
            return

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

        old_definition = copy.deepcopy(self._schema_definitions.get(old_name, {"type": "single_label", "labels": []}))
        self.locHeadRenameRequested.emit(old_name, new_name)

        if old_name in self._schema_definitions:
            self._schema_definitions[new_name] = self._schema_definitions.pop(old_name)
        elif new_name not in self._schema_definitions:
            self._schema_definitions[new_name] = old_definition

        events = self._snapshot_events()
        for evt in events:
            if evt.get("head") == old_name:
                evt["head"] = new_name
        self._set_snapshot_events(events)

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
        events = [e for e in self._snapshot_events() if e.get("head") != head_name]
        self._set_snapshot_events(events)

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
            events = self._snapshot_events()
            events.append({"head": head, "label": label_name, "position_ms": int(current_pos)})
            self._set_snapshot_events(events)
            self._display_events_for_item(self.current_video_path)
            self.refresh_tree_icons(self.current_video_path)

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

        events = self._snapshot_events()
        for evt in events:
            if evt.get("head") == head and evt.get("label") == old_label:
                evt["label"] = new_label
        self._set_snapshot_events(events)

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

        events = [
            evt
            for evt in self._snapshot_events()
            if not (evt.get("head") == head and evt.get("label") == label)
        ]
        self._set_snapshot_events(events)

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

        events = self._snapshot_events()
        events.append(copy.deepcopy(new_event))
        self._set_snapshot_events(events)

        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons(self.current_video_path)
        self._reselect_event(new_event)

    # --- Table Modification ---
    def _normalize_event_for_manual_edit(self, event: dict) -> dict:
        updated = copy.deepcopy(event)
        if isinstance(updated, dict):
            updated.pop("confidence_score", None)
        return updated

    def _on_annotation_modified(self, old_event, new_event):
        if not self.current_video_path:
            return

        normalized_new = self._normalize_event_for_manual_edit(new_event)
        if old_event == normalized_new:
            return

        events = self._snapshot_events()
        index = self._find_event_index(events, old_event)
        if index < 0:
            return
        if not self.current_sample_id:
            return

        self.locEventModRequested.emit(
            self.current_sample_id,
            copy.deepcopy(old_event),
            copy.deepcopy(normalized_new),
        )

        events[index] = copy.deepcopy(normalized_new)
        self._set_snapshot_events(events)

        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons(self.current_video_path)
        self._reselect_event(normalized_new)

    def _on_confirm_single_annotation(self, item_data):
        if not isinstance(item_data, dict) or "confidence_score" not in item_data:
            return
        if not self.current_video_path or not self.current_sample_id:
            return

        events = self._snapshot_events()
        index = self._find_event_index(events, item_data)
        if index < 0:
            return

        updated_event = copy.deepcopy(events[index])
        updated_event.pop("confidence_score", None)
        if updated_event == events[index]:
            return

        self.locEventModRequested.emit(
            self.current_sample_id,
            copy.deepcopy(events[index]),
            copy.deepcopy(updated_event),
        )

        events[index] = updated_event
        self._set_snapshot_events(events)

        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons(self.current_video_path)
        self._reselect_event(updated_event)

    def _on_reject_single_annotation(self, item_data):
        if not isinstance(item_data, dict) or "confidence_score" not in item_data:
            return
        if not self.current_video_path or not self.current_sample_id:
            return

        events = self._snapshot_events()
        index = self._find_event_index(events, item_data)
        if index < 0:
            return

        self.locEventDelRequested.emit(
            self.current_sample_id,
            copy.deepcopy(events[index]),
            index,
        )

        events.pop(index)
        self._set_snapshot_events(events)
        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons(self.current_video_path)

    def _on_delete_single_annotation(self, item_data):
        if not self.current_video_path:
            return

        events = self._snapshot_events()
        index = self._find_event_index(events, item_data)
        if index < 0:
            return

        # reply = QMessageBox.question(
        #     self.localization_panel,
        #     "Delete Event",
        #     "Delete this event?",
        #     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        # )
        # if reply != QMessageBox.StandardButton.Yes:
        #     return
        if not self.current_sample_id:
            return

        self.locEventDelRequested.emit(
            self.current_sample_id,
            copy.deepcopy(events[index]),
            index,
        )

        events.pop(index)
        self._set_snapshot_events(events)
        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons(self.current_video_path)

    # --- Smart inference integration ---
    def _prompt_model_id(self):
        current = str(self.settings.value(self.SETTINGS_MODEL_KEY, self.DEFAULT_MODEL) or self.DEFAULT_MODEL)
        model_id, ok = QInputDialog.getText(
            self.localization_panel,
            "Localization Inference Model",
            "Model id:",
            text=current,
        )
        if not ok:
            return None
        clean = str(model_id or "").strip()
        if not clean:
            QMessageBox.warning(self.localization_panel, "Inference", "Model id cannot be empty.")
            return None
        self.settings.setValue(self.SETTINGS_MODEL_KEY, clean)
        self.settings.sync()
        return clean

    def _prompt_inference_range(self):
        start_default = self._fmt_ms_short(0)
        end_default_ms = self._media_duration_ms if self._media_duration_ms > 0 else 0
        end_default = self._fmt_ms_short(end_default_ms)

        start_text, ok = QInputDialog.getText(
            self.localization_panel,
            "Inference Start",
            "Start time (mm:ss.mmm):",
            text=start_default,
        )
        if not ok:
            return None, None

        end_text, ok = QInputDialog.getText(
            self.localization_panel,
            "Inference End",
            "End time (mm:ss.mmm):",
            text=end_default,
        )
        if not ok:
            return None, None

        start_ms = self._parse_mmss_to_ms(start_text, 0)
        end_ms = self._parse_mmss_to_ms(end_text, end_default_ms)
        if end_ms != 0 and end_ms <= start_ms:
            QMessageBox.warning(self.localization_panel, "Invalid Range", "End time must be greater than Start time.")
            return None, None
        return start_ms, end_ms

    def _on_head_smart_inference_requested(self, head_name: str):
        if not self.current_video_path or not self.current_sample_id:
            return

        model_id = self._prompt_model_id()
        if not model_id:
            return

        start_ms, end_ms = self._prompt_inference_range()
        if start_ms is None:
            return

        self._pending_inference_head = str(head_name or "")
        self.statusMessageRequested.emit("Inference", "Running localization inference...", 1200)
        self.inference_manager.start_inference(self.current_video_path, start_ms, end_ms, model_id)

    def _resolve_unknown_prediction_label(self, head: str, predicted_label: str):
        definition = self._schema_definitions.get(head, {}) if isinstance(self._schema_definitions, dict) else {}
        labels = list(definition.get("labels", [])) if isinstance(definition, dict) else []

        clean_pred = str(predicted_label or "").strip()
        if not labels or clean_pred in labels:
            return clean_pred

        options = [*labels, "<Skip Prediction>"]
        mapped, ok = QInputDialog.getItem(
            self.localization_panel,
            "Map Predicted Label",
            f"Map '{clean_pred}' to:",
            options,
            0,
            False,
        )
        if not ok or mapped == "<Skip Prediction>":
            return None
        return str(mapped)

    @staticmethod
    def _prediction_confidence(event: dict) -> float:
        if not isinstance(event, dict):
            return 1.0
        if "confidence_score" in event:
            try:
                return max(0.0, min(1.0, float(event.get("confidence_score") or 0.0)))
            except Exception:
                return 1.0
        if "confidence" in event:
            try:
                return max(0.0, min(1.0, float(event.get("confidence") or 0.0)))
            except Exception:
                return 1.0
        return 1.0

    def _on_inference_success(self, predicted_events: list):
        if not self.current_video_path or not self.current_sample_id:
            self._pending_inference_head = None
            return

        target_head = str(self._pending_inference_head or self.current_head or "")
        if not target_head:
            self._pending_inference_head = None
            return

        current_events = self._snapshot_events()
        existing_keys = {
            (
                str(evt.get("head") or ""),
                str(evt.get("label") or ""),
                int(self._event_position_ms(evt)),
            )
            for evt in current_events
            if isinstance(evt, dict)
        }

        appended_count = 0
        for raw in list(predicted_events or []):
            if not isinstance(raw, dict):
                continue

            mapped_label = self._resolve_unknown_prediction_label(target_head, raw.get("label"))
            if not mapped_label:
                continue

            position_ms = self._event_position_ms(raw)
            event = {
                "head": target_head,
                "label": mapped_label,
                "position_ms": int(position_ms),
                "confidence_score": self._prediction_confidence(raw),
            }
            event_key = (event["head"], event["label"], event["position_ms"])
            if event_key in existing_keys:
                continue
            existing_keys.add(event_key)
            current_events.append(event)
            appended_count += 1

        if appended_count == 0:
            self.statusMessageRequested.emit("Inference", "No new events added.", 1200)
            self._pending_inference_head = None
            return

        self._set_snapshot_events(current_events)
        self.locEventsSetRequested.emit(self.current_sample_id, self._snapshot_events())

        self.statusMessageRequested.emit("Inference", f"Added {appended_count} inferred event(s).", 1500)
        self.saveStateRefreshRequested.emit()
        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons(self.current_video_path)
        self._pending_inference_head = None

    def _on_inference_error(self, error_msg: str):
        self._pending_inference_head = None
        QMessageBox.critical(self.localization_panel, "Inference Error", f"Failed to run model:\n{error_msg}")

    # --- Helper Refresh Methods ---
    def _refresh_schema_ui(self):
        self.localization_panel.table.set_schema(self._schema_definitions)
        self.localization_panel.annot_mgmt.update_schema(self._schema_definitions)

    def _refresh_current_clip_events(self):
        if not self.current_video_path:
            return
        self._display_events_for_item(self.current_video_path)

    def refresh_tree_icons(self, path=None):
        if path:
            self.itemStatusRefreshRequested.emit(path)
            return

        for cached_path in self._action_paths_cache:
            self.itemStatusRefreshRequested.emit(cached_path)

    def _display_events_for_item(self, path, update_markers=None):
        if path and path != self.current_video_path:
            return

        events = self._snapshot_events()
        display_data = sorted(events, key=lambda x: self._event_position_ms(x))
        self.localization_panel.table.set_data(display_data)

        if update_markers is None:
            update_markers = self._is_active_mode()
        if update_markers:
            markers = [{"start_ms": e.get("position_ms", 0), "color": QColor("#00BFFF")} for e in display_data]
            self.markersUpdateRequested.emit(markers)

    def _find_event_index(self, events, event):
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

        events = self._snapshot_events()
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

    @staticmethod
    def _fmt_ms_short(ms: int) -> str:
        ms = max(0, int(ms or 0))
        seconds = ms // 1000
        minutes = seconds // 60
        return f"{minutes:02}:{seconds % 60:02}.{ms % 1000:03}"

    @staticmethod
    def _parse_mmss_to_ms(text: str, fallback: int = 0) -> int:
        value = (text or "").strip()
        if not value:
            return max(0, int(fallback))

        try:
            parts = value.split(":")
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                sec_parts = parts[2].split(".")
                seconds = int(sec_parts[0])
                millis = int(sec_parts[1]) if len(sec_parts) > 1 else 0
                return max(0, ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis)
            if len(parts) == 2:
                minutes = int(parts[0])
                sec_parts = parts[1].split(".")
                seconds = int(sec_parts[0])
                millis = int(sec_parts[1]) if len(sec_parts) > 1 else 0
                return max(0, (minutes * 60 + seconds) * 1000 + millis)
            if len(parts) == 1:
                return max(0, int(float(parts[0]) * 1000))
        except Exception:
            pass

        return max(0, int(fallback))

    # -------------------------------------------------------------------------
    # Snapshot helpers
    # -------------------------------------------------------------------------
    def _set_selected_sample_snapshot(self, sample):
        if not isinstance(sample, dict):
            self._clear_selected_sample_state()
            return

        sample_id = str(sample.get("id") or "")
        path = str(self._action_path_by_sample_id.get(sample_id) or self._extract_primary_path(sample) or "")
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
        self.localization_panel.setEnabled(False)

    def _snapshot_events(self):
        events = self._current_sample_snapshot.get("events", [])
        if not isinstance(events, list):
            return []
        return copy.deepcopy(events)

    def _set_snapshot_events(self, events):
        if not isinstance(self._current_sample_snapshot, dict):
            self._current_sample_snapshot = {}
        normalized = [copy.deepcopy(evt) for evt in list(events or []) if isinstance(evt, dict)]
        normalized.sort(key=self._event_position_ms)
        self._current_sample_snapshot["events"] = normalized

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
