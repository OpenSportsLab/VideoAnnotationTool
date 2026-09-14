"""Streaming VQA mode controller."""

import copy
from uuid import uuid4

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor

from streaming_vqa import entries_with_errors, entry_errors, format_ask_time
from utils import annotation_at_position, annotation_position_ms, parse_utc_datetime


class StreamingVQAEditorController(QObject):
    streamingVQAUpdateRequested = pyqtSignal(str, object)
    mediaSeekRequested = pyqtSignal(int)
    markersUpdateRequested = pyqtSignal(object)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self._active = False
        self._origins = {}
        self.reset_ui()

    def setup_connections(self):
        self.panel.addRequested.connect(self.add_question)
        self.panel.editRequested.connect(self.edit_question)
        self.panel.deleteRequested.connect(self.delete_question)
        self.panel.entrySelected.connect(self.select_question)
        self.panel.seekRequested.connect(self.seek_selected)

    def reset_ui(self):
        self.current_sample_id = ""
        self._entries = []
        self._invalid_container = False
        self._selected_index = -1
        self._position_ms = 0
        self._origins.clear()
        self._refresh()

    @property
    def origin(self):
        return self._origins.get(self.current_sample_id)

    def on_selected_sample_changed(self, sample):
        sample = sample if isinstance(sample, dict) else {}
        sample_id = str(sample.get("id") or "")
        if sample_id != self.current_sample_id:
            self._selected_index = -1
        self.current_sample_id = sample_id
        raw = sample.get("streaming_vqa", [])
        self._invalid_container = not isinstance(raw, list)
        self._entries = copy.deepcopy(raw if isinstance(raw, list) else [raw])
        if not 0 <= self._selected_index < len(self._entries):
            self._selected_index = -1
        self._refresh()

    def on_media_position_changed(self, position_ms):
        self._position_ms = max(0, int(position_ms))

    def on_timeline_origin_changed(self, sample_id, origin):
        self._origins[str(sample_id)] = parse_utc_datetime(origin)
        if str(sample_id) == self.current_sample_id:
            self._refresh()

    def on_mode_changed(self, index):
        self._active = index == 5
        if self._active:
            self._refresh()

    def add_question(self):
        if not self.current_sample_id:
            return
        entry = annotation_at_position({"id": str(uuid4()), "question": ""}, self._position_ms, self.origin)
        self._edit(entry, -1)

    def edit_question(self):
        if 0 <= self._selected_index < len(self._entries):
            self._edit(self._entries[self._selected_index], self._selected_index)

    def _edit(self, entry, index):
        sample_id = self.current_sample_id
        other_ids = [item.get("id") for i, item in enumerate(self._entries) if i != index and isinstance(item, dict)]
        updated = self.panel.edit_entry(copy.deepcopy(entry), self.origin, other_ids)
        if updated is None or self.current_sample_id != sample_id or entry_errors(updated, other_ids):
            return
        if updated == entry and not self._invalid_container:
            return
        entries = copy.deepcopy(self._entries)
        if index < 0:
            index = len(entries)
            entries.append(updated)
        else:
            entries[index] = updated
        self._commit(entries, index)

    def delete_question(self):
        if 0 <= self._selected_index < len(self._entries):
            entries = copy.deepcopy(self._entries)
            entries.pop(self._selected_index)
            self._commit(entries, -1)

    def _commit(self, entries, selected_index):
        # Refreshes emitted by HistoryManager may clear a newly hidden sample.
        # Set local presentation first; never overwrite that owner refresh afterward.
        self._entries = copy.deepcopy(entries)
        self._invalid_container = False
        self._selected_index = selected_index
        self._refresh()
        self.streamingVQAUpdateRequested.emit(self.current_sample_id, entries)

    def select_question(self, index):
        self._selected_index = index
        self._refresh_details()
        self.seek_selected()

    def seek_selected(self):
        if 0 <= self._selected_index < len(self._entries):
            entry = self._entries[self._selected_index]
            if isinstance(entry, dict) and (type(entry.get("position_ms")) is int or parse_utc_datetime(entry.get("timestamp_utc")) is not None):
                self.mediaSeekRequested.emit(annotation_position_ms(entry, self.origin))

    def _refresh(self):
        rows, markers = [], []
        for index, (entry, errors) in enumerate(self._validated_rows()):
            question, correct = "Invalid question", ""
            if isinstance(entry, dict):
                question = str(entry.get("question") or "(Empty question)")
                options = entry.get("options")
                if isinstance(options, list):
                    correct = next((str(option.get("text") or "") for option in options if isinstance(option, dict) and option.get("id") == entry.get("correct_option_id")), "")
            if not errors:
                markers.append({"start_ms": annotation_position_ms(entry, self.origin), "color": QColor("#38BDF8")})
            rows.append((index, format_ask_time(entry, self.origin), ("⚠ " if errors else "") + question, correct, errors))
        rows.sort(key=lambda row: annotation_position_ms(self._entries[row[0]], self.origin))
        self.panel.set_rows(rows, self._selected_index)
        self.panel.add_button.setEnabled(bool(self.current_sample_id))
        self._refresh_details()
        if self._active:
            self.markersUpdateRequested.emit(markers)

    def _refresh_details(self):
        selected = 0 <= self._selected_index < len(self._entries)
        text, seekable = "", False
        if selected:
            entry, errors = self._validated_rows()[self._selected_index]
            if isinstance(entry, dict):
                text = str(entry.get("question") or "")
                options = entry.get("options")
                for option in options if isinstance(options, list) else []:
                    if isinstance(option, dict):
                        prefix = "●" if option.get("id") == entry.get("correct_option_id") else "○"
                        text += f"\n\n{prefix} {option.get('text', '')}"
                seekable = type(entry.get("position_ms")) is int or parse_utc_datetime(entry.get("timestamp_utc")) is not None
            if errors:
                text += "\n\nNeeds repair:\n" + "\n".join(dict.fromkeys(errors))
        self.panel.details.setPlainText(text)
        self.panel.set_selection_actions(selected, seekable)

    def _validated_rows(self):
        rows = entries_with_errors(self._entries)
        if self._invalid_container:
            for _, errors in rows:
                errors.append("streaming_vqa must be an array. Edit or delete this row to repair it.")
        return rows
