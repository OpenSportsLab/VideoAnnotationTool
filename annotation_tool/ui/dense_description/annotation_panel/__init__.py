import os

from PyQt6 import uic
from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QVBoxLayout, QWidget

from ui.localization.event_editor.annotation_table import AnnotationTableModel, AnnotationTableWidget
from utils import resource_path


class DenseTableModel(AnnotationTableModel):
    """
    Dense-description table model.
    Columns: Time, Lang, Description.
    """

    def __init__(self, annotations=None):
        super().__init__(annotations)
        self._headers = ["Time", "Lang", "Description"]

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

        if role in [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole]:
            if col == 0:
                return self._fmt_ms(item.get("position_ms", 0))
            if col == 1:
                return item.get("lang", "en")
            if col == 2:
                return item.get("text", "")

        return super().data(index, role)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        row = index.row()
        col = index.column()

        old_item = self._data[row]
        new_item = old_item.copy()
        value_str = str(value).strip()

        if col == 0:
            try:
                new_item["position_ms"] = self._parse_time_str(value_str)
            except ValueError:
                return False
        elif col == 1:
            new_item["lang"] = value_str
        elif col == 2:
            new_item["text"] = value_str

        if new_item != old_item:
            self._data[row] = new_item
            self.itemChanged.emit(old_item, new_item)
            return True

        return False


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
    Exposes `input_widget` and `table` APIs used by DenseEditorController.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(
            os.path.join("ui", "dense_description", "annotation_panel", "dense_annotation_panel.ui")
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

        self.table = AnnotationTableWidget(self.denseTableContainer)

        table_layout = self.denseTableContainer.layout()
        if table_layout is None:
            table_layout = QVBoxLayout(self.denseTableContainer)
            table_layout.setContentsMargins(0, 0, 0, 0)
            table_layout.setSpacing(0)
        table_layout.addWidget(self.table)

        # Swap in dense model and reconnect the table signal wiring.
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
        self.denseMainLayout.setStretch(4, 2)

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
