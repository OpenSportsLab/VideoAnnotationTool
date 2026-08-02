import os

from PyQt6 import uic
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from utils import resource_path


class DescriptionAnnotationPanel(QWidget):
    """
    Description annotation editor panel view loaded from Qt Designer UI.
    """
    captionTextChanged = pyqtSignal()
    inferenceRequested = pyqtSignal()
    inferenceConfirmRequested = pyqtSignal()
    inferenceRejectRequested = pyqtSignal()

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

        inference_row = QHBoxLayout()
        self.run_inference_button = QPushButton("Run Inference…", self)
        self.confirm_inference_button = QPushButton("Confirm", self)
        self.reject_inference_button = QPushButton("Reject", self)
        self.inference_status_label = QLabel("", self)
        self.inference_candidate_label = QLabel("", self)
        self.inference_candidate_label.setWordWrap(True)
        inference_row.addWidget(self.run_inference_button)
        inference_row.addWidget(self.confirm_inference_button)
        inference_row.addWidget(self.reject_inference_button)
        self.verticalLayout.addLayout(inference_row)
        self.verticalLayout.addWidget(self.inference_status_label)
        self.verticalLayout.addWidget(self.inference_candidate_label)
        self.run_inference_button.clicked.connect(self.inferenceRequested.emit)
        self.confirm_inference_button.clicked.connect(self.inferenceConfirmRequested.emit)
        self.reject_inference_button.clicked.connect(self.inferenceRejectRequested.emit)
        self.set_smart_inference_state(False)

    def set_smart_inference_state(self, active: bool, confidence: float = 0.0, model_id: str = ""):
        self.confirm_inference_button.setVisible(bool(active))
        self.reject_inference_button.setVisible(bool(active))
        if active:
            self.inference_status_label.setText(f"Smart prediction: {confidence * 100:.1f}% · {model_id}")
        else:
            self.inference_status_label.clear()
            self.inference_candidate_label.clear()

    def set_pending_prediction(self, candidate=None):
        active = isinstance(candidate, dict)
        self.confirm_inference_button.setText("Accept")
        self.reject_inference_button.setText("Reject")
        self.set_smart_inference_state(
            active,
            float(candidate.get("confidence_score", 0.0) or 0.0) if active else 0.0,
            str(candidate.get("inference_model_id") or "") if active else "",
        )
        self.inference_candidate_label.setText(
            f"Candidate: {candidate.get('text', '')}" if active else ""
        )

    def set_inference_loading(self, loading: bool):
        self.run_inference_button.setEnabled(not bool(loading))

    def set_caption_text(self, text: str):
        self.caption_edit.setPlainText(text or "")

    def get_caption_text(self) -> str:
        return self.caption_edit.toPlainText()

    def set_caption_editor_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self.caption_edit.setEnabled(enabled)
        self.setEnabled(enabled)


__all__ = ["DescriptionAnnotationPanel"]
