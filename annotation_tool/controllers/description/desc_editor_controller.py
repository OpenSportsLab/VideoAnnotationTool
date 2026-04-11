import copy

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class DescEditorController(QObject):
    """
    Description editor controller.
    Owns caption editor signal wiring, text refresh, save, and clear/reset behavior.
    """

    clearMarkersRequested = pyqtSignal()
    captionsUpdateRequested = pyqtSignal(str, object)

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

    def setup_connections(self):
        """Connect Description editor UI signals to controller actions."""
        self.description_panel.captionTextChanged.connect(self._on_caption_text_changed)

    def on_mode_changed(self, index: int):
        self._active_mode_index = index
        if self._is_active_mode():
            self.clearMarkersRequested.emit()

    def reset_ui(self):
        """Reset the Description editor UI for project clear/close flows."""
        self._autosave_timer.stop()
        self.current_sample_id = ""
        self.current_action_path = None
        self._current_sample_snapshot = {}
        self._set_editor_text("")
        self.description_panel.set_caption_editor_enabled(False)

    def on_selected_sample_changed(self, sample):
        """
        Refresh Description editor content for selected tree item.
        """
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
