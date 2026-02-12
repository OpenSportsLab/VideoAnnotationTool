from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QAbstractItemView, QHeaderView
)
from PyQt6.QtCore import Qt, QTimer

from .desc_input_widget import DenseDescriptionInputWidget
from .dense_table import DenseTableModel, AnnotationTableWidget


class DenseRightPanel(QWidget):
    """
    Right Panel for Dense Description Mode.
    Contains Undo/Redo, Input Field, and Description Table.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # This panel has a fixed width; column ratio will be computed within this width.
        self.setFixedWidth(400)

        layout = QVBoxLayout(self)

        # 1. Header with Undo/Redo (Reusing Localization Style)
        header_layout = QHBoxLayout()
        self.undo_btn = QPushButton("Undo")
        self.redo_btn = QPushButton("Redo")

        header_layout.addWidget(QLabel("<b>Dense Annotation</b>"))
        header_layout.addStretch()
        header_layout.addWidget(self.undo_btn)
        header_layout.addWidget(self.redo_btn)
        layout.addLayout(header_layout)

        # 2. Top: Input Widget
        self.input_widget = DenseDescriptionInputWidget()
        layout.addWidget(self.input_widget, 1)

        # 3. Bottom: Table Widget
        self.table = AnnotationTableWidget()

        # [CRITICAL FIX] Swap Model and Reconnect Signals
        # ---------------------------------------------------------
        # 1. Create and set the specific Dense model
        self.dense_model = DenseTableModel()
        self.table.model = self.dense_model          # Update python reference
        self.table.table.setModel(self.dense_model)  # Update QTableView

        # 2. Reconnect editing signal (Fix: "Cannot modify")
        self.dense_model.itemChanged.connect(self.table.annotationModified.emit)

        # 3. Reconnect selection signal (Fix: "Timeline does not jump")
        selection_model = self.table.table.selectionModel()
        selection_model.selectionChanged.connect(self.table._on_selection_changed)

        # 4. Enforce edit triggers
        self.table.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed |
            QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        # ---------------------------------------------------------

        # ---- Column width ratio: 2 : 1 : 4 ----
        # We enforce fixed section sizes so the ratio is stable and not overridden by content.
        header = self.table.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)

        # Apply ratio after the widget is laid out (viewport width becomes valid).
        QTimer.singleShot(0, self._apply_dense_column_ratio)

        layout.addWidget(self.table, 2)

    def _apply_dense_column_ratio(self):
        """
        Apply a fixed 2:1:4 width ratio for [Time, Lang, Description].
        This uses the table viewport width (actual drawable area).
        """
        view = self.table.table  # QTableView
        w = view.viewport().width()

        if w <= 0:
            return

        # Total parts: 2 + 1 + 4 = 7
        total_parts = 7
        unit = max(20, w // total_parts)  # Add a lower bound to avoid too narrow columns

        c0 = unit * 2                       # Time
        c1 = unit * 1                       # Lang
        c2 = max(80, w - c0 - c1)           # Description takes the remaining width (with min width)

        view.setColumnWidth(0, c0)
        view.setColumnWidth(1, c1)
        view.setColumnWidth(2, c2)

    def resizeEvent(self, event):
        """
        Re-apply column ratio on resize to keep [Time, Lang, Description] as 2:1:4.
        """
        super().resizeEvent(event)
        self._apply_dense_column_ratio()
