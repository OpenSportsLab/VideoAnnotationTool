"""One decision for the classes returned by a localization inference run."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class LocalizationClassMappingDialog(QDialog):
    SKIP_TEXT = "Skip Prediction"

    def __init__(self, predicted_classes, head, head_labels, existing_heads, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Map Predicted Classes")
        self.setMinimumWidth(530)
        self._predicted_classes = list(predicted_classes)
        self._existing_heads = {str(name).casefold() for name in existing_heads}
        self._combos = {}

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"Some predicted classes are not defined in '{head}'. "
            "Choose a class in this head for each prediction, or create a new task head."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.map_radio = QRadioButton(f"Map to '{head}'")
        self.map_radio.setChecked(True)
        layout.addWidget(self.map_radio)

        self.mapping_table = QTableWidget(len(self._predicted_classes), 2)
        self.mapping_table.setHorizontalHeaderLabels(["Predicted class", "Class in head"])
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.mapping_table.setMinimumHeight(min(320, 64 + 34 * len(self._predicted_classes)))
        for row, predicted in enumerate(self._predicted_classes):
            item = QTableWidgetItem(predicted)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(predicted)
            self.mapping_table.setItem(row, 0, item)
            combo = QComboBox(self.mapping_table)
            combo.addItem(self.SKIP_TEXT, None)
            for label in head_labels:
                combo.addItem(label, label)
            if predicted in head_labels:
                combo.setCurrentIndex(head_labels.index(predicted) + 1)
            self.mapping_table.setCellWidget(row, 1, combo)
            self._combos[predicted] = combo
        layout.addWidget(self.mapping_table)

        self.new_head_radio = QRadioButton("Create a new task head with all predicted classes")
        layout.addWidget(self.new_head_radio)
        name_row = QWidget(self)
        name_layout = QHBoxLayout(name_row)
        name_layout.setContentsMargins(24, 0, 0, 0)
        name_layout.addWidget(QLabel("Head name:"))
        self.new_head_name = QLineEdit(self._suggest_head_name(head))
        name_layout.addWidget(self.new_head_name)
        layout.addWidget(name_row)

        self.validation_label = QLabel("")
        self.validation_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.validation_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        layout.addWidget(self.buttons)

        self.map_radio.toggled.connect(self._update_state)
        self.new_head_radio.toggled.connect(self._update_state)
        self.new_head_name.textChanged.connect(self._update_state)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self._update_state()

    def _suggest_head_name(self, head):
        base = f"{head}_inference"
        candidate = base
        suffix = 2
        while candidate.casefold() in self._existing_heads:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def _update_state(self):
        creating = self.new_head_radio.isChecked()
        self.mapping_table.setEnabled(not creating)
        self.new_head_name.setEnabled(creating)
        name = self.new_head_name.text().strip()
        if creating and not name:
            message = "Enter a task head name."
        elif creating and name.casefold() in self._existing_heads:
            message = "A task head with this name already exists."
        else:
            message = ""
        self.validation_label.setText(message)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not message)

    def accept(self):
        self._update_state()
        if self.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled():
            super().accept()

    def decision(self):
        """Return (target head name or None, class mapping).

        A non-None head name means the caller should create that head. Mapping
        values are either a destination class or None to skip that class.
        """
        if self.new_head_radio.isChecked():
            canonical = {}
            for predicted in self._predicted_classes:
                canonical.setdefault(predicted.casefold(), predicted)
            return self.new_head_name.text().strip(), {
                predicted: canonical[predicted.casefold()]
                for predicted in self._predicted_classes
            }
        return None, {
            predicted: self._combos[predicted].currentData()
            for predicted in self._predicted_classes
        }
