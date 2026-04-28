import os
import copy
import json
import re

from PyQt6 import uic
from PyQt6.QtCore import Qt, QModelIndex, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from utils import resource_path


def _natural_sort_text(value) -> str:
    parts = re.split(r"([0-9]+)", str(value or "").casefold())
    return "".join(part.zfill(12) if part.isdigit() else part for part in parts)


class DatasetExplorerTreeModel(QStandardItemModel):
    """
    Internal tree model used by DatasetExplorerPanel.
    """

    FilePathRole = Qt.ItemDataRole.UserRole
    DataIdRole = Qt.ItemDataRole.UserRole + 1
    SortRole = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.configure_columns()

    def configure_columns(self):
        self.setColumnCount(1)
        self.setSortRole(self.SortRole)

    def add_entry(
        self,
        name: str,
        path: str,
        source_files: list = None,
        icon=None,
        data_id: str = None,
        confidence_score: float = None,
    ) -> QStandardItem:
        display_name = self.entry_display_name(name, confidence_score)
        item = QStandardItem(display_name)
        item.setEditable(True)
        item.setData(path, self.FilePathRole)
        item.setData(data_id, self.DataIdRole)
        item.setData(_natural_sort_text(name), self.SortRole)

        if icon:
            item.setIcon(icon)

        if source_files:
            for src in source_files:
                child_name = os.path.basename(src) or str(src)
                child = QStandardItem(child_name)
                child.setEditable(False)
                child.setData(src, self.FilePathRole)
                child.setData(data_id, self.DataIdRole)
                child.setData(_natural_sort_text(child_name), self.SortRole)
                item.appendRow(child)

        self.appendRow(item)
        return item

    @staticmethod
    def entry_display_name(name: str, confidence_score: float = None) -> str:
        display_name = str(name or "")
        if confidence_score is not None:
            display_name = f"{display_name} (conf:{float(confidence_score):.2f})"
        return display_name


class DatasetExplorerPanel(QWidget):
    """
    Dataset Explorer view backed by a Qt Designer .ui file.
    """

    removeItemRequested = pyqtSignal(QModelIndex)
    addDataRequested = pyqtSignal()
    sampleNavigateRequested = pyqtSignal(int)
    headerDraftChanged = pyqtSignal(dict)

    _HEADER_VALUE_ROLE = Qt.ItemDataRole.UserRole + 200
    _HEADER_HAS_VALUE_ROLE = Qt.ItemDataRole.UserRole + 201
    _MISSING = object()

    def __init__(
        self,
        tree_title="Project Items",
        filter_items=None,
        clear_text="Clear All",
        enable_context_menu=True,
        parent=None,
    ):
        super().__init__(parent)

        ui_path = resource_path(
            os.path.join("ui", "dataset_explorer_panel", "dataset_explorer_panel.ui")
        )
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load DatasetExplorerPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        self.tree_model = DatasetExplorerTreeModel(self)
        self.tree.setModel(self.tree_model)
        self._header_key_order = [
            "version",
            "date",
            "dataset_name",
            "description",
            "metadata",
        ]
        self._header_known = {}
        self._header_unknown = {}
        self._header_draft = {}
        self._suspend_header_signals = False

        self._configure_widgets(tree_title, filter_items, clear_text)
        self.btn_add_data.clicked.connect(self.addDataRequested.emit)
        self.btn_prev_sample.clicked.connect(lambda: self.sampleNavigateRequested.emit(-1))
        self.btn_next_sample.clicked.connect(lambda: self.sampleNavigateRequested.emit(1))
        self._set_context_menu_enabled(enable_context_menu)

    def _configure_widgets(self, tree_title, filter_items, clear_text):
        self.lbl_title.setText(tree_title)
        self.lbl_title.setProperty("class", "panel_header_lbl")

        self.clear_btn.setText(clear_text)
        self.clear_btn.setObjectName("panel_clear_btn")

        self.filter_combo.clear()
        if filter_items:
            self.filter_combo.addItems(filter_items)
        self.bottomLayout.setStretch(1, 1)

        self.tree.setHeaderHidden(True)
        self.tree.setSortingEnabled(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.json_raw_text.setReadOnly(True)
        self.json_raw_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._configure_header_tables()

    def _configure_header_tables(self):
        self._configure_single_header_table(self.table_header_known, editable=True)
        self._configure_single_header_table(self.table_header_unknown, editable=False)
        self.table_header_known.itemChanged.connect(self._on_known_header_item_changed)
        self.table_header_known.cellDoubleClicked.connect(self._on_known_header_cell_double_clicked)

    def _configure_single_header_table(self, table, editable: bool):
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Key", "Value"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setWordWrap(True)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        if editable:
            table.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked
                | QAbstractItemView.EditTrigger.EditKeyPressed
                | QAbstractItemView.EditTrigger.SelectedClicked
            )
        else:
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def _set_context_menu_enabled(self, enabled: bool):
        try:
            self.tree.customContextMenuRequested.disconnect(self._show_context_menu)
        except TypeError:
            pass

        if enabled:
            self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self._show_context_menu)
        else:
            self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    def _show_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return

        menu = QMenu(self.tree)
        remove_label = "Remove Input" if index.parent().isValid() else "Remove Sample"
        remove_action = menu.addAction(remove_label)
        selected = menu.exec(self.tree.mapToGlobal(pos))
        if selected == remove_action:
            self.removeItemRequested.emit(index)

    # ------------------------------------------------------------------
    # Header Inspector API
    # ------------------------------------------------------------------
    def set_header_rows(self, known: dict, unknown: dict, draft: dict = None, key_order=None):
        self._suspend_header_signals = True
        self._header_known = copy.deepcopy(known or {})
        self._header_unknown = copy.deepcopy(unknown or {})
        self._header_draft = copy.deepcopy(draft or {})
        if key_order:
            self._header_key_order = list(key_order)

        self._populate_known_table()
        self._populate_unknown_table()
        self._suspend_header_signals = False

    def clear_header_rows(self):
        self.set_header_rows({}, {}, {})

    def set_raw_json_text(self, raw_json: str):
        self.json_raw_text.setPlainText(raw_json or "")

    def clear_raw_json_text(self):
        self.json_raw_text.clear()

    def get_staged_header_draft(self):
        return copy.deepcopy(self._header_draft)

    def _populate_known_table(self):
        table = self.table_header_known
        table.setRowCount(0)
        default_row_height = table.verticalHeader().defaultSectionSize()
        line_height = max(1, table.fontMetrics().lineSpacing())
        for row, key in enumerate(self._header_key_order):
            table.insertRow(row)

            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, key_item)

            value = self._value_for_known_key(key)
            has_value = value is not self._MISSING
            display = self._stringify_header_value(value if has_value else "")

            value_item = QTableWidgetItem(display)
            value_item.setData(self._HEADER_HAS_VALUE_ROLE, has_value)
            value_item.setData(
                self._HEADER_VALUE_ROLE,
                copy.deepcopy(value) if has_value else None,
            )

            is_nested = key == "metadata" or (
                has_value and isinstance(value, (dict, list))
            )
            if is_nested:
                value_item.setToolTip("Double-click to edit JSON object/array.")
                value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 1, value_item)

            if key == "description":
                # Keep long descriptions readable in-place (about 5 text lines).
                table.setRowHeight(row, line_height * 5 + 8)
            else:
                table.setRowHeight(row, default_row_height)

    def _populate_unknown_table(self):
        table = self.table_header_unknown
        table.setRowCount(0)
        for row, (key, value) in enumerate(self._header_unknown.items()):
            table.insertRow(row)
            key_item = QTableWidgetItem(str(key))
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, key_item)

            value_item = QTableWidgetItem(self._stringify_header_value(value))
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 1, value_item)

    def _value_for_known_key(self, key: str):
        if key in self._header_draft:
            return self._header_draft[key]
        if key in self._header_known:
            return self._header_known[key]
        return self._MISSING

    def _stringify_header_value(self, value):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        return str(value)

    def _on_known_header_item_changed(self, item: QTableWidgetItem):
        if self._suspend_header_signals:
            return
        if item.column() != 1:
            return

        row = item.row()
        key_item = self.table_header_known.item(row, 0)
        if not key_item:
            return
        key = key_item.text()

        has_existing_value = bool(item.data(self._HEADER_HAS_VALUE_ROLE))
        existing_value = item.data(self._HEADER_VALUE_ROLE)
        new_text = item.text()
        if has_existing_value:
            parsed = self._parse_scalar_value(new_text, existing_value)
        else:
            if new_text == "":
                self._set_draft_value(key, self._MISSING)
                return
            parsed = new_text
        self._set_draft_value(key, parsed)

    def _on_known_header_cell_double_clicked(self, row: int, column: int):
        if column != 1:
            return
        key_item = self.table_header_known.item(row, 0)
        if not key_item:
            return
        key = key_item.text()

        current = self._value_for_known_key(key)
        if current is self._MISSING:
            # Allow easy initialization for nested known fields.
            if key == "metadata":
                current = {}
            else:
                return

        if not isinstance(current, (dict, list)):
            return

        updated = self._open_json_value_dialog(key, current)
        if updated is self._MISSING:
            return
        self._set_draft_value(key, updated)

    def _open_json_value_dialog(self, key: str, current_value):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit JSON: {key}")
        dialog.resize(520, 360)
        layout = QVBoxLayout(dialog)

        editor = QPlainTextEdit(dialog)
        editor.setPlainText(json.dumps(current_value, indent=2, ensure_ascii=False))
        layout.addWidget(editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        while True:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return self._MISSING
            raw = editor.toPlainText().strip()
            try:
                value = json.loads(raw) if raw else None
            except Exception as exc:
                QMessageBox.warning(self, "Invalid JSON", f"Could not parse JSON:\n{exc}")
                continue
            if not isinstance(value, (dict, list)):
                QMessageBox.warning(self, "Invalid Type", "Value must be a JSON object or array.")
                continue
            return value

    def _parse_scalar_value(self, text: str, template):
        if isinstance(template, bool):
            lowered = text.strip().lower()
            if lowered in ("true", "1", "yes"):
                return True
            if lowered in ("false", "0", "no"):
                return False
            return template
        if isinstance(template, int) and not isinstance(template, bool):
            try:
                return int(text)
            except Exception:
                return template
        if isinstance(template, float):
            try:
                return float(text)
            except Exception:
                return template
        if template is None:
            return None if text.strip().lower() == "null" else text
        return text

    def _set_draft_value(self, key: str, value):
        baseline = self._header_known.get(key, self._MISSING)
        if value is self._MISSING:
            self._header_draft.pop(key, None)
        elif baseline is not self._MISSING and baseline == value:
            self._header_draft.pop(key, None)
        else:
            self._header_draft[key] = copy.deepcopy(value)

        self._suspend_header_signals = True
        self._populate_known_table()
        self._suspend_header_signals = False
        self.headerDraftChanged.emit(copy.deepcopy(self._header_draft))
