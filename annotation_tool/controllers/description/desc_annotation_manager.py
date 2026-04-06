import copy
import os
from PyQt6.QtCore import QModelIndex
from PyQt6.QtWidgets import QMessageBox
# [NEW] Import CmdType for Undo/Redo
from models.app_state import CmdType


class DescAnnotationManager:
    """
    Manages data loading and saving for Description Mode (Right Panel).
    Handles the formatting of Q&A from JSON and flattening it upon save.
    Supports Undo/Redo operations.
    """
    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model
        self.current_action_path = None

    def reset_ui(self):
        """Reset the description editor UI for a new project."""
        self.main.description_panel.caption_edit.setPlainText("")
        self.main.description_panel.setEnabled(False)

    def setup_connections(self):
        """Connect UI signals to controller methods."""
        # [UPDATED] Tree Selection is now handled centrally in main_window.py
        
        # Connect Editor Buttons
        self.main.description_panel.confirm_clicked.connect(self.save_current_annotation)
        self.main.description_panel.clear_clicked.connect(self.clear_current_text)

    def handle_description_selection(self, current: QModelIndex, previous: QModelIndex):
        """
        Handle Description selection from the tree:
        1) Resolve media path from selection and load/play it when valid.
        2) Refresh description editor content for the selected item.
        """
        media_path = None
        if current.isValid():
            model = self.main.tree_model
            path = current.data(self.main.tree_model.FilePathRole)

            if model.hasChildren(current):
                first_child = model.index(0, 0, current)
                if first_child.isValid():
                    path = first_child.data(self.main.tree_model.FilePathRole)
                else:
                    path = None

            cwd = self.model.current_working_directory
            if path and cwd and not os.path.isabs(path):
                media_path = os.path.normpath(os.path.join(cwd, path))
            else:
                media_path = path

            if media_path and not os.path.exists(media_path):
                media_path = None

        if media_path:
            self.main.media_controller.load_and_play(media_path)

        self.on_item_selected(current, previous)

    def on_item_selected(self, current: QModelIndex, previous: QModelIndex):
        """
        Triggered when a tree item is selected. 
        Loads the corresponding data into the text editor.
        """
        if not current.isValid():
            self.main.description_panel.caption_edit.clear()
            self.current_action_path = None
            self.main.description_panel.caption_edit.setEnabled(False)
            return

        # 1. Identify the Action Path
        path = current.data(self.main.tree_model.FilePathRole)
        model = self.main.tree_model
        
        # If user clicked a child (video), find the parent (action) to show shared annotations
        if not model.hasChildren(current) and current.parent().isValid():
            parent_idx = current.parent()
            path = parent_idx.data(self.main.tree_model.FilePathRole)
        
        
        self.current_action_path = path
        self.main.description_panel.caption_edit.setEnabled(True)
        
        # 2. Find Data Object in Model
        # We search by path first, fallback to ID if needed
        action_data = next((item for item in self.model.action_item_data if item.get("metadata", {}).get("path") == path), None)
        if not action_data:
             #action_data = next((item for item in self.model.action_item_data if item.get("id") == current.text()), None)
             action_data = next((item for item in self.model.action_item_data if item.get("id") == current.data()), None)

        if not action_data:
            self.main.description_panel.caption_edit.setPlaceholderText("No metadata found for this item.")
            return

        # 3. Format and Display Text
        self._load_and_format_text(action_data)

    def _load_and_format_text(self, data):
        """
        Formats the display text. 
        - If 'captions' contains 'question' fields, formats as Q&A blocks.
        - If 'captions' is plain text (already saved), displays it directly.
        """
        captions = data.get("captions", [])
        formatted_blocks = []

        if captions:
            # Iterate through existing captions (which might be raw Q&A or edited text)
            for cap in captions:
                text = cap.get("text", "")
                question = cap.get("question", "") # Check for the 'question' key
                
                if question:
                    # Format as Q & A if the question key exists
                    formatted_blocks.append(f'Q: "{question}"\nA: "{text}"')
                else:
                    # Otherwise, just append the text (e.g. for already edited/flattened descriptions)
                    formatted_blocks.append(text)
            
            full_text = "\n\n".join(formatted_blocks)
        
        else:
            # Fallback: If no captions exist yet, try to generate template from metadata questions
            metadata = data.get("metadata", {})
            questions = metadata.get("questions", [])
            for i, q in enumerate(questions):
                formatted_blocks.append(f'Q: "{q}"\nA: ""')
            
            full_text = "\n\n".join(formatted_blocks)

        self.main.description_panel.caption_edit.setPlainText(full_text)

    def save_current_annotation(self):
        """
        Saves the current text content back to the JSON model.
        Flattens the structure: removes 'question' keys and saves everything as one text block.
        Now supports UNDO/REDO.
        """
        if not self.current_action_path:
            return

        text_content = self.main.description_panel.caption_edit.toPlainText()
        
        # Find the target data item in the model
        target_item = None
        for item in self.model.action_item_data:
            if item.get("metadata", {}).get("path") == self.current_action_path:
                target_item = item
                break
        
        if target_item:
            # --- [NEW] Undo/Redo Logic Start ---
            
            # 1. Capture Old State (Deep copy to ensure isolation)
            old_captions = copy.deepcopy(target_item.get("captions", []))
            
            # 2. Define New State
            new_captions = [
                {
                    "lang": "en", 
                    "text": text_content
                }
            ]
            
            # 3. Push Command to History Stack
            self.model.push_undo(
                CmdType.DESC_EDIT, 
                path=self.current_action_path, 
                old_data=old_captions, 
                new_data=new_captions
            )
            # --- Undo/Redo Logic End ---

            # Apply the Change
            target_item["captions"] = new_captions
            
            # Mark state as dirty so Save button becomes active
            self.model.is_data_dirty = True
            self.main.update_save_export_button_state()
            
            # Update Tree Icon (Done/Empty)
            is_done = bool(text_content.strip())
            self._update_tree_icon(self.current_action_path, is_done)
            
            self.main.show_temp_msg("Saved", "Description updated.")
            

    def clear_current_text(self):
        """Clears the editor text."""
        self.main.description_panel.caption_edit.clear()

    def _update_tree_icon(self, path, is_done):
        """Updates the checkmark icon in the tree view."""
        item = self.model.action_item_map.get(path)
        if item:
            item.setIcon(self.main.done_icon if is_done else self.main.empty_icon)

    # -------------------------------------------------------------------------
    #  Tree Navigation Helpers
    # -------------------------------------------------------------------------
    def nav_prev_action(self): self._nav_tree(step=-1, level='top')
    def nav_next_action(self): self._nav_tree(step=1, level='top')
    def nav_prev_clip(self): self._nav_tree(step=-1, level='child')
    def nav_next_clip(self): self._nav_tree(step=1, level='child')

    def _nav_tree(self, step, level):
        tree = self.main.dataset_explorer_panel.tree
        curr = tree.currentIndex()
        if not curr.isValid():
            return

        model = self.main.tree_model

        if level == 'top':
            if curr.parent().isValid():
                curr = curr.parent()
            new_row = curr.row() + step

            if 0 <= new_row < model.rowCount(QModelIndex()):
                new_idx = model.index(new_row, 0, QModelIndex())
                tree.setCurrentIndex(new_idx)
                tree.scrollTo(new_idx)

        elif level == 'child':
            parent = curr.parent()
            if not parent.isValid():
                if step == 1 and model.rowCount(curr) > 0:
                    child = model.index(0, 0, curr)
                    tree.setCurrentIndex(child)
                elif step == -1:
                    self.nav_prev_action()
            else:
                new_row = curr.row() + step
                if 0 <= new_row < model.rowCount(parent):
                    new_idx = model.index(new_row, 0, parent)
                    tree.setCurrentIndex(new_idx)
                else:
                    if step == 1:
                        self.nav_next_action()
                    else:
                        self.nav_prev_action()
