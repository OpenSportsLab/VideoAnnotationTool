import copy
from PyQt6.QtCore import QModelIndex
from PyQt6.QtWidgets import QMessageBox
from models.project_tree import ProjectTreeModel

class DescAnnotationManager:
    """
    Manages data loading and saving for Description Mode (Right Panel).
    Handles the formatting of Q&A from JSON and flattening it upon save.
    """
    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model
        self.ui = main_window.ui.description_ui.right_panel
        self.current_action_path = None

    def setup_connections(self):
        """Connect UI signals to controller methods."""
        # Listen to Tree Selection from the Description Panel
        tree = self.main.ui.description_ui.left_panel.tree
        tree.selectionModel().currentChanged.connect(self.on_item_selected)
        
        # Connect Editor Buttons
        self.ui.confirm_clicked.connect(self.save_current_annotation)
        self.ui.clear_clicked.connect(self.clear_current_text)

    def on_item_selected(self, current: QModelIndex, previous: QModelIndex):
        """
        Triggered when a tree item is selected. 
        Loads the corresponding data into the text editor.
        """
        if not current.isValid():
            self.ui.caption_edit.clear()
            self.current_action_path = None
            self.ui.caption_edit.setEnabled(False)
            return

        # 1. Identify the Action Path
        path = current.data(ProjectTreeModel.FilePathRole)
        model = self.main.tree_model
        
        # If user clicked a child (video), find the parent (action) to show shared annotations
        if not model.hasChildren(current) and current.parent().isValid():
            parent_idx = current.parent()
            path = parent_idx.data(ProjectTreeModel.FilePathRole)
        
        self.current_action_path = path
        self.ui.caption_edit.setEnabled(True)
        
        # 2. Find Data Object in Model
        # We search by path first, fallback to ID if needed
        action_data = next((item for item in self.model.action_item_data if item.get("metadata", {}).get("path") == path), None)
        if not action_data:
             action_data = next((item for item in self.model.action_item_data if item.get("id") == current.text()), None)

        if not action_data:
            self.ui.caption_edit.setPlaceholderText("No metadata found for this item.")
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

        self.ui.caption_edit.setPlainText(full_text)

    def save_current_annotation(self):
        """
        Saves the current text content back to the JSON model.
        Flattens the structure: removes 'question' keys and saves everything as one text block.
        """
        if not self.current_action_path:
            return

        text_content = self.ui.caption_edit.toPlainText()
        
        # Find the target data item in the model
        target_item = None
        for item in self.model.action_item_data:
            if item.get("metadata", {}).get("path") == self.current_action_path:
                target_item = item
                break
        
        if target_item:
            # [CRITICAL UPDATE]
            # Replace the entire 'captions' list with a single entry containing the full text.
            # This effectively removes the old 'question' fields from the JSON structure
            # and stores the user's edited content purely as 'text'.
            target_item["captions"] = [
                {
                    "lang": "en", 
                    "text": text_content
                }
            ]
            
            # Mark state as dirty so Save button becomes active
            self.model.is_data_dirty = True
            self.main.update_save_export_button_state()
            
            # Update Tree Icon (Done/Empty)
            is_done = bool(text_content.strip())
            self._update_tree_icon(self.current_action_path, is_done)
            
            self.main.show_temp_msg("Saved", "Description updated.")
            
            # Auto-advance to next item
            self._auto_advance()

    def clear_current_text(self):
        """Clears the editor text."""
        self.ui.caption_edit.clear()

    def _update_tree_icon(self, path, is_done):
        """Updates the checkmark icon in the tree view."""
        item = self.model.action_item_map.get(path)
        if item:
            item.setIcon(self.main.done_icon if is_done else self.main.empty_icon)

    def _auto_advance(self):
        """Moves selection to the next Action in the tree automatically."""
        self.main.desc_nav_manager.nav_next_action()