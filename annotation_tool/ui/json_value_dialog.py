"""Shared modal editor for nested manifest and annotation JSON values."""

import json

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)


def _reject_nonfinite_constant(value):
    raise ValueError(f"{value} is not a valid JSON number.")


class JsonValueDialog(QDialog):
    def __init__(self, key, current_value, parent=None, *, objects_only=False, allow_empty=False):
        super().__init__(parent)
        self.setWindowTitle(f"Edit JSON: {key}")
        self.resize(520, 360)
        self._objects_only = objects_only
        self._allow_empty = allow_empty
        self.value = None

        layout = QVBoxLayout(self)
        self.editor = QPlainTextEdit(self)
        self.editor.setPlainText(json.dumps(current_value, indent=2, ensure_ascii=False))
        layout.addWidget(self.editor)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def accept(self):
        try:
            raw = self.editor.toPlainText()
            if self._allow_empty and not raw.strip():
                value = {}
            else:
                value = json.loads(raw, parse_constant=_reject_nonfinite_constant)
            # Python accepts NaN/Infinity and overflowing JSON numbers by default.
            # Check nested values too before allowing them into the document.
            json.dumps(value, allow_nan=False)
        except (ValueError, OverflowError) as exc:
            QMessageBox.warning(self, "Invalid JSON", f"Could not parse valid JSON:\n{exc}")
            return

        allowed_types = (dict,) if self._objects_only else (dict, list)
        if not isinstance(value, allowed_types):
            expected = "a JSON object (dictionary)" if self._objects_only else "a JSON object or array"
            QMessageBox.warning(self, "Invalid Type", f"Value must be {expected}.")
            return

        self.value = value
        super().accept()
