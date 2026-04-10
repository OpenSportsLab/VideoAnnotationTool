import copy

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QInputDialog, QMessageBox


class DenseEditorController(QObject):
    """
    Dense Description controller.
    Owns dense editor behavior, navigation, and sample-driven selection handling.
    Dataset add/remove/filter/clear is handled centrally by DatasetExplorerController.
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

    def __init__(self, dense_panel):
        super().__init__()
        self.dense_panel = dense_panel
        self._last_media_position_ms = 0
        self._active_mode_index = 0

        self.current_sample_id = ""
        self.current_video_path = None
        self._current_sample_snapshot = {}

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

    def reset_ui(self):
        self.dense_panel.set_events([])
        self.dense_panel.set_dense_enabled(False)
        self.current_sample_id = ""
        self.current_video_path = None
        self._current_sample_snapshot = {}

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
        self._current_sample_snapshot = copy.deepcopy(sample)
        self._set_snapshot_dense_events(self._current_sample_snapshot.get("dense_captions", []))
        self.dense_panel.set_dense_enabled(True)
        self._refresh_events_display(update_markers=self._is_active_mode())

    def _on_event_selected_from_table(self, ms: int):
        self._last_media_position_ms = max(0, int(ms))
        self.mediaSeekRequested.emit(int(ms))

    def _on_add_event_requested(self, initial_text: str = ""):
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
        new_event = {"position_ms": pos_ms, "lang": "en", "text": text}
        self.denseEventAddRequested.emit(self.current_sample_id, copy.deepcopy(new_event))
        events = self._snapshot_dense_events()
        events.append(copy.deepcopy(new_event))
        self._set_snapshot_dense_events(events)
        self._refresh_events_display(update_markers=self._is_active_mode())
        self.dense_panel.select_event(new_event)

    def _on_annotation_modified(self, old_event: dict, new_event: dict):
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
        new_event = old_event.copy()
        new_event["position_ms"] = current_ms
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
        self.dense_panel.set_events(events)

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
