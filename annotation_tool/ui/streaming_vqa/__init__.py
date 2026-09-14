"""Manual Streaming VQA editor. Widgets emit intents; they never mutate a project."""

import copy
from uuid import uuid4

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QRadioButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from streaming_vqa import entry_errors, format_ask_time, normalize_for_write, with_ask_time
from utils import annotation_utc_datetime, format_utc_datetime


class StreamingVQADialog(QDialog):
    def __init__(self, entry, origin=None, other_ids=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Streaming VQA Question")
        self.resize(620, 560)
        self._original = copy.deepcopy(entry) if isinstance(entry, dict) else {}
        self._origin = origin
        self._other_ids = other_ids
        self.result_entry = None
        self.option_rows = []
        self.correct_group = QButtonGroup(self)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Ask time — available history is sample start through this time"))
        timestamp = annotation_utc_datetime(self._original, origin)
        time_text = (format_utc_datetime(timestamp) + " UTC") if timestamp else format_ask_time(self._original, origin)
        if "timestamp_utc" in self._original and timestamp is None:
            time_text = str(self._original["timestamp_utc"])
        self.time_edit = QLineEdit(time_text)
        self._initial_time = time_text
        self.time_edit.setAccessibleName("Ask time")
        layout.addWidget(self.time_edit)
        layout.addWidget(QLabel("Question"))
        self.question_edit = QPlainTextEdit(str(self._original.get("question") or ""))
        self.question_edit.setAccessibleName("Question")
        self.question_edit.setMaximumHeight(110)
        layout.addWidget(self.question_edit)
        layout.addWidget(QLabel("Choices — select the one correct answer"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        choice_widget = QWidget()
        self.choices_layout = QVBoxLayout(choice_widget)
        self.choices_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(choice_widget)
        layout.addWidget(scroll, 1)
        raw_options = self._original.get("options")
        for option in raw_options if isinstance(raw_options, list) else [{} for _ in range(4)]:
            self.add_option(option)
        add_button = QPushButton("+ Add Choice")
        add_button.setAutoDefault(False)
        add_button.clicked.connect(lambda: self.add_option())
        layout.addWidget(add_button)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setAccessibleName("Validation errors")
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_option(self, option=None):
        payload = copy.deepcopy(option) if isinstance(option, dict) else {}
        existing_ids = [row[1]["id"] for row in self.option_rows]
        option_id = payload.get("id")
        if not isinstance(option_id, str) or not option_id.strip() or option_id in existing_ids:
            payload["id"] = str(uuid4())
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        radio = QRadioButton()
        radio.setAccessibleName("Correct choice")
        self.correct_group.addButton(radio)
        radio.setChecked(payload["id"] == self._original.get("correct_option_id"))
        edit = QLineEdit(str(payload.get("text") or ""))
        edit.setAccessibleName("Choice text")
        layout.addWidget(radio)
        layout.addWidget(edit, 1)
        for text, callback in (
            ("↑", lambda: self.move_option(widget, -1)),
            ("↓", lambda: self.move_option(widget, 1)),
            ("Remove", lambda: self.remove_option(widget)),
        ):
            button = QPushButton(text)
            button.setAutoDefault(False)
            button.setAccessibleName({"↑": "Move choice up", "↓": "Move choice down"}.get(text, text))
            button.clicked.connect(callback)
            layout.addWidget(button)
        self.option_rows.append((widget, payload, radio, edit))
        self.choices_layout.addWidget(widget)

    def remove_option(self, widget):
        row = next(row for row in self.option_rows if row[0] is widget)
        self.correct_group.removeButton(row[2])
        self.option_rows.remove(row)
        self.choices_layout.removeWidget(widget)
        widget.deleteLater()

    def move_option(self, widget, step):
        index = next(index for index, row in enumerate(self.option_rows) if row[0] is widget)
        target = index + step
        if 0 <= target < len(self.option_rows):
            row = self.option_rows.pop(index)
            self.option_rows.insert(target, row)
            self.choices_layout.removeWidget(widget)
            self.choices_layout.insertWidget(target, widget)

    def accept(self):
        entry = copy.deepcopy(self._original)
        question_id = entry.get("id")
        if not isinstance(question_id, str) or not question_id.strip() or question_id in self._other_ids:
            entry["id"] = str(uuid4())
        question_text = self.question_edit.toPlainText()
        entry["question"] = question_text if question_text == entry.get("question") else question_text.strip()
        entry["options"] = []
        entry.pop("correct_option_id", None)
        for _, payload, radio, edit in self.option_rows:
            text = edit.text()
            option = dict(payload, text=text if text == payload.get("text") else text.strip())
            entry["options"].append(option)
            if radio.isChecked():
                entry["correct_option_id"] = option["id"]
        if self.time_edit.text().strip() != self._initial_time:
            try:
                entry = with_ask_time(entry, self.time_edit.text(), self._origin)
            except ValueError as error:
                self.error_label.setText(str(error))
                return
        errors = entry_errors(entry, self._other_ids)
        if errors:
            self.error_label.setText("\n".join(dict.fromkeys(errors)))
            return
        # Opening and saving an unchanged row must not promote legacy time fields.
        self.result_entry = entry if entry == self._original else normalize_for_write([entry], self._origin)[0]
        super().accept()


class StreamingVQAAnnotationPanel(QWidget):
    addRequested = pyqtSignal()
    editRequested = pyqtSignal()
    deleteRequested = pyqtSignal()
    entrySelected = pyqtSignal(int)
    seekRequested = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        self.add_button = QPushButton("+ Add Question")
        self.edit_button = QPushButton("Edit")
        self.delete_button = QPushButton("Delete")
        for button, signal in ((self.add_button, self.addRequested), (self.edit_button, self.editRequested), (self.delete_button, self.deleteRequested)):
            actions.addWidget(button)
            button.clicked.connect(signal.emit)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Ask time", "Question", "Correct"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self.editRequested.emit())
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel("Selected question"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Selected question and choices")
        layout.addWidget(self.details, 1)
        self.go_button = QPushButton("Go to Ask Time")
        self.go_button.clicked.connect(self.seekRequested.emit)
        layout.addWidget(self.go_button)
        self.set_selection_actions(False)

    def selected_index(self):
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else -1

    def _on_selection_changed(self):
        self.entrySelected.emit(self.selected_index())

    def set_rows(self, rows, selected_index):
        blocked = self.table.blockSignals(True)
        self.table.setRowCount(0)
        selected_row = -1
        for index, time, question, correct, errors in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, text in enumerate((time, question, correct)):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setToolTip("\n".join(errors) if errors else text)
                self.table.setItem(row, column, item)
            if index == selected_index:
                selected_row = row
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        else:
            self.table.setCurrentCell(-1, -1)
        self.table.blockSignals(blocked)

    def set_selection_actions(self, selected, seekable=False):
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)
        self.go_button.setEnabled(selected and seekable)

    def edit_entry(self, entry, origin, other_ids):
        dialog = StreamingVQADialog(entry, origin, other_ids, self)
        return dialog.result_entry if dialog.exec() == QDialog.DialogCode.Accepted else None
