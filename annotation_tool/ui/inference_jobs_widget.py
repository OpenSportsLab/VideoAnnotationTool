"""Presentation-only widget for inference queues and session job history."""

from __future__ import annotations

import json
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


_ACTIVE_STATES = {"running", "cancelling"}
_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class InferenceJobsWidget(QWidget):
    """Render immutable queue snapshots and emit user intents only."""

    cancelRequested = pyqtSignal(str)
    cancelAllRequested = pyqtSignal()
    clearHistoryRequested = pyqtSignal()

    def __init__(self, run_action: QAction, parent=None):
        super().__init__(parent)
        self.setObjectName("inferenceJobsWidget")
        self._entries_by_id = {}
        self._selected_request_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        self.run_button = QToolButton(self)
        self.run_button.setObjectName("runInferenceButton")
        self.run_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.run_button.setDefaultAction(run_action)
        toolbar.addWidget(self.run_button)
        toolbar.addStretch(1)
        self.cancel_all_button = QPushButton("Cancel All", self)
        self.cancel_all_button.clicked.connect(self.cancelAllRequested.emit)
        toolbar.addWidget(self.cancel_all_button)
        layout.addLayout(toolbar)

        self.summary_label = QLabel("Local: Idle | Remote: Idle", self)
        self.summary_label.setObjectName("inferenceJobsSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        splitter = QSplitter(self)
        splitter.setOrientation(Qt.Orientation.Vertical)
        self.tabs = QTabWidget(splitter)
        self.local_table = self._add_queue_tab("Local")
        self.remote_table = self._add_queue_tab("Remote")
        self.history_table = self._add_history_tab()

        details_group = QGroupBox("Job Details", splitter)
        details_layout = QVBoxLayout(details_group)
        self.details_view = QTextBrowser(details_group)
        self.details_view.setObjectName("inferenceJobDetails")
        self.details_view.setPlaceholderText("Select Details for a queued or finished job.")
        details_layout.addWidget(self.details_view)
        splitter.addWidget(self.tabs)
        splitter.addWidget(details_group)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    def _add_queue_tab(self, title):
        page = QWidget(self.tabs)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(3, 3, 3, 3)
        table = QTableWidget(0, 4, page)
        table.setHorizontalHeaderLabels(["Job", "State", "Details", "Cancel"])
        self._configure_table(table)
        page_layout.addWidget(table)
        self.tabs.addTab(page, title)
        return table

    def _add_history_tab(self):
        page = QWidget(self.tabs)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(3, 3, 3, 3)
        table = QTableWidget(0, 5, page)
        table.setHorizontalHeaderLabels(
            ["Provider", "Job", "State", "Finished", "Details"]
        )
        self._configure_table(table)
        page_layout.addWidget(table)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.clear_history_button = QPushButton("Clear History", page)
        self.clear_history_button.clicked.connect(self.clearHistoryRequested.emit)
        actions.addWidget(self.clear_history_button)
        page_layout.addLayout(actions)
        self.tabs.addTab(page, "History")
        return table

    @staticmethod
    def _configure_table(table):
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def set_entries(self, entries) -> None:
        entries = tuple(entries or ())
        self._entries_by_id = {entry.request_id: entry for entry in entries}
        active_or_queued = [
            entry
            for entry in entries
            if entry.state in _ACTIVE_STATES | {"queued"}
        ]
        for backend, table in (
            ("local", self.local_table),
            ("remote", self.remote_table),
        ):
            lane = [entry for entry in active_or_queued if entry.backend == backend]
            lane.sort(
                key=lambda entry: (
                    0 if entry.state in _ACTIVE_STATES else 1,
                    entry.queue_position,
                    entry.submitted_at,
                )
            )
            self._populate_queue(table, lane)

        recent = [entry for entry in entries if entry.state in _TERMINAL_STATES]
        self._populate_history(recent)
        self.cancel_all_button.setEnabled(bool(active_or_queued))
        self.clear_history_button.setEnabled(bool(recent))
        self.summary_label.setText(self._summary(entries))

        if self._selected_request_id in self._entries_by_id:
            self._show_details(self._selected_request_id)
        elif self._selected_request_id:
            self._selected_request_id = ""
            self.details_view.clear()

    def _populate_queue(self, table, entries):
        table.setRowCount(0)
        for entry in entries:
            row = table.rowCount()
            table.insertRow(row)
            state = entry.state.title()
            if entry.state == "queued":
                state = f"Queued #{entry.queue_position}"
            elif entry.total > 0:
                state = f"{state} {entry.current}/{entry.total}"
            self._set_item(table, row, 0, self._job_name(entry))
            self._set_item(table, row, 1, state)
            details = QPushButton("Details", table)
            details.clicked.connect(
                lambda _checked=False, request_id=entry.request_id: self._show_details(
                    request_id
                )
            )
            table.setCellWidget(row, 2, details)
            cancel = QPushButton(
                "Cancelling…" if entry.state == "cancelling" else "Cancel", table
            )
            cancel.setEnabled(entry.state != "cancelling")
            cancel.clicked.connect(
                lambda _checked=False, request_id=entry.request_id: self.cancelRequested.emit(
                    request_id
                )
            )
            table.setCellWidget(row, 3, cancel)

    def _populate_history(self, entries):
        self.history_table.setRowCount(0)
        for entry in entries:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            self._set_item(self.history_table, row, 0, entry.backend.title())
            self._set_item(self.history_table, row, 1, self._job_name(entry))
            self._set_item(self.history_table, row, 2, entry.state.title())
            self._set_item(
                self.history_table, row, 3, self._format_time(entry.finished_at)
            )
            details = QPushButton("Details", self.history_table)
            details.clicked.connect(
                lambda _checked=False, request_id=entry.request_id: self._show_details(
                    request_id
                )
            )
            self.history_table.setCellWidget(row, 4, details)

    @staticmethod
    def _set_item(table, row, column, value):
        table.setItem(row, column, QTableWidgetItem(str(value)))

    @staticmethod
    def _job_name(entry):
        task = entry.task.replace("_", " ").title()
        samples = len(entry.sample_ids)
        suffix = f" ({samples} sample{'s' if samples != 1 else ''})"
        return f"{task} · {entry.model_id}{suffix}"

    @staticmethod
    def _format_time(timestamp):
        if not timestamp:
            return "—"
        return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")

    @staticmethod
    def _summary(entries):
        summaries = []
        for backend in ("local", "remote"):
            active = next(
                (
                    entry
                    for entry in entries
                    if entry.backend == backend and entry.state in _ACTIVE_STATES
                ),
                None,
            )
            queued = sum(
                entry.backend == backend and entry.state == "queued"
                for entry in entries
            )
            text = active.state.title() if active is not None else "Idle"
            if active is not None and active.total > 0:
                text += f" {active.current}/{active.total}"
            if queued:
                text += f", {queued} queued"
            summaries.append(f"{backend.title()}: {text}")
        return " | ".join(summaries)

    def _show_details(self, request_id):
        entry = self._entries_by_id.get(str(request_id or ""))
        if entry is None:
            return
        self._selected_request_id = entry.request_id
        started = entry.started_at or entry.submitted_at
        finished = entry.finished_at or 0.0
        duration = max(0.0, finished - started) if finished and started else 0.0
        header = [
            f"{entry.backend.title()} · {self._job_name(entry)}",
            f"State: {entry.state.title()}",
            f"Request: {entry.request_id}",
            f"Submitted: {self._format_time(entry.submitted_at)}",
        ]
        if duration:
            header.append(f"Duration: {duration:.1f}s")
        if entry.error_code:
            header.append(f"Error code: {entry.error_code}")
        lines = ["<br>".join(self._escape(value) for value in header), "<hr>"]
        for event in entry.log_events:
            progress = (
                f" [{event.current}/{event.total}]" if event.total > 0 else ""
            )
            line = (
                f"{self._format_time(event.timestamp)} · "
                f"{event.state.title()} · {event.message}{progress}"
            )
            lines.append(self._escape(line))
            if event.details not in (None, "", {}):
                try:
                    rendered = json.dumps(event.details, sort_keys=True, default=str)
                except TypeError:
                    rendered = str(event.details)
                lines.append(f"&nbsp;&nbsp;{self._escape(rendered)}")
        self.details_view.setHtml("<br>".join(lines))

    @staticmethod
    def _escape(value):
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )


__all__ = ["InferenceJobsWidget"]
