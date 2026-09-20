"""Presentation-only widget for all inference jobs and persistent history."""

from __future__ import annotations

import json
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton,
    QVBoxLayout, QWidget,
)

_ACTIVE_STATES = {"running", "cancelling"}
_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class InferenceJobsWidget(QWidget):
    cancelRequested = pyqtSignal(str)
    cancelAllRequested = pyqtSignal()
    clearHistoryRequested = pyqtSignal()

    def __init__(self, run_action: QAction, parent=None):
        super().__init__(parent)
        self.setObjectName("inferenceJobsWidget")
        self._entries_by_id = {}
        self._selected_request_id = ""
        self._providers = [("local", "Local", True)]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        toolbar = QHBoxLayout()
        self.run_button = QToolButton(self)
        self.run_button.setObjectName("runInferenceButton")
        self.run_button.setDefaultAction(run_action)
        toolbar.addWidget(self.run_button)
        toolbar.addStretch(1)
        self.cancel_all_button = QPushButton("Cancel All", self)
        self.clear_history_button = QPushButton("Clear Finished", self)
        self.cancel_all_button.clicked.connect(self.cancelAllRequested.emit)
        self.clear_history_button.clicked.connect(self.clearHistoryRequested.emit)
        toolbar.addWidget(self.cancel_all_button)
        toolbar.addWidget(self.clear_history_button)
        layout.addLayout(toolbar)
        self.summary_label = QLabel("Local: Idle", self)
        self.summary_label.setObjectName("inferenceJobsSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self.storage_error_label = QLabel("", self)
        self.storage_error_label.setObjectName("inferenceHistoryError")
        self.storage_error_label.setWordWrap(True)
        self.storage_error_label.setStyleSheet("color: #b45309;")
        self.storage_error_label.hide()
        layout.addWidget(self.storage_error_label)
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.jobs_table = QTableWidget(0, 8, splitter)
        self.jobs_table.setObjectName("inferenceJobsTable")
        self.jobs_table.setHorizontalHeaderLabels([
            "Provider", "Job", "State / Progress", "Queue Position",
            "Submitted", "Finished", "Details", "Cancel",
        ])
        self._configure_table(self.jobs_table)
        # Transitional aliases still reference this single canonical table.
        self.local_table = self.remote_table = self.history_table = self.jobs_table
        details_group = QGroupBox("Job Details", splitter)
        details_layout = QVBoxLayout(details_group)
        self.details_view = QTextBrowser(details_group)
        self.details_view.setObjectName("inferenceJobDetails")
        self.details_view.setPlaceholderText("Select Details for an inference job.")
        details_layout.addWidget(self.details_view)
        splitter.addWidget(self.jobs_table)
        splitter.addWidget(details_group)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    @staticmethod
    def _configure_table(table):
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def set_history_error(self, message: str) -> None:
        self.storage_error_label.setText(str(message or ""))
        self.storage_error_label.setVisible(bool(message))

    def set_providers(self, providers) -> None:
        self._providers = [
            (
                str(item.get("id") or ""),
                str(item.get("name") or item.get("id") or ""),
                item.get("kind") == "local" or bool(item.get("enabled")),
            )
            for item in providers or []
        ] or [("local", "Local", True)]
        self.summary_label.setText(self._summary(self._entries_by_id.values()))

    def set_entries(self, entries) -> None:
        entries = tuple(entries or ())
        self._entries_by_id = {entry.request_id: entry for entry in entries}
        self.jobs_table.setRowCount(0)
        for entry in sorted(entries, key=self._sort_key):
            self._append_row(entry)
        active = [entry for entry in entries if entry.state in _ACTIVE_STATES | {"queued"}]
        terminal = [entry for entry in entries if entry.state in _TERMINAL_STATES]
        self.cancel_all_button.setEnabled(bool(active))
        self.clear_history_button.setEnabled(bool(terminal))
        self.summary_label.setText(self._summary(entries))
        if self._selected_request_id in self._entries_by_id:
            self._show_details(self._selected_request_id)
        elif self._selected_request_id:
            self._selected_request_id = ""
            self.details_view.clear()

    @staticmethod
    def _sort_key(entry):
        if entry.state in _ACTIVE_STATES:
            return (0, entry.submitted_at)
        if entry.state == "queued":
            return (1, entry.submitted_at)
        return (2, -entry.finished_at)

    def _append_row(self, entry):
        table = self.jobs_table
        row = table.rowCount()
        table.insertRow(row)
        state = entry.state.title()
        if entry.total > 0 and entry.state in _ACTIVE_STATES:
            state += f" {entry.current}/{entry.total}"
        queue = str(entry.queue_position) if entry.state == "queued" else "—"
        values = (
            entry.provider_name or entry.backend.title(), self._job_name(entry),
            state, queue, self._format_time(entry.submitted_at),
            self._format_time(entry.finished_at),
        )
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value)))
        details = QPushButton("Details", table)
        details.clicked.connect(lambda _checked=False, rid=entry.request_id: self._show_details(rid))
        table.setCellWidget(row, 6, details)
        if entry.state in _ACTIVE_STATES | {"queued"}:
            cancel = QPushButton("Cancelling…" if entry.state == "cancelling" else "Cancel", table)
            cancel.setEnabled(entry.state != "cancelling")
            cancel.clicked.connect(lambda _checked=False, rid=entry.request_id: self.cancelRequested.emit(rid))
            table.setCellWidget(row, 7, cancel)

    @staticmethod
    def _job_name(entry):
        task = entry.task.replace("_", " ").title()
        count = len(entry.sample_ids)
        return f"{task} · {entry.model_id} ({count} sample{'s' if count != 1 else ''})"

    @staticmethod
    def _format_time(timestamp):
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "—"

    def _summary(self, entries):
        providers = list(self._providers)
        for entry in entries:
            if entry.state in _TERMINAL_STATES:
                continue
            provider_id = entry.provider_id or entry.backend
            if not any(item[0] == provider_id for item in providers):
                providers.append((
                    provider_id, entry.provider_name or entry.backend.title(), True
                ))
        output = []
        for provider_id, name, enabled in providers:
            lane = [entry for entry in entries if (entry.provider_id or entry.backend) == provider_id]
            running = next((entry for entry in lane if entry.state in _ACTIVE_STATES), None)
            queued = sum(entry.state == "queued" for entry in lane)
            text = (
                running.state.title() if running
                else "Idle" if enabled or queued
                else "Disabled"
            )
            if running and running.total > 0:
                text += f" {running.current}/{running.total}"
            if queued:
                text += f", {queued} queued"
            output.append(f"{name}: {text}")
        return " | ".join(output)

    def _show_details(self, request_id):
        entry = self._entries_by_id.get(str(request_id or ""))
        if entry is None:
            return
        self._selected_request_id = entry.request_id
        started = entry.started_at or entry.submitted_at
        duration = max(0.0, entry.finished_at - started) if entry.finished_at and started else 0.0
        header = [
            f"{entry.provider_name or entry.backend.title()} · {self._job_name(entry)}",
            f"State: {entry.state.title()}", f"Request: {entry.request_id}",
            f"Submitted: {self._format_time(entry.submitted_at)}",
        ]
        if duration:
            header.append(f"Duration: {duration:.1f}s")
        if entry.error_code:
            header.append(f"Error code: {entry.error_code}")
        lines = ["<br>".join(self._escape(value) for value in header), "<hr>"]
        for event in entry.log_events:
            progress = f" [{event.current}/{event.total}]" if event.total > 0 else ""
            lines.append(self._escape(f"{self._format_time(event.timestamp)} · {event.state.title()} · {event.message}{progress}"))
            if event.details not in (None, "", {}):
                lines.append("&nbsp;&nbsp;" + self._escape(json.dumps(event.details, sort_keys=True, default=str)))
        self.details_view.setHtml("<br>".join(lines))

    @staticmethod
    def _escape(value):
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = ["InferenceJobsWidget"]
