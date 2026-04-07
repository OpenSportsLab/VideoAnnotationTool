import os

from PyQt6 import uic
from PyQt6.QtCore import QAbstractTableModel, QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QMenu, QPushButton, QTableView, QWidget

from utils import resource_path


def _format_mmss_msec(ms: int) -> str:
    ms = max(0, int(ms))
    seconds = ms // 1000
    minutes = seconds // 60
    return f"{minutes:02}:{seconds % 60:02}.{ms % 1000:03}"


def _parse_time_to_ms(text: str, fallback: int = 0) -> int:
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


class DenseTableModel(QAbstractTableModel):
    """
    Dense-description table model.
    Columns: Time, Lang, Description.
    """

    itemChanged = pyqtSignal(dict, dict)

    def __init__(self, annotations=None):
        super().__init__()
        self._data = annotations or []
        self._headers = ["Time", "Lang", "Description"]

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
        col = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 0:
                return _format_mmss_msec(item.get("position_ms", 0))
            if col == 1:
                return item.get("lang", "en")
            if col == 2:
                return item.get("text", "")

        if role == Qt.ItemDataRole.UserRole:
            return item

        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        row = index.row()
        col = index.column()

        old_item = self._data[row]
        new_item = old_item.copy()
        value_str = str(value).strip()

        if col == 0:
            new_item["position_ms"] = _parse_time_to_ms(value_str, old_item.get("position_ms", 0))
        elif col == 1:
            new_item["lang"] = value_str
        elif col == 2:
            new_item["text"] = value_str
        else:
            return False

        if new_item == old_item:
            return False

        self._data[row] = new_item
        self.itemChanged.emit(old_item, new_item)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
        return True

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


class _DenseTableAdapter(QObject):
    """
    Adapter exposing the previous `table` API expected by DenseEditorController.
    Uses standard widgets from dense_annotation_panel.ui.
    """

    annotationSelected = pyqtSignal(int)
    annotationModified = pyqtSignal(dict, dict)
    annotationDeleted = pyqtSignal(dict)
    updateTimeForSelectedRequested = pyqtSignal(dict)

    def __init__(
        self,
        table_view: QTableView,
        *,
        edit_label: QLabel | None = None,
        set_time_btn: QPushButton | None = None,
        list_label: QLabel | None = None,
        parent=None,
    ):
        super().__init__(parent)

        self.edit_lbl = edit_label
        self.btn_set_time = set_time_btn
        self.list_lbl = list_label
        self.table = table_view

        self.table.setProperty("class", "annotation_table")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )

        self.model = DenseTableModel()
        self.model.itemChanged.connect(self.annotationModified.emit)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        selection_model = self.table.selectionModel()
        if selection_model:
            selection_model.selectionChanged.connect(self._on_selection_changed)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        if self.btn_set_time is not None:
            self.btn_set_time.setEnabled(False)
            self.btn_set_time.clicked.connect(self._on_set_time_clicked)

    def set_data(self, annotations):
        self.model.set_annotations(annotations)

    def _on_selection_changed(self, selected, deselected):
        indexes = selected.indexes()
        has_selection = bool(indexes)

        if self.btn_set_time is not None:
            self.btn_set_time.setEnabled(has_selection)

        if not has_selection:
            return

        row = indexes[0].row()
        item = self.model.get_annotation_at(row)
        if item:
            self.annotationSelected.emit(item.get("position_ms", 0))

    def _on_set_time_clicked(self):
        if self.btn_set_time is None:
            return

        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return

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

        menu = QMenu(self.table)
        act_delete = menu.addAction("Delete Event")
        selected_action = menu.exec(self.table.mapToGlobal(pos))

        if selected_action == act_delete:
            self.annotationDeleted.emit(item)


class _DenseInputAdapter(QObject):
    """
    Small adapter to preserve the old input-widget API used by controllers.
    """

    descriptionSubmitted = pyqtSignal(str)

    def __init__(self, time_label, text_editor, submit_btn):
        super().__init__()
        self._time_label = time_label
        self.text_editor = text_editor
        self._submit_btn = submit_btn
        self._submit_btn.clicked.connect(self._on_submit)

    def update_time(self, time_str: str):
        self._time_label.setText(f"Current Time: {time_str}")

    def set_text(self, text: str):
        self.text_editor.setPlainText(text)

    def _on_submit(self):
        text = self.text_editor.toPlainText().strip()
        if text:
            self.descriptionSubmitted.emit(text)


class DenseAnnotationPanel(QWidget):
    """
    Dense annotation editor panel view loaded from Qt Designer UI.
    Uses only standard widgets in .ui and adapter objects in Python.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(
            os.path.join("ui", "dense_description", "dense_annotation_panel.ui")
        )
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load DenseAnnotationPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        # Keep existing QSS hooks used by style.qss.
        self.denseCurrentTimeLabel.setProperty("class", "dense_time_display")
        self.denseDescriptionEdit.setProperty("class", "dense_desc_editor")
        self.denseConfirmBtn.setProperty("class", "dense_confirm_btn")

        self.input_widget = _DenseInputAdapter(
            time_label=self.denseCurrentTimeLabel,
            text_editor=self.denseDescriptionEdit,
            submit_btn=self.denseConfirmBtn,
        )

        self.table = _DenseTableAdapter(
            self.denseEventsTableView,
            edit_label=self.denseEditLabel,
            set_time_btn=self.denseSetCurrentTimeBtn,
            list_label=self.denseEventsListLabel,
            parent=self,
        )

        # Swap in dense model and reconnect table signal wiring.
        self.dense_model = DenseTableModel()
        self.table.model = self.dense_model
        self.table.table.setModel(self.dense_model)
        self.dense_model.itemChanged.connect(self.table.annotationModified.emit)

        selection_model = self.table.table.selectionModel()
        if selection_model:
            selection_model.selectionChanged.connect(self.table._on_selection_changed)

        self.table.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )

        header = self.table.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)

        # Top editor + bottom table ratio.
        self.denseMainLayout.setStretch(2, 1)
        self.denseMainLayout.setStretch(7, 2)

        QTimer.singleShot(0, self._apply_dense_column_ratio)

    def _apply_dense_column_ratio(self):
        """
        Keep [Time, Lang, Description] widths in a stable 2:1:4 ratio.
        """
        view = self.table.table
        width = view.viewport().width()
        if width <= 0:
            return

        unit = max(20, width // 7)  # 2 + 1 + 4
        col0 = unit * 2
        col1 = unit
        col2 = max(80, width - col0 - col1)

        view.setColumnWidth(0, col0)
        view.setColumnWidth(1, col1)
        view.setColumnWidth(2, col2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_dense_column_ratio()


__all__ = ["DenseAnnotationPanel"]
