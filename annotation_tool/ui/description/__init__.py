import os

from PyQt6 import uic
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLabel, QWidget

from ui.inference_review_bar import InferenceReviewBar
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

        self.inference_candidate_label = QLabel("", self)
        self.inference_candidate_label.setWordWrap(True)
        self.verticalLayout.addWidget(self.inference_candidate_label)
        self.inference_review_bar = InferenceReviewBar(self)
        self.verticalLayout.addWidget(self.inference_review_bar)
        self.run_inference_button = self.inference_review_bar.run_button
        self.confirm_inference_button = self.inference_review_bar.accept_button
        self.reject_inference_button = self.inference_review_bar.reject_button
        self.inference_status_label = self.inference_review_bar.status_label
        self.inference_review_bar.runRequested.connect(self.inferenceRequested.emit)
        self.inference_review_bar.acceptRequested.connect(self.inferenceConfirmRequested.emit)
        self.inference_review_bar.rejectRequested.connect(self.inferenceRejectRequested.emit)
        self.set_smart_inference_state(False)

    def set_smart_inference_state(self, active: bool, confidence: float = 0.0, model_id: str = ""):
        self.inference_review_bar.set_review_actions_visible(bool(active))
        if active:
            self.inference_review_bar.set_status(
                f"Pending prediction · {confidence * 100:.1f}% · {model_id}"
            )
        else:
            self.inference_review_bar.set_status()
            self.inference_candidate_label.clear()

    def set_pending_prediction(self, candidate=None):
        active = isinstance(candidate, dict)
        self.set_smart_inference_state(
            active,
            float(candidate.get("confidence_score", 0.0) or 0.0) if active else 0.0,
            str(candidate.get("inference_model_id") or "") if active else "",
        )
        self.inference_candidate_label.setText(
            f"Candidate: {candidate.get('text', '')}" if active else ""
        )

    def set_inference_loading(self, loading: bool):
        self.inference_review_bar.set_running(loading)

    def set_caption_text(self, text: str):
        self.caption_edit.setPlainText(text or "")

    def get_caption_text(self) -> str:
        return self.caption_edit.toPlainText()

    def set_caption_editor_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self.caption_edit.setEnabled(enabled)
        self.setEnabled(enabled)


__all__ = ["DescriptionAnnotationPanel"]
