"""Status-bar summary and non-modal panel for Local/Remote inference queues."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


_ACTIVE_STATES = {"running", "cancelling"}
_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class InferenceQueuePanel(QDialog):
    cancelRequested = pyqtSignal(str)
    clearHistoryRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inference Queue")
        self.setModal(False)
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        self.local_table = self._add_queue_section(layout, "Local")
        self.remote_table = self._add_queue_section(layout, "Remote")

        recent_group = QGroupBox("Recent Jobs", self)
        recent_layout = QVBoxLayout(recent_group)
        self.recent_table = QTableWidget(0, 4, recent_group)
        self.recent_table.setHorizontalHeaderLabels(
            ["Provider", "Task / Model", "State", "Details"]
        )
        self._configure_table(self.recent_table)
        recent_layout.addWidget(self.recent_table)
        recent_actions = QHBoxLayout()
        recent_actions.addStretch(1)
        self.clear_history_button = QPushButton("Clear History", recent_group)
        self.clear_history_button.clicked.connect(self.clearHistoryRequested.emit)
        recent_actions.addWidget(self.clear_history_button)
        recent_layout.addLayout(recent_actions)
        layout.addWidget(recent_group)

    def _add_queue_section(self, layout, title):
        group = QGroupBox(f"{title} Queue", self)
        group_layout = QVBoxLayout(group)
        table = QTableWidget(0, 4, group)
        table.setHorizontalHeaderLabels(
            ["Task / Model", "Samples", "State / Progress", "Action"]
        )
        self._configure_table(table)
        group_layout.addWidget(table)
        layout.addWidget(group)
        return table

    @staticmethod
    def _configure_table(table):
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def set_entries(self, entries) -> None:
        entries = tuple(entries or ())
        for backend, table in (
            ("local", self.local_table),
            ("remote", self.remote_table),
        ):
            queue_entries = [
                entry
                for entry in entries
                if entry.backend == backend
                and entry.state in _ACTIVE_STATES | {"queued"}
            ]
            queue_entries.sort(
                key=lambda entry: (
                    0 if entry.state in _ACTIVE_STATES else 1,
                    entry.queue_position,
                    entry.submitted_at,
                )
            )
            self._populate_queue_table(table, queue_entries)

        recent = [entry for entry in entries if entry.state in _TERMINAL_STATES]
        self.recent_table.setRowCount(0)
        for entry in recent:
            row = self.recent_table.rowCount()
            self.recent_table.insertRow(row)
            details = entry.message
            if entry.error_code:
                details = f"{details} [{entry.error_code}]".strip()
            if entry.error_details not in (None, "", {}):
                details = f"{details} · {entry.error_details}"
            for column, value in enumerate(
                (
                    entry.backend.title(),
                    f"{entry.task.replace('_', ' ')} · {entry.model_id}",
                    entry.state.title(),
                    details,
                )
            ):
                self.recent_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.clear_history_button.setEnabled(bool(recent))

    def _populate_queue_table(self, table, entries):
        table.setRowCount(0)
        for entry in entries:
            row = table.rowCount()
            table.insertRow(row)
            state = entry.state.title()
            if entry.state == "queued":
                state = f"Queued #{entry.queue_position}"
            elif entry.total > 0:
                state = f"{state} · {entry.current}/{entry.total}"
            elif entry.message:
                state = f"{state} · {entry.message}"
            values = (
                f"{entry.task.replace('_', ' ')} · {entry.model_id}",
                str(len(entry.sample_ids)),
                state,
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))
            cancel = QPushButton(
                "Cancelling…" if entry.state == "cancelling" else "Cancel",
                table,
            )
            cancel.setEnabled(entry.state != "cancelling")
            cancel.clicked.connect(
                lambda _checked=False, request_id=entry.request_id: self.cancelRequested.emit(
                    request_id
                )
            )
            table.setCellWidget(row, 3, cancel)


class InferenceActivityWidget(QFrame):
    cancelRequested = pyqtSignal(str)
    clearHistoryRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inferenceActivityWidget")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 2, 1)
        layout.setSpacing(6)
        self.label = QLabel("", self)
        self.label.setObjectName("inferenceActivityLabel")
        self.details_button = QPushButton("Details", self)
        self.details_button.setObjectName("inferenceQueueDetailsButton")
        layout.addWidget(self.label, 1)
        layout.addWidget(self.details_button)

        self.panel = InferenceQueuePanel(parent)
        self.panel.cancelRequested.connect(self.cancelRequested.emit)
        self.panel.clearHistoryRequested.connect(self.clearHistoryRequested.emit)
        self.details_button.clicked.connect(self.show_panel)
        self.setVisible(False)

    def set_entries(self, entries) -> None:
        entries = tuple(entries or ())
        self.panel.set_entries(entries)
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
            if active is not None:
                text = active.state.title()
                if active.total > 0:
                    text += f" {active.current}/{active.total}"
            else:
                text = "Idle"
            if queued:
                text += f", {queued} queued"
            summaries.append(f"{backend.title()}: {text}")
        has_recent = any(entry.state in _TERMINAL_STATES for entry in entries)
        self.label.setText("Inference · " + " | ".join(summaries))
        self.setVisible(bool(entries))
        if not entries:
            self.panel.hide()
        elif has_recent and not any(
            entry.state in _ACTIVE_STATES | {"queued"} for entry in entries
        ):
            self.label.setText("Inference · Recent jobs")

    def show_panel(self) -> None:
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def close_panel(self) -> None:
        self.panel.hide()


__all__ = ["InferenceActivityWidget", "InferenceQueuePanel"]
