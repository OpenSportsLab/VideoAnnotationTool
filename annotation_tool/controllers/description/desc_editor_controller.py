import copy

from PyQt6.QtCore import QModelIndex

from models.app_state import CmdType


class DescEditorController:
    """
    Description editor controller.
    Owns caption editor signal wiring, text refresh, save, and clear/reset behavior.
    """

    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model
        self.current_action_path = None

    def setup_connections(self):
        """Connect Description editor UI signals to controller actions."""
        self.main.description_panel.confirm_clicked.connect(self.save_current_annotation)
        self.main.description_panel.clear_clicked.connect(self.clear_current_text)

    def reset_ui(self):
        """Reset the Description editor UI for project clear/close flows."""
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

        self.current_action_path = None
        self.main.description_panel.caption_edit.clear()
        self.main.description_panel.caption_edit.setEnabled(False)

    def on_item_selected(self, current: QModelIndex, previous: QModelIndex):
        """
        Refresh Description editor content for selected tree item.
        Selection/media loading is orchestrated by MainWindow.
        """
        if not current.isValid():
            self.main.description_panel.caption_edit.clear()
            self.current_action_path = None
            self.main.description_panel.caption_edit.setEnabled(False)
            return

        path = current.data(self.main.tree_model.FilePathRole)
        model = self.main.tree_model

        # If user clicked a child, use its parent action path.
        if not model.hasChildren(current) and current.parent().isValid():
            parent_idx = current.parent()
            path = parent_idx.data(self.main.tree_model.FilePathRole)

        self.current_action_path = path
        self.main.description_panel.caption_edit.setEnabled(True)

        action_data = next(
            (item for item in self.model.action_item_data if item.get("metadata", {}).get("path") == path),
            None,
        )
        if not action_data:
            action_data = next(
                (item for item in self.model.action_item_data if item.get("id") == current.data()),
                None,
            )

        if not action_data:
            self.main.description_panel.caption_edit.setPlaceholderText("No metadata found for this item.")
            return

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
        if not self.current_action_path:
            return

        text_content = self.main.description_panel.caption_edit.toPlainText()

        target_item = None
        for item in self.model.action_item_data:
            if item.get("metadata", {}).get("path") == self.current_action_path:
                target_item = item
                break

        if not target_item:
            return

        old_captions = copy.deepcopy(target_item.get("captions", []))
        new_captions = [{"lang": "en", "text": text_content}]

        self.model.push_undo(
            CmdType.DESC_EDIT,
            path=self.current_action_path,
            old_data=old_captions,
            new_data=new_captions,
        )

        target_item["captions"] = new_captions
        self.model.is_data_dirty = True
        self.main.update_save_export_button_state()

        # Keep tree status updates through the shared status-sync path.
        self.main.update_action_item_status(self.current_action_path)
        self.main.show_temp_msg("Saved", "Description updated.")

    # -------------------------------------------------------------------------
    # Tree Navigation Helpers (Description mode)
    # -------------------------------------------------------------------------
    def nav_prev_action(self):
        self._nav_tree(step=-1, level="top")

    def nav_next_action(self):
        self._nav_tree(step=1, level="top")

    def nav_prev_clip(self):
        self._nav_tree(step=-1, level="child")

    def nav_next_clip(self):
        self._nav_tree(step=1, level="child")

    def _nav_tree(self, step, level):
        tree = self.main.dataset_explorer_panel.tree
        curr = tree.currentIndex()
        if not curr.isValid():
            return

        model = self.main.tree_model

        if level == "top":
            if curr.parent().isValid():
                curr = curr.parent()
            new_row = curr.row() + step
            if 0 <= new_row < model.rowCount(QModelIndex()):
                new_idx = model.index(new_row, 0, QModelIndex())
                tree.setCurrentIndex(new_idx)
                tree.scrollTo(new_idx)
            return

        if level == "child":
            parent = curr.parent()
            if not parent.isValid():
                if step == 1 and model.rowCount(curr) > 0:
                    child = model.index(0, 0, curr)
                    tree.setCurrentIndex(child)
                elif step == -1:
                    self.nav_prev_action()
                return

            new_row = curr.row() + step
            if 0 <= new_row < model.rowCount(parent):
                new_idx = model.index(new_row, 0, parent)
                tree.setCurrentIndex(new_idx)
            else:
                if step == 1:
                    self.nav_next_action()
                else:
                    self.nav_prev_action()
