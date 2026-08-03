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
        self._selected_caption_index = -1
        self._suspend_autosave = False
        self._active_mode_index = 0
        self._autosave_timer = QTimer(self.description_panel)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(250)
        self._autosave_timer.timeout.connect(self.save_current_annotation)
        self._pending_predictions = {}

    def setup_connections(self):
        """Connect Description editor UI signals to controller actions."""
        self.description_panel.captionTextChanged.connect(self._on_caption_text_changed)
        self.description_panel.captionMetadataChanged.connect(self._on_caption_text_changed)
        self.description_panel.captionSelectionChanged.connect(
            self._on_caption_selection_changed
        )
        self.description_panel.captionAddRequested.connect(self.add_caption)
        self.description_panel.captionDeleteRequested.connect(self.delete_selected_caption)
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
        self._selected_caption_index = -1
        self.description_panel.set_captions([], -1)
        self._set_editor_fields()
        self.description_panel.set_caption_editor_enabled(False)
        self._pending_predictions.clear()
        self.pendingPredictionsChanged.emit(set())
        self.description_panel.set_smart_inference_state(False)

    def on_selected_sample_changed(self, sample):
        """
        Refresh Description editor content for selected tree item.
        """
        incoming_sample_id = (
            str(sample.get("id") or "") if isinstance(sample, dict) else ""
        )
        if self.current_sample_id and incoming_sample_id != self.current_sample_id:
            self.save_current_annotation()
        else:
            self._autosave_timer.stop()

        if not isinstance(sample, dict):
            self.current_sample_id = ""
            self.current_action_path = None
            self._current_sample_snapshot = {}
            self._selected_caption_index = -1
            self.description_panel.set_captions([], -1)
            self._set_editor_fields()
            self.description_panel.set_caption_editor_enabled(False)
            if self._is_active_mode():
                self.clearMarkersRequested.emit()
            return

        previous_sample_id = self.current_sample_id
        self.current_sample_id = incoming_sample_id
        if not self.current_sample_id:
            self.current_action_path = None
            self._current_sample_snapshot = {}
            self._selected_caption_index = -1
            self.description_panel.set_captions([], -1)
            self._set_editor_fields()
            self.description_panel.set_caption_editor_enabled(False)
            if self._is_active_mode():
                self.clearMarkersRequested.emit()
            return

        self._current_sample_snapshot = copy.deepcopy(sample)
        self.current_action_path = self._extract_primary_path(sample)
        self.description_panel.set_caption_editor_enabled(True)
        if self._is_active_mode():
            self.clearMarkersRequested.emit()

        preferred_row = (
            self._selected_caption_index
            if previous_sample_id == self.current_sample_id
            else 0
        )
        self._load_captions(sample, preferred_row)
        pending = self._pending_predictions.get(self.current_sample_id)
        if pending:
            self.description_panel.set_pending_prediction(pending)
            return
        smart = next(
            (
                caption
                for caption in sample.get("captions", [])
                if isinstance(caption, dict) and "confidence_score" in caption
            ),
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
            if (
                not isinstance(candidate, dict)
                or not sample_id
                or not str(candidate.get("text") or "").strip()
            ):
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
            captions = copy.deepcopy(self._current_sample_snapshot.get("captions", []))
            if not isinstance(captions, list):
                captions = []
            captions.append(accepted)
            self.captionsUpdateRequested.emit(self.current_sample_id, captions)
            self._current_sample_snapshot["captions"] = copy.deepcopy(captions)
            self._load_captions(self._current_sample_snapshot, len(captions) - 1)
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
        self._load_captions(self._current_sample_snapshot, self._selected_caption_index)
        self.description_panel.set_smart_inference_state(False)

    def reject_smart_inference(self):
        if self._pending_predictions.pop(self.current_sample_id, None) is not None:
            self.description_panel.set_pending_prediction(None)
            self.pendingPredictionsChanged.emit(set(self._pending_predictions))
            return
        # Persisted smart captions have no reversible pre-inference snapshot.
        # Rejecting them must not discard existing caption rows.
        self.description_panel.set_smart_inference_state(False)

    def _load_captions(self, data, preferred_row: int = 0):
        captions = data.get("captions", [])
        if not isinstance(captions, list):
            captions = []
        if captions:
            selected_row = min(max(int(preferred_row), 0), len(captions) - 1)
        else:
            selected_row = -1
        self._selected_caption_index = selected_row
        self.description_panel.set_captions(captions, selected_row)
        self._load_selected_caption_fields()

    def _load_selected_caption_fields(self):
        captions = self._current_sample_snapshot.get("captions", [])
        row = self._selected_caption_index
        caption = (
            captions[row]
            if isinstance(captions, list) and 0 <= row < len(captions)
            else None
        )
        if not isinstance(caption, dict):
            self._set_editor_fields()
            self.description_panel.set_caption_detail_enabled(False)
            return
        self._set_editor_fields(
            variant=str(caption.get("variant") or ""),
            lang=str(caption.get("lang") or ""),
            text=str(caption.get("text") or ""),
        )
        self.description_panel.set_caption_detail_enabled(True)

    def _set_editor_fields(self, *, variant: str = "", lang: str = "", text: str = ""):
        self._suspend_autosave = True
        try:
            self.description_panel.set_caption_fields(
                variant=variant, lang=lang, text=text
            )
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

    def _on_caption_selection_changed(self, row: int):
        row = int(row)
        if row == self._selected_caption_index:
            return
        self.save_current_annotation()
        self._selected_caption_index = row
        self._load_selected_caption_fields()

    def add_caption(self):
        if not self.current_sample_id:
            return False
        self.save_current_annotation()
        captions = copy.deepcopy(self._current_sample_snapshot.get("captions", []))
        if not isinstance(captions, list):
            captions = []
        captions.append({"lang": "en", "text": ""})
        self.captionsUpdateRequested.emit(self.current_sample_id, copy.deepcopy(captions))
        self._current_sample_snapshot["captions"] = copy.deepcopy(captions)
        self._load_captions(self._current_sample_snapshot, len(captions) - 1)
        return True

    def delete_selected_caption(self):
        if not self.current_sample_id:
            return False
        self.save_current_annotation()
        captions = copy.deepcopy(self._current_sample_snapshot.get("captions", []))
        row = self._selected_caption_index
        if not isinstance(captions, list) or not 0 <= row < len(captions):
            return False
        captions.pop(row)
        self.captionsUpdateRequested.emit(self.current_sample_id, copy.deepcopy(captions))
        self._current_sample_snapshot["captions"] = copy.deepcopy(captions)
        self._load_captions(self._current_sample_snapshot, min(row, len(captions) - 1))
        return True

    def save_current_annotation(self):
        """
        Persist current Description editor text into the selected sample captions.
        """
        if not self.current_sample_id:
            return False

        self._autosave_timer.stop()
        old_captions = copy.deepcopy(self._current_sample_snapshot.get("captions", []))
        row = self._selected_caption_index
        if not isinstance(old_captions, list) or not 0 <= row < len(old_captions):
            return False
        old_caption = old_captions[row]
        if not isinstance(old_caption, dict):
            return False

        fields = self.description_panel.get_caption_fields()
        new_caption = copy.deepcopy(old_caption)
        variant = str(fields.get("variant") or "").strip()
        lang = str(fields.get("lang") or "").strip()
        text = str(fields.get("text") or "")
        if variant:
            new_caption["variant"] = variant
        else:
            new_caption.pop("variant", None)
        if lang or "lang" in old_caption:
            new_caption["lang"] = lang
        new_caption["text"] = text
        new_captions = copy.deepcopy(old_captions)
        new_captions[row] = new_caption
        if old_captions == new_captions:
            return False

        self.captionsUpdateRequested.emit(
            self.current_sample_id,
            copy.deepcopy(new_captions),
        )
        self._current_sample_snapshot["captions"] = copy.deepcopy(new_captions)
        self.description_panel.update_caption_summary(row, new_caption)
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
