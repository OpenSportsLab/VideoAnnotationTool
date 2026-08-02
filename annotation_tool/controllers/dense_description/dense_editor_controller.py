import copy

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QInputDialog, QMessageBox
from utils import annotation_at_position, parse_utc_datetime, project_temporal_annotations


class DenseEditorController(QObject):
    """
    Dense Description controller.
    Owns dense editor behavior, navigation, and sample-driven selection handling.
    Dataset loading and explorer state updates are handled centrally by DatasetExplorerController.
    """

    statusMessageRequested = pyqtSignal(str, str, int)
    saveStateRefreshRequested = pyqtSignal()
    itemStatusRefreshRequested = pyqtSignal(str)
    # payload: sample_id, ...
    denseEventAddRequested = pyqtSignal(str, dict)
    denseEventModRequested = pyqtSignal(str, dict, dict)
    denseEventDelRequested = pyqtSignal(str, dict, int)
    mediaSeekRequested = pyqtSignal(int)
    markersUpdateRequested = pyqtSignal(object)
    denseEventsSetRequested = pyqtSignal(str, object)
    inferenceRunRequested = pyqtSignal(str, object)
    pendingPredictionsChanged = pyqtSignal(object)

    def __init__(self, dense_panel):
        super().__init__()
        self.dense_panel = dense_panel
        self._last_media_position_ms = 0
        self._active_mode_index = 0
        self._timeline_origin_utc = None
        self._timeline_origins = {}

        self.current_sample_id = ""
        self.current_video_path = None
        self._current_sample_snapshot = {}
        self._pending_predictions = {}

    # -------------------------------------------------------------------------
    # Lifecycle / Wiring
    # -------------------------------------------------------------------------
    def setup_connections(self):
        self.dense_panel.eventNavigateRequested.connect(self._navigate_annotation)
        self.dense_panel.addEventRequested.connect(self._on_add_event_requested)
        self.dense_panel.eventSelected.connect(self._on_event_selected_from_table)
        self.dense_panel.eventDeleted.connect(self._on_delete_single_annotation)
        self.dense_panel.eventModified.connect(self._on_annotation_modified)
        self.dense_panel.updateTimeForSelectedRequested.connect(self._on_update_time_for_selected)
        self.dense_panel.inferenceRequested.connect(
            lambda: self.inferenceRunRequested.emit("dense_description", {"language": "en"})
        )
        self.dense_panel.smartConfirmRequested.connect(self.confirm_selected_smart_prediction)
        self.dense_panel.smartRejectRequested.connect(self.reject_selected_smart_prediction)
        self.dense_panel.smartAcceptAllRequested.connect(self.accept_all_predictions)
        self.dense_panel.smartRejectAllRequested.connect(self.reject_all_predictions)

    def apply_shared_inference_result(self, result, context=None):
        for item in result.items:
            sample_id = str(item.get("sample_id") or "")
            predictions = item.get("dense_captions")
            if not sample_id or not isinstance(predictions, list):
                continue
            pending = []
            for raw in predictions:
                if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
                    continue
                event = copy.deepcopy(raw)
                event.setdefault("lang", "en")
                event["confidence_score"] = float(event.get("confidence_score", 1.0) or 0.0)
                event["inference_model_id"] = result.model_id
                event["_pending_prediction"] = True
                pending.append(event)
            self._pending_predictions[sample_id] = pending
        self._refresh_events_display(update_markers=self._is_active_mode())

    def confirm_selected_smart_prediction(self):
        self._change_selected_smart_prediction(confirm=True)

    def reject_selected_smart_prediction(self):
        self._change_selected_smart_prediction(confirm=False)

    def _change_selected_smart_prediction(self, *, confirm: bool):
        target = self.dense_panel.get_selected_event()
        if not isinstance(target, dict) or not target.get("_pending_prediction") or not self.current_sample_id:
            return
        pending = self._pending_predictions.get(self.current_sample_id, [])
        index = self._find_event_index(pending, target)
        if index < 0:
            return
        if confirm:
            event = pending[index]
            accepted = {key: copy.deepcopy(value) for key, value in event.items() if key not in {"confidence_score", "confidence", "inference_model_id", "_pending_prediction"}}
            events = self._snapshot_dense_events()
            key = (int(accepted.get("position_ms", 0) or 0), str(accepted.get("text") or ""))
            if key not in {(int(e.get("position_ms", 0) or 0), str(e.get("text") or "")) for e in events}:
                events.append(accepted)
                self.denseEventsSetRequested.emit(self.current_sample_id, copy.deepcopy(events))
                self._set_snapshot_dense_events(events)
        pending.pop(index)
        self._refresh_events_display(update_markers=self._is_active_mode())

    def accept_all_predictions(self):
        pending = self._pending_predictions.pop(self.current_sample_id, [])
        if not pending:
            return
        events = self._snapshot_dense_events()
        existing = {(int(e.get("position_ms", 0) or 0), str(e.get("text") or "")) for e in events}
        for event in pending:
            accepted = {key: copy.deepcopy(value) for key, value in event.items() if key not in {"confidence_score", "confidence", "inference_model_id", "_pending_prediction"}}
            key = (int(accepted.get("position_ms", 0) or 0), str(accepted.get("text") or ""))
            if key not in existing:
                existing.add(key)
                events.append(accepted)
        if events != self._snapshot_dense_events():
            self.denseEventsSetRequested.emit(self.current_sample_id, copy.deepcopy(events))
            self._set_snapshot_dense_events(events)
        self._refresh_events_display(update_markers=self._is_active_mode())

    def reject_all_predictions(self):
        self._pending_predictions.pop(self.current_sample_id, None)
        self._refresh_events_display(update_markers=self._is_active_mode())

    def on_mode_changed(self, index: int):
        self._active_mode_index = index
        if not self._is_active_mode():
            return
        if self.current_video_path:
            self._refresh_events_display(update_markers=True)
            return
        self.markersUpdateRequested.emit([])

    def on_media_position_changed(self, ms: int):
        self._last_media_position_ms = max(0, int(ms))

    def on_timeline_origin_changed(self, sample_id: str, origin_utc):
        sample_key = str(sample_id or "")
        origin = parse_utc_datetime(origin_utc)
        if sample_key:
            if origin is None:
                self._timeline_origins.pop(sample_key, None)
            else:
                self._timeline_origins[sample_key] = origin
        if sample_key != self.current_sample_id:
            return
        self._timeline_origin_utc = origin
        self.dense_panel.set_timeline_origin(origin)
        self._set_snapshot_dense_events(
            project_temporal_annotations(
                self._current_sample_snapshot.get("dense_captions", []),
                self._timeline_origin_utc,
            )
        )
        self._refresh_events_display(update_markers=self._is_active_mode())

    def reset_ui(self):
        self._pending_predictions.clear()
        self.pendingPredictionsChanged.emit(set())
        self.dense_panel.set_prediction_actions_visible(False)
        self.dense_panel.set_events([])
        self.dense_panel.set_dense_enabled(False)
        self.current_sample_id = ""
        self.current_video_path = None
        self._current_sample_snapshot = {}
        self._timeline_origin_utc = None
        self._timeline_origins.clear()
        self.dense_panel.set_timeline_origin(None)

    def submit_current_annotation(self):
        self._on_add_event_requested()

    # -------------------------------------------------------------------------
    # Selection + Dense Editing
    # -------------------------------------------------------------------------
    def on_selected_sample_changed(self, sample, resolved_path: str = ""):
        if not isinstance(sample, dict):
            self._clear_current_selection_state(clear_markers=self._is_active_mode())
            return

        sample_id = str(sample.get("id") or "")
        if not sample_id:
            self._clear_current_selection_state(clear_markers=self._is_active_mode())
            return

        path = str(resolved_path or "")
        if not path:
            self._clear_current_selection_state(clear_markers=self._is_active_mode())
            return

        self.current_sample_id = sample_id
        self.current_video_path = path
        self._timeline_origin_utc = self._timeline_origins.get(sample_id)
        self.dense_panel.set_timeline_origin(self._timeline_origin_utc)
        self._current_sample_snapshot = copy.deepcopy(sample)
        self._set_snapshot_dense_events(
            project_temporal_annotations(
                self._current_sample_snapshot.get("dense_captions", []),
                self._timeline_origin_utc,
            )
        )
        if self._is_active_mode() and any(
            "timestamp_utc" in event
            and parse_utc_datetime(event.get("timestamp_utc")) is None
            for event in self._current_sample_snapshot.get("dense_captions", [])
            if isinstance(event, dict)
        ):
            self.statusMessageRequested.emit(
                "Invalid UTC timestamp",
                "A dense annotation has an invalid timestamp_utc; position_ms is being used.",
                3500,
            )
        self.dense_panel.set_dense_enabled(True)
        self._refresh_events_display(update_markers=self._is_active_mode())

    def _on_event_selected_from_table(self, ms: int):
        self._last_media_position_ms = max(0, int(ms))
        self.mediaSeekRequested.emit(int(ms))

    def _on_add_event_requested(self, initial_text: str = ""):
        self.reject_all_predictions()
        if not self.current_video_path:
            QMessageBox.warning(self.dense_panel, "Warning", "Please select a sample first.")
            return

        provided_text = (initial_text or "").strip()
        if provided_text:
            text = provided_text
            accepted = True
        else:
            text, accepted = QInputDialog.getMultiLineText(
                self.dense_panel,
                "Add New Description",
                "Description:",
                "",
            )
            text = (text or "").strip()

        if not accepted or not text:
            return
        if not self.current_sample_id:
            return

        pos_ms = max(0, int(self._last_media_position_ms))
        new_event = annotation_at_position(
            {"lang": "en", "text": text},
            pos_ms,
            self._timeline_origin_utc,
        )
        self.denseEventAddRequested.emit(self.current_sample_id, copy.deepcopy(new_event))
        events = self._snapshot_dense_events()
        events.append(copy.deepcopy(new_event))
        self._set_snapshot_dense_events(events)
        self._refresh_events_display(update_markers=self._is_active_mode())
        self.dense_panel.select_event(new_event)

    def _on_annotation_modified(self, old_event: dict, new_event: dict):
        self.reject_all_predictions()
        if not self.current_video_path:
            return
        if old_event == new_event:
            return

        events = self._snapshot_dense_events()
        event_index = self._find_event_index(events, old_event)
        if event_index < 0:
            return
        if not self.current_sample_id:
            return
        self.denseEventModRequested.emit(
            self.current_sample_id,
            copy.deepcopy(old_event),
            copy.deepcopy(new_event),
        )
        events[event_index] = copy.deepcopy(new_event)
        self._set_snapshot_dense_events(events)

        # Defer to avoid mutating model while the table delegate is still committing edits.
        QTimer.singleShot(
            0,
            lambda: self._refresh_after_event_modification(self.current_video_path, new_event),
        )

    def _refresh_after_event_modification(self, path: str, target_event: dict):
        if path and path != self.current_video_path:
            return
        self._refresh_events_display(update_markers=self._is_active_mode())
        self.dense_panel.select_event(target_event)

    def _on_delete_single_annotation(self, item_data: dict):
        self.reject_all_predictions()
        if not self.current_video_path:
            return

        events = self._snapshot_dense_events()
        event_index = self._find_event_index(events, item_data)
        if event_index < 0:
            return

        if not self.current_sample_id:
            return
        self.denseEventDelRequested.emit(self.current_sample_id, copy.deepcopy(item_data), event_index)
        events.pop(event_index)
        self._set_snapshot_dense_events(events)
        self._refresh_events_display(update_markers=self._is_active_mode())

    def _on_update_time_for_selected(self, old_event: dict):
        if not self.current_video_path:
            return

        current_ms = max(0, int(self._last_media_position_ms))
        new_event = annotation_at_position(old_event, current_ms, self._timeline_origin_utc)
        self._on_annotation_modified(old_event, new_event)

    def display_events_for_item(self, path: str, update_markers=None):
        if path and path != self.current_video_path:
            return
        self._refresh_events_display(update_markers=update_markers)

    # -------------------------------------------------------------------------
    # Navigation
    # -------------------------------------------------------------------------
    def _navigate_annotation(self, step: int):
        events = self._snapshot_dense_events()
        if not events:
            return

        sorted_events = sorted(events, key=lambda x: x.get("position_ms", 0))
        current_pos = max(0, int(self._last_media_position_ms))

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
            self.mediaSeekRequested.emit(target["position_ms"])
            self.dense_panel.select_row_by_time(target["position_ms"])

    def _selected_event_in_table(self):
        return self.dense_panel.get_selected_event()

    def _snapshot_dense_events(self):
        events = self._current_sample_snapshot.get("dense_captions", [])
        if not isinstance(events, list):
            return []
        return copy.deepcopy(events)

    def _set_snapshot_dense_events(self, events):
        if not isinstance(self._current_sample_snapshot, dict):
            self._current_sample_snapshot = {}
        normalized = copy.deepcopy(list(events or []))
        normalized.sort(key=self._event_position_ms)
        self._current_sample_snapshot["dense_captions"] = normalized

    def _refresh_events_display(self, update_markers=None):
        current_selection_ms = None
        current_selected_event = self.dense_panel.get_selected_event()
        if isinstance(current_selected_event, dict):
            current_selection_ms = current_selected_event.get("position_ms")

        events = self._snapshot_dense_events()
        pending = copy.deepcopy(self._pending_predictions.get(self.current_sample_id, []))
        events.extend(pending)
        self.dense_panel.set_events(events)
        self.dense_panel.set_prediction_actions_visible(bool(pending))
        self.pendingPredictionsChanged.emit({sample_id for sample_id, values in self._pending_predictions.items() if values})

        if update_markers is None:
            update_markers = self._is_active_mode()
        if update_markers:
            markers = [
                {"start_ms": event.get("position_ms", 0), "color": QColor("#FFD700")}
                for event in events
            ]
            self.markersUpdateRequested.emit(markers)

        if current_selection_ms is not None:
            self.dense_panel.select_row_by_time(current_selection_ms)

    def _clear_current_selection_state(self, clear_markers: bool = False):
        self.current_sample_id = ""
        self.current_video_path = None
        self._current_sample_snapshot = {}
        self.dense_panel.set_events([])
        self.dense_panel.set_dense_enabled(False)
        if clear_markers:
            self.markersUpdateRequested.emit([])

    @staticmethod
    def _find_event_index(events: list, target_event: dict) -> int:
        try:
            return events.index(target_event)
        except ValueError:
            return -1

    @staticmethod
    def _event_position_ms(event) -> int:
        if not isinstance(event, dict):
            return 0
        try:
            return int(event.get("position_ms", 0) or 0)
        except Exception:
            return 0

    def _is_active_mode(self) -> bool:
        return self._active_mode_index == 3
