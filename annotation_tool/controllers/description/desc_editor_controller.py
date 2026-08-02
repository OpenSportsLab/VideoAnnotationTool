import copy

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox


class DescEditorController(QObject):
    """
    Description editor controller.
    Owns caption editor signal wiring, text refresh, save, and clear/reset behavior.
    """

    clearMarkersRequested = pyqtSignal()
    captionsUpdateRequested = pyqtSignal(str, object)
    inferenceRunRequested = pyqtSignal(str, object)
    pendingPredictionsChanged = pyqtSignal(object)

    def __init__(self, description_panel):
        super().__init__()
        self.description_panel = description_panel
        self.current_sample_id = ""
        self.current_action_path = None
        self._current_sample_snapshot = {}
        self._suspend_autosave = False
        self._active_mode_index = 0
        self._autosave_timer = QTimer(self.description_panel)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(250)
        self._autosave_timer.timeout.connect(self.save_current_annotation)
        self._pre_smart_captions = None
        self._pending_predictions = {}

    def setup_connections(self):
        """Connect Description editor UI signals to controller actions."""
        self.description_panel.captionTextChanged.connect(self._on_caption_text_changed)
        self.description_panel.inferenceConfirmRequested.connect(self.confirm_smart_inference)
        self.description_panel.inferenceRejectRequested.connect(self.reject_smart_inference)

    def on_mode_changed(self, index: int):
        self._active_mode_index = index
        if self._is_active_mode():
            self.clearMarkersRequested.emit()

    def request_inference(self):
        if not self.current_sample_id:
            QMessageBox.warning(
                self.description_panel, "Inference", "Please select a sample first."
            )
            return
        self.inferenceRunRequested.emit("description", {"language": "en"})

    def reset_ui(self):
        """Reset the Description editor UI for project clear/close flows."""
        self._autosave_timer.stop()
        self.current_sample_id = ""
        self.current_action_path = None
        self._current_sample_snapshot = {}
        self._set_editor_text("")
        self.description_panel.set_caption_editor_enabled(False)
        self._pre_smart_captions = None
        self._pending_predictions.clear()
        self.pendingPredictionsChanged.emit(set())
        self.description_panel.set_smart_inference_state(False)

    def on_selected_sample_changed(self, sample):
        """
        Refresh Description editor content for selected tree item.
        """
        self._pre_smart_captions = None
        if not isinstance(sample, dict):
            self._autosave_timer.stop()
            self.current_sample_id = ""
            self.current_action_path = None
            self._set_editor_text("")
            self._current_sample_snapshot = {}
            self.description_panel.set_caption_editor_enabled(False)
            if self._is_active_mode():
                self.clearMarkersRequested.emit()
            return

        self.current_sample_id = str(sample.get("id") or "")
        if not self.current_sample_id:
            self._autosave_timer.stop()
            self.current_action_path = None
            self._set_editor_text("")
            self._current_sample_snapshot = {}
            self.description_panel.set_caption_editor_enabled(False)
            if self._is_active_mode():
                self.clearMarkersRequested.emit()
            return

        self._current_sample_snapshot = copy.deepcopy(sample)
        self.current_action_path = self._extract_primary_path(sample)
        self.description_panel.set_caption_editor_enabled(True)
        if self._is_active_mode():
            self.clearMarkersRequested.emit()

        self._load_and_format_text(sample)
        pending = self._pending_predictions.get(self.current_sample_id)
        if pending:
            self.description_panel.set_pending_prediction(pending)
            return
        smart = next(
            (caption for caption in sample.get("captions", []) if isinstance(caption, dict) and "confidence_score" in caption),
            None,
        )
        self.description_panel.set_smart_inference_state(
            bool(smart),
            float(smart.get("confidence_score", 0.0) or 0.0) if smart else 0.0,
            str(smart.get("inference_model_id") or "") if smart else "",
        )

    def apply_shared_inference_result(self, result, context=None):
        if not result.items:
            return
        for item in result.items:
            captions = item.get("captions")
            candidate = copy.deepcopy(captions[0]) if isinstance(captions, list) and captions else None
            sample_id = str(item.get("sample_id") or "")
            if not isinstance(candidate, dict) or not sample_id or not str(candidate.get("text") or "").strip():
                continue
            candidate.setdefault("lang", "en")
            candidate["confidence_score"] = float(candidate.get("confidence_score", 1.0) or 0.0)
            candidate["inference_model_id"] = result.model_id
            self._pending_predictions[sample_id] = candidate
        if self.current_sample_id in self._pending_predictions:
            self.description_panel.set_pending_prediction(self._pending_predictions[self.current_sample_id])
        self.pendingPredictionsChanged.emit(set(self._pending_predictions))

    def confirm_smart_inference(self):
        pending = self._pending_predictions.pop(self.current_sample_id, None)
        if pending is not None:
            accepted = copy.deepcopy(pending)
            accepted.pop("confidence_score", None)
            accepted.pop("inference_model_id", None)
            captions = [accepted]
            if captions != self._current_sample_snapshot.get("captions", []):
                self.captionsUpdateRequested.emit(self.current_sample_id, captions)
                self._current_sample_snapshot["captions"] = copy.deepcopy(captions)
                self._load_and_format_text(self._current_sample_snapshot)
            self.description_panel.set_pending_prediction(None)
            self.pendingPredictionsChanged.emit(set(self._pending_predictions))
            return
        captions = copy.deepcopy(self._current_sample_snapshot.get("captions", []))
        changed = False
        for caption in captions:
            if not isinstance(caption, dict) or "confidence_score" not in caption:
                continue
            caption.pop("confidence_score", None)
            caption.pop("inference_model_id", None)
            changed = True
        if not changed or not self.current_sample_id:
            return
        self.captionsUpdateRequested.emit(self.current_sample_id, captions)
        self._current_sample_snapshot["captions"] = copy.deepcopy(captions)
        self._pre_smart_captions = None
        self.description_panel.set_smart_inference_state(False)

    def reject_smart_inference(self):
        if self._pending_predictions.pop(self.current_sample_id, None) is not None:
            self.description_panel.set_pending_prediction(None)
            self.pendingPredictionsChanged.emit(set(self._pending_predictions))
            return
        if not self.current_sample_id:
            return
        captions = copy.deepcopy(self._pre_smart_captions if self._pre_smart_captions is not None else [])
        self.captionsUpdateRequested.emit(self.current_sample_id, captions)
        self._current_sample_snapshot["captions"] = copy.deepcopy(captions)
        self._pre_smart_captions = None
        self._load_and_format_text(self._current_sample_snapshot)
        self.description_panel.set_smart_inference_state(False)

    def _load_and_format_text(self, data):
        """
        Format text for display.
        - If captions contain "question", show Q/A blocks.
        - Otherwise show caption text as-is.
        - If no captions, fallback to metadata.questions template.
        """
        captions = data.get("captions", [])
        formatted_blocks = []

        if captions:
            for cap in captions:
                text = cap.get("text", "")
                question = cap.get("question", "")
                if question:
                    formatted_blocks.append(f'Q: "{question}"\nA: "{text}"')
                else:
                    formatted_blocks.append(text)
            full_text = "\n\n".join(formatted_blocks)
        else:
            metadata = data.get("metadata", {})
            for question in metadata.get("questions", []):
                formatted_blocks.append(f'Q: "{question}"\nA: ""')
            full_text = "\n\n".join(formatted_blocks)

        self._set_editor_text(full_text)

    def _set_editor_text(self, text: str):
        self._suspend_autosave = True
        try:
            self.description_panel.set_caption_text(text)
        finally:
            self._suspend_autosave = False

    def _on_caption_text_changed(self):
        if self._suspend_autosave:
            return
        if not self.current_sample_id:
            return
        if self._pending_predictions.pop(self.current_sample_id, None) is not None:
            self.description_panel.set_pending_prediction(None)
        self._autosave_timer.start()

    def save_current_annotation(self):
        """
        Persist current Description editor text into the selected sample captions.
        """
        if not self.current_sample_id:
            return False

        text_content = self.description_panel.get_caption_text()
        old_captions = copy.deepcopy(self._current_sample_snapshot.get("captions", []))
        new_captions = [{"lang": "en", "text": text_content}]
        if old_captions == new_captions:
            return False

        self.captionsUpdateRequested.emit(
            self.current_sample_id,
            copy.deepcopy(new_captions),
        )
        self._current_sample_snapshot["captions"] = copy.deepcopy(new_captions)
        return True

    def _is_active_mode(self) -> bool:
        return self._active_mode_index == 2

    @staticmethod
    def _extract_primary_path(sample: dict):
        inputs = sample.get("inputs")
        if isinstance(inputs, list):
            for input_item in inputs:
                if isinstance(input_item, dict):
                    path = input_item.get("path")
                    if path:
                        return path
        return None
