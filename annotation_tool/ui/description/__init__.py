import os

from PyQt6 import uic
from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import QLabel, QListWidgetItem, QWidget

from ui.inference_review_bar import InferenceReviewBar
from utils import resource_path


class DescriptionAnnotationPanel(QWidget):
    """
    Description annotation editor panel view loaded from Qt Designer UI.
    """
    captionTextChanged = pyqtSignal()
    captionMetadataChanged = pyqtSignal()
    captionSelectionChanged = pyqtSignal(int)
    captionAddRequested = pyqtSignal()
    captionDeleteRequested = pyqtSignal()
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
        self.descVariantEdit.textChanged.connect(self.captionMetadataChanged.emit)
        self.descLanguageEdit.textChanged.connect(self.captionMetadataChanged.emit)
        self.descCaptionsList.currentRowChanged.connect(
            self.captionSelectionChanged.emit
        )
        self.descAddCaptionBtn.clicked.connect(self.captionAddRequested.emit)
        self.descDeleteCaptionBtn.clicked.connect(self.captionDeleteRequested.emit)

        self.inference_candidate_label = QLabel("", self)
        self.inference_candidate_label.setWordWrap(True)
        self.verticalLayout.addWidget(self.inference_candidate_label)
        self.inference_review_bar = InferenceReviewBar(self)
        self.verticalLayout.addWidget(self.inference_review_bar)
        self.confirm_inference_button = self.inference_review_bar.accept_button
        self.reject_inference_button = self.inference_review_bar.reject_button
        self.inference_status_label = self.inference_review_bar.status_label
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

    def set_caption_text(self, text: str):
        self.caption_edit.setPlainText(text or "")

    def get_caption_text(self) -> str:
        return self.caption_edit.toPlainText()

    def set_captions(self, captions, selected_row: int = -1):
        blockers = (QSignalBlocker(self.descCaptionsList),)
        self.descCaptionsList.clear()
        for index, caption in enumerate(captions or []):
            item = QListWidgetItem(self._caption_summary(caption, index))
            item.setToolTip(
                str(caption.get("text", "")) if isinstance(caption, dict) else ""
            )
            self.descCaptionsList.addItem(item)
        if 0 <= int(selected_row) < self.descCaptionsList.count():
            self.descCaptionsList.setCurrentRow(int(selected_row))
        else:
            self.descCaptionsList.setCurrentRow(-1)
        del blockers

    def update_caption_summary(self, row: int, caption):
        item = self.descCaptionsList.item(int(row))
        if item is None:
            return
        item.setText(self._caption_summary(caption, int(row)))
        item.setToolTip(
            str(caption.get("text", "")) if isinstance(caption, dict) else ""
        )

    def get_selected_caption_index(self) -> int:
        return self.descCaptionsList.currentRow()

    def set_caption_fields(
        self, *, variant: str = "", lang: str = "", text: str = ""
    ):
        blockers = (
            QSignalBlocker(self.descVariantEdit),
            QSignalBlocker(self.descLanguageEdit),
            QSignalBlocker(self.caption_edit),
        )
        self.descVariantEdit.setText(variant or "")
        self.descLanguageEdit.setText(lang or "")
        self.caption_edit.setPlainText(text or "")
        del blockers

    def get_caption_fields(self) -> dict:
        return {
            "variant": self.descVariantEdit.text(),
            "lang": self.descLanguageEdit.text(),
            "text": self.caption_edit.toPlainText(),
        }

    def set_caption_detail_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self.captionDetailWidget.setEnabled(enabled)
        self.descDeleteCaptionBtn.setEnabled(enabled)

    def set_caption_editor_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self.descCaptionsList.setEnabled(enabled)
        self.descAddCaptionBtn.setEnabled(enabled)
        if not enabled:
            self.set_caption_detail_enabled(False)

    @staticmethod
    def _caption_summary(caption, index: int) -> str:
        if not isinstance(caption, dict):
            return f"Caption {index + 1} · Unsupported entry"
        variant = str(caption.get("variant") or "").strip()
        lang = str(caption.get("lang") or "").strip()
        text = " ".join(str(caption.get("text") or "").split())
        preview = text if len(text) <= 90 else f"{text[:87]}..."
        identity = " · ".join(part for part in (variant, lang) if part)
        prefix = identity or f"Caption {index + 1}"
        return f"{prefix} — {preview or '(empty)'}"


__all__ = ["DescriptionAnnotationPanel"]
