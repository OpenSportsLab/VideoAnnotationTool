import copy

from PyQt6.QtCore import QTimer

from controllers.command_types import CmdType


class DescEditorController:
    """
    Description editor controller.
    Owns caption editor signal wiring, text refresh, save, and clear/reset behavior.
    """

    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model
        self.description_panel = main_window.description_panel
        self.current_sample_id = ""
        self.current_action_path = None
        self._suspend_autosave = False
        self._autosave_timer = QTimer(self.main)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(250)
        self._autosave_timer.timeout.connect(self._save_current_annotation_if_needed)

    def setup_connections(self):
        """Connect Description editor UI signals to controller actions."""
        self.description_panel.caption_edit.textChanged.connect(self._on_caption_text_changed)

    def reset_ui(self):
        """Reset the Description editor UI for project clear/close flows."""
        self._autosave_timer.stop()
        self.current_sample_id = ""
        self.current_action_path = None
        self._set_editor_text("")
        self.description_panel.caption_edit.setEnabled(False)
        self.description_panel.setEnabled(False)

    def on_item_removed(self, path: str):
        """Handle removal of a description item from the dataset explorer."""
        if self.current_action_path != path:
            return

        self._autosave_timer.stop()
        self.current_sample_id = ""
        self.current_action_path = None
        self._set_editor_text("")
        self.description_panel.caption_edit.setEnabled(False)

    def on_data_selected(self, data_id: str):
        """
        Refresh Description editor content for selected tree item.
        """
        if not data_id:
            self._autosave_timer.stop()
            self.current_sample_id = ""
            self._set_editor_text("")
            self.current_action_path = None
            self.description_panel.caption_edit.setEnabled(False)
            self.description_panel.setEnabled(False)
            if self.main.right_tabs.currentIndex() == 2:
                self.main.center_panel.set_markers([])
            return

        action_data = self.model.get_item_by_id(data_id)
        if not action_data:
            self.description_panel.caption_edit.setPlaceholderText("No metadata found for this item.")
            self._autosave_timer.stop()
            self.current_sample_id = ""
            self.current_action_path = None
            self._set_editor_text("")
            self.description_panel.caption_edit.setEnabled(False)
            self.description_panel.setEnabled(False)
            if self.main.right_tabs.currentIndex() == 2:
                self.main.center_panel.set_markers([])
            return

        self.current_sample_id = data_id
        self.current_action_path = action_data.get("metadata", {}).get("path") or action_data.get("path")
        self.description_panel.caption_edit.setEnabled(True)
        self.description_panel.setEnabled(True)
        if self.main.right_tabs.currentIndex() == 2:
            self.main.center_panel.set_markers([])

        self._load_and_format_text(action_data)

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
            self.description_panel.caption_edit.setPlainText(text)
        finally:
            self._suspend_autosave = False

    def _on_caption_text_changed(self):
        if self._suspend_autosave:
            return
        if not self.current_sample_id:
            return
        self._autosave_timer.start()

    def _save_current_annotation_if_needed(self):
        self.save_current_annotation(show_feedback=False)

    def save_current_annotation(self, show_feedback: bool = False):
        """
        Persist current Description editor text into the selected action captions.
        Pushes DESC_EDIT undo command and updates done status.
        """
        if not self.current_sample_id:
            return False

        text_content = self.description_panel.caption_edit.toPlainText()
        sample = self.model.get_sample(self.current_sample_id)
        if not sample:
            return False

        old_captions = copy.deepcopy(sample.get("captions", []))
        new_captions = [{"lang": "en", "text": text_content}]
        if old_captions == new_captions:
            return False

        self.model.push_undo(
            CmdType.DESC_EDIT,
            path=self.current_action_path,
            sample_id=self.current_sample_id,
            old_data=old_captions,
            new_data=new_captions,
        )

        self.model.set_sample_captions(self.current_sample_id, new_captions)
        self.model.is_data_dirty = True
        self.main.update_save_export_button_state()

        # Keep tree status updates through the shared status-sync path.
        self.main.update_action_item_status(self.current_action_path)
        if show_feedback:
            self.main.show_temp_msg("Saved", "Description updated.")
        return True
