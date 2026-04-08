import copy

from controllers.command_types import CmdType


class DescEditorController:
    """
    Description editor controller.
    Owns caption editor signal wiring, text refresh, save, and clear/reset behavior.
    """

    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model
        self.current_sample_id = ""
        self.current_action_path = None

    def setup_connections(self):
        """Connect Description editor UI signals to controller actions."""
        self.main.description_panel.confirm_clicked.connect(self.save_current_annotation)
        self.main.description_panel.clear_clicked.connect(self.clear_current_text)

    def reset_ui(self):
        """Reset the Description editor UI for project clear/close flows."""
        self.current_sample_id = ""
        self.current_action_path = None
        self.main.description_panel.caption_edit.setPlainText("")
        self.main.description_panel.caption_edit.setEnabled(False)
        self.main.description_panel.setEnabled(False)

    def clear_current_text(self):
        """Clear current editor text."""
        self.main.description_panel.caption_edit.clear()

    def on_item_removed(self, path: str):
        """Handle removal of a description item from the dataset explorer."""
        if self.current_action_path != path:
            return

        self.current_sample_id = ""
        self.current_action_path = None
        self.main.description_panel.caption_edit.clear()
        self.main.description_panel.caption_edit.setEnabled(False)

    def on_data_selected(self, data_id: str):
        """
        Refresh Description editor content for selected tree item.
        """
        if not data_id:
            self.current_sample_id = ""
            self.main.description_panel.caption_edit.clear()
            self.current_action_path = None
            self.main.description_panel.caption_edit.setEnabled(False)
            self.main.description_panel.setEnabled(False)
            if self.main.right_tabs.currentIndex() == 2:
                self.main.center_panel.set_markers([])
            return

        action_data = self.model.get_item_by_id(data_id)
        if not action_data:
            self.main.description_panel.caption_edit.setPlaceholderText("No metadata found for this item.")
            self.current_sample_id = ""
            self.current_action_path = None
            self.main.description_panel.caption_edit.clear()
            self.main.description_panel.caption_edit.setEnabled(False)
            self.main.description_panel.setEnabled(False)
            if self.main.right_tabs.currentIndex() == 2:
                self.main.center_panel.set_markers([])
            return

        self.current_sample_id = data_id
        self.current_action_path = action_data.get("metadata", {}).get("path") or action_data.get("path")
        self.main.description_panel.caption_edit.setEnabled(True)
        self.main.description_panel.setEnabled(True)
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

        self.main.description_panel.caption_edit.setPlainText(full_text)

    def save_current_annotation(self):
        """
        Persist current Description editor text into the selected action captions.
        Pushes DESC_EDIT undo command and updates done status.
        """
        if not self.current_sample_id:
            return

        text_content = self.main.description_panel.caption_edit.toPlainText()
        sample = self.model.get_sample(self.current_sample_id)
        if not sample:
            return

        old_captions = copy.deepcopy(sample.get("captions", []))
        new_captions = [{"lang": "en", "text": text_content}]

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
        self.main.show_temp_msg("Saved", "Description updated.")
