import os

from PyQt6 import uic
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from utils import resource_path


class DescriptionAnnotationPanel(QWidget):
    """
    Description annotation editor panel view loaded from Qt Designer UI.
    """
    captionTextChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(
            os.path.join("ui", "description", "description_annotation_panel.ui")
        )
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load DescriptionAnnotationPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        # Keep existing runtime API expected by controllers/tests.
        self.caption_edit = self.descCaptionEdit
        self.caption_edit.textChanged.connect(self.captionTextChanged.emit)

    def set_caption_text(self, text: str):
        self.caption_edit.setPlainText(text or "")

    def get_caption_text(self) -> str:
        return self.caption_edit.toPlainText()

    def set_caption_editor_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self.caption_edit.setEnabled(enabled)
        self.setEnabled(enabled)


__all__ = ["DescriptionAnnotationPanel"]
