import json
import os
from PyQt6.QtWidgets import QFileDialog, QMessageBox

class DescFileManager:
    """
    Handles JSON I/O for the Description / Video Captioning mode.
    Responsible for populating the ProjectTreeModel and saving data back to disk.
    """
    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model  # AppStateModel

    def create_new_project(self):
        """
        Initializes a fresh Description project state.
        """
        # 1. Reset Global State
        self._clear_workspace(full_reset=True)
        
        # 2. Set Task Metadata
        self.model.current_task_name = "video_captioning"
        self.model.json_loaded = True
        self.model.is_data_dirty = True
        self.model.current_working_directory = None
        self.model.current_json_path = None
        
        # 3. Setup UI for blank state
        self.main.prepare_new_description_ui()
        self.main.ui.show_description_view()
        self.main.update_save_export_button_state()
        
        self.main.show_temp_msg("New Project", "Description project created. Use 'Add Data' to start.")

    def load_project(self, data: dict, file_path: str):
        """
        Loads the JSON data into the Model and populates the Tree View.
        """
        self._clear_workspace(full_reset=False)
        self.model.current_json_path = file_path
        self.model.current_working_directory = os.path.dirname(file_path)
        
        # 1. Store Raw Data
        self.model.action_item_data = data.get("data", [])
        self.model.current_task_name = data.get("task", "video_captioning")
        
        # 2. Populate the Tree
        self._populate_tree()
        
        # 3. Finalize UI
        self.model.json_loaded = True
        self.model.is_data_dirty = False
        self.main.setWindowTitle(f"SoccerNet Pro - {os.path.basename(file_path)}")
        self.main.update_save_export_button_state()
        
        self.main.show_temp_msg("Loaded", f"Loaded {len(self.model.action_item_data)} actions.")

    def save_json(self) -> bool:
        """Saves the current state back to JSON."""
        if not self.model.current_json_path:
            return self.save_as_json()

        # Construct data dictionary
        output_data = {
            "version": "1.0",
            "task": self.model.current_task_name,
            "data": self.model.action_item_data
        }
        # Preserve metadata if available in model (optional expansion)

        try:
            with open(self.model.current_json_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            self.model.is_data_dirty = False
            self.main.update_save_export_button_state()
            self.main.show_temp_msg("Saved", "Project saved successfully.")
            return True
        except Exception as e:
            QMessageBox.critical(self.main, "Save Error", f"Failed to save JSON:\n{e}")
            return False

    def save_as_json(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self.main, "Save Project As", "", "JSON Files (*.json)"
        )
        if not path:
            return False
            
        self.model.current_json_path = path
        return self.save_json()

    def export_json(self):
        """Export logic (currently same as save as)."""
        self.save_as_json()

    def _populate_tree(self):
        """
        Converts JSON structure into the QStandardItemModel.
        """
        tree_model = self.main.tree_model
        tree_model.clear()
        self.model.action_item_map.clear()

        # Iterate through the JSON 'data' list
        for item in self.model.action_item_data:
            # A. Get Display Name (Action ID)
            action_id = item.get("id", "Unknown ID")
            
            # B. Get Metadata Path
            action_path = item.get("metadata", {}).get("path", action_id)
            
            # C. Extract Video Paths from 'inputs' list
            input_paths = []
            inputs = item.get("inputs", [])
            for inp in inputs:
                if isinstance(inp, dict) and "path" in inp:
                    input_paths.append(inp["path"])
            
            # D. Add to Tree Model
            tree_item = tree_model.add_entry(
                name=action_id,
                path=action_path,
                source_files=input_paths
            )
            
            # Store mapping
            self.model.action_item_map[action_path] = tree_item
            
            # E. Check Status
            captions = item.get("captions", [])
            has_content = len(captions) > 0 and bool(captions[0].get("text", "").strip())
            
            if has_content:
                tree_item.setIcon(self.main.done_icon)
            else:
                tree_item.setIcon(self.main.empty_icon)

    def _clear_workspace(self, full_reset=True):
        """Clears the tree and model state."""
        self.main.tree_model.clear()
        self.model.action_item_map.clear()
        if full_reset:
            self.model.json_loaded = False
            self.model.current_json_path = None
            self.model.action_item_data = []
            self.model.is_data_dirty = False
            self.main.ui.description_ui.right_panel.caption_edit.clear()
            self.main.ui.description_ui.right_panel.caption_edit.setEnabled(False)