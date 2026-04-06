import os

from PyQt6 import uic
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from utils import resource_path


class DescriptionAnnotationPanel(QWidget):
    """
    Description annotation editor panel view loaded from Qt Designer UI.
    """

    confirm_clicked = pyqtSignal()
    clear_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(
            os.path.join("ui", "description", "annotation_panel", "description_annotation_panel.ui")
        )
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load DescriptionAnnotationPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        # Keep existing runtime API expected by controllers/tests.
        self.caption_edit = self.descCaptionEdit
        self.confirm_btn = self.descConfirmBtn
        self.clear_btn = self.descClearBtn

        # Keep Clear/Confirm width ratio from the previous hand-built widget.
        self.buttonsLayout.setStretch(0, 1)
        self.buttonsLayout.setStretch(1, 2)

        self.confirm_btn.clicked.connect(self.confirm_clicked.emit)
        self.clear_btn.clicked.connect(self.clear_clicked.emit)


__all__ = ["DescriptionAnnotationPanel"]
