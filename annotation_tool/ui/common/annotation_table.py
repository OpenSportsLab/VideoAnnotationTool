from PyQt6.QtCore import QAbstractTableModel, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)


class AnnotationTableModel(QAbstractTableModel):
    """
    Shared event table model for time/head/label rows.
    """

    itemChanged = pyqtSignal(dict, dict)

    def __init__(self, annotations=None):
        super().__init__()
        self._data = annotations or []
        self._headers = ["Time", "Head", "Label"]

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return len(self._headers)

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        item = self._data[row]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            col = index.column()
            if col == 0:
                return self._fmt_ms(item.get("position_ms", 0))
            if col == 1:
                return item.get("head", "").replace("_", " ")
            if col == 2:
                return item.get("label", "").replace("_", " ")
        elif role == Qt.ItemDataRole.UserRole:
            return item

        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        row = index.row()
        col = index.column()

        old_item = self._data[row]
        new_item = old_item.copy()
        text_val = str(value).strip()

        if col == 0:
            try:
                ms = self._parse_time_str(text_val)
                new_item["position_ms"] = ms
            except ValueError:
                return False
        elif col == 1:
            new_item["head"] = text_val
        elif col == 2:
            new_item["label"] = text_val

        if new_item != old_item:
            self.itemChanged.emit(old_item, new_item)
            return True

        return False

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._headers[section]
        return None

    def set_annotations(self, annotations):
        self.beginResetModel()
        self._data = annotations
        self.endResetModel()

    def get_annotation_at(self, row):
        if 0 <= row < len(self._data):
            return self._data[row]
        return None

    def _fmt_ms(self, ms):
        seconds = ms // 1000
        minutes = seconds // 60
        return f"{minutes:02}:{seconds % 60:02}.{ms % 1000:03}"

    def _parse_time_str(self, time_str):
        if not time_str:
            return 0
        parts = time_str.split(":")
        total_seconds = 0.0
        if len(parts) == 3:  # HH:MM:SS.mmm
            total_seconds += float(parts[0]) * 3600
            total_seconds += float(parts[1]) * 60
            total_seconds += float(parts[2])
        elif len(parts) == 2:  # MM:SS.mmm
            total_seconds += float(parts[0]) * 60
            total_seconds += float(parts[1])
        elif len(parts) == 1:  # SS.mmm
            total_seconds += float(parts[0])
        return int(total_seconds * 1000)


class AnnotationTableWidget(QWidget):
    """
    Shared table surface for event browsing/editing.
    """

    annotationSelected = pyqtSignal(int)
    annotationModified = pyqtSignal(dict, dict)
    annotationDeleted = pyqtSignal(dict)
    updateTimeForSelectedRequested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.edit_lbl = QLabel("Edit Annotation")
        self.edit_lbl.setProperty("class", "panel_header_lbl")
        layout.addWidget(self.edit_lbl)

        self.btn_set_time = QPushButton("Set to Current Video Time")
        self.btn_set_time.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_set_time.setEnabled(False)
        self.btn_set_time.clicked.connect(self._on_set_time_clicked)
        layout.addWidget(self.btn_set_time)

        self.list_lbl = QLabel("Events List")
        self.list_lbl.setProperty("class", "panel_header_lbl")
        layout.addWidget(self.list_lbl)

        self.table = QTableView()
        self.table.setProperty("class", "annotation_table")

        self.model = AnnotationTableModel()
        self.model.itemChanged.connect(self.annotationModified.emit)

        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        layout.addWidget(self.table)

        self.current_schema = {}

    def set_data(self, annotations):
        self.model.set_annotations(annotations)

    def set_schema(self, schema):
        self.current_schema = schema

    def _on_selection_changed(self, selected, deselected):
        indexes = selected.indexes()
        if indexes:
            self.btn_set_time.setEnabled(True)
            row = indexes[0].row()
            item = self.model.get_annotation_at(row)
            if item:
                self.annotationSelected.emit(item.get("position_ms", 0))
        else:
            self.btn_set_time.setEnabled(False)

    def _on_set_time_clicked(self):
        indexes = self.table.selectionModel().selectedRows()
        if indexes:
            row = indexes[0].row()
            item = self.model.get_annotation_at(row)
            if item:
                self.updateTimeForSelectedRequested.emit(item)

    def _show_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        item = self.model.get_annotation_at(row)
        if not item:
            return

        menu = QMenu(self)
        act_delete = menu.addAction("Delete Event")
        selected_action = menu.exec(self.table.mapToGlobal(pos))

        if selected_action == act_delete:
            self.annotationDeleted.emit(item)

