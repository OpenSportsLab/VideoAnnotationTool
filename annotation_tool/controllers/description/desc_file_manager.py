import os
import json
import datetime
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from utils import natural_sort_key

class DescFileManager:
    """
    Handles JSON I/O for Description (Video Captioning) projects.
    Includes strict validation and metadata preservation.
    Fixed to support Multi-Clip Actions and Q&A Caption structures.
    """
    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model

    def create_new_project(self):
        """Create a blank Description project."""
        self._clear_workspace(full_reset=True)

        # Initialize Default State
        self.model.current_task_name = "Untitled Description Task"
        self.model.project_description = ""
        self.model.modalities = ["video"]
        
        # Initialize Global Metadata
        self.model.desc_global_metadata = {
            "version": "1.0",
            "date": datetime.date.today().isoformat(),
            "metadata": {
                "source": "SoccerNet Annotation Tool",
                "created_by": "User",
            }
        }
        
        self.model.json_loaded = True
        self.model.is_data_dirty = True
        self.model.current_json_path = None
        self.model.current_working_directory = None

        self.main.setup_dynamic_ui() 
        self.main.show_description_view()
        self.main.update_save_export_button_state()
        
        if hasattr(self.main, "prepare_new_desc_ui"):
            self.main.prepare_new_desc_ui()

        self.main.statusBar().showMessage("Project Created — Description Workspace Ready", 5000)

    def load_project(self, data, file_path):
        """
        Load Description project from JSON.
        Returns True if successful, False otherwise.
        """
        # --- [STEP 1] VALIDATION ---
        if hasattr(self.model, "validate_desc_json"):
            is_valid, error_msg, warning_msg = self.model.validate_desc_json(data)

            if not is_valid:
                if len(error_msg) > 1000:
                    error_msg = error_msg[:1000] + "\n... (truncated)"
                error_text = (
                    "The imported JSON contains critical errors and cannot be loaded.\n\n"
                    f"{error_msg}\n\n"
                    "--------------------------------------------------\n"
                    "💡 Please download the correct Description JSON format from:\n"
                    "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-description-xfoul"
                )
                
                QMessageBox.critical(
                    self.main,
                    "Validation Error (Description)",
                    error_text,
                )
                return False 

            if warning_msg:
                if len(warning_msg) > 1000:
                    warning_msg = warning_msg[:1000] + "\n... (truncated)"
                res = QMessageBox.warning(
                    self.main,
                    "Validation Warnings",
                    "The file contains warnings:\n\n" + warning_msg + "\n\nContinue loading?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if res != QMessageBox.StandardButton.Yes:
                    return False

        # --- [STEP 2] CLEAR & LOAD ---
        self._clear_workspace(full_reset=True)

        self.model.current_working_directory = os.path.dirname(os.path.abspath(file_path))
        self.model.current_task_name = data.get("dataset_name", data.get("task", "Description Task"))
        
        # Preserve Global Metadata
        self.model.desc_global_metadata = {
            "version": data.get("version", "1.0"),
            "date": data.get("date", datetime.date.today().isoformat()),
            "metadata": data.get("metadata", {})
        }

        loaded_count = 0
        missing_files = []
        
        # --- [STEP 3] PROCESS ITEMS (Multi-Clip Support) ---
        for item in data.get("data", []):
            inputs = item.get("inputs", [])
            if not inputs: continue
            
            aid = item.get("id", "Unknown ID")
            
            # 1. Resolve ALL Source Files (for Tree Structure)
            source_files = []
            for inp in inputs:
                raw_path = inp.get("path", "")
                if not raw_path: continue
                
                # Path Resolution
                if os.path.isabs(raw_path):
                    final_path = raw_path
                else:
                    final_path = os.path.normpath(os.path.join(self.model.current_working_directory, raw_path))
                
                if os.path.exists(final_path):
                    source_files.append(final_path)
                else:
                    # Keep valid structure even if file missing locally, but warn
                    source_files.append(final_path) 
            
            if not source_files:
                missing_files.append(aid)
                continue
                
            # Check if any files are missing locally for warning
            if not any(os.path.exists(p) for p in source_files):
                missing_files.append(aid)

            # 2. Determine Action Key/Path
            # Priority: item.metadata.path -> item.id -> first video path
            # This 'action_path' is what keys the Tree Item to the Data.
            meta = item.get("metadata", {})
            action_path = meta.get("path")
            if not action_path:
                action_path = aid # Fallback to ID if no path in metadata
                
            # 3. Store COMPLETE Data Structure
            # We store the raw 'inputs' to preserve 'name': 'video1' etc.
            # We store 'captions' as-is so AnnotationManager sees the Q&A list.
            entry = {
                "name": aid,
                "path": action_path,     # Key for Tree
                "source_files": source_files, # List of absolute paths for playback/tree children
                "inputs": inputs,        # Original input metadata
                "captions": item.get("captions", []),
                "metadata": meta,
                "id": aid
            }
            
            # 4. Register
            self.model.action_item_data.append(entry)
            self.model.action_path_to_name[action_path] = aid
            
            # Store item metadata in the separate lookup if needed (legacy compatibility)
            if meta:
                self.model.imported_action_metadata[aid] = meta

            loaded_count += 1

        self.model.current_json_path = file_path
        self.model.json_loaded = True
        
        # Populate UI Tree
        # The viewer will call tree_model.add_entry using 'name', 'path', and 'source_files' from our entry
        self.main.populate_action_tree()
        self.main.update_save_export_button_state()
        
        if missing_files:
             QMessageBox.warning(self.main, "Load Warning", f"Could not find video files for {len(missing_files)} actions locally.")
        else:
            self.main.statusBar().showMessage(f"Loaded {loaded_count} actions into Description Mode.", 2000)

        return True

    def save_json(self):
        if self.model.current_json_path:
            return self._write_json(self.model.current_json_path)
        return self.export_json()

    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(self.main, "Export Description JSON", "", "JSON (*.json)")
        if path: return self._write_json(path)
        return False

    def _write_json(self, path):
        """Writes current state to JSON, preserving full structure."""
        global_meta = getattr(self.model, "desc_global_metadata", {})
        
        output = {
            "version": global_meta.get("version", "1.0"),
            "date": global_meta.get("date", datetime.date.today().isoformat()),
            "task": "video_captioning",
            "dataset_name": self.model.current_task_name,
            "metadata": global_meta.get("metadata", {}),
            "data": []
        }
        
        base_dir = os.path.dirname(path)
        sorted_items = sorted(self.model.action_item_data, key=lambda d: natural_sort_key(d.get("name", "")))
        
        for data in sorted_items:
            # We reconstruct the item from our internal model data
            # which is kept in sync by DescAnnotationManager
            
            # 1. Reconstruct Inputs
            # Try to use original 'inputs' structure, just updating paths to relative
            export_inputs = []
            original_inputs = data.get("inputs", [])
            source_files = data.get("source_files", [])
            
            if len(original_inputs) == len(source_files):
                # We can map 1-to-1
                for i, inp in enumerate(original_inputs):
                    new_inp = inp.copy()
                    abs_p = source_files[i]
                    try:
                        rel_p = os.path.relpath(abs_p, base_dir).replace(os.sep, "/")
                    except:
                        rel_p = abs_p
                    new_inp["path"] = rel_p
                    export_inputs.append(new_inp)
            else:
                # Fallback: create new input structs from source_files
                for i, abs_p in enumerate(source_files):
                    try:
                        rel_p = os.path.relpath(abs_p, base_dir).replace(os.sep, "/")
                    except:
                        rel_p = abs_p
                    export_inputs.append({
                        "type": "video",
                        "name": f"video{i+1}",
                        "path": rel_p
                    })

            # 2. Build Entry
            entry = {
                "id": data.get("name") or data.get("id"),
                "metadata": data.get("metadata", {}),
                "inputs": export_inputs,
                "captions": data.get("captions", []) # This contains the edited/loaded captions
            }
                
            output["data"].append(entry)
            
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=4, ensure_ascii=False)
            self.model.is_data_dirty = False
            self.main.statusBar().showMessage(f"Saved to {os.path.basename(path)}", 2000)
            return True
        except Exception as e:
            QMessageBox.critical(self.main, "Save Error", str(e))
            return False

    def _clear_workspace(self, full_reset=False):
        self.main.tree_model.clear()
        self.model.reset(full_reset)
        if full_reset:
            self.model.desc_global_metadata = {}
        
        # Clear Description UI elements
        if hasattr(self.main, "description_panel"):
             self.main.description_panel.caption_edit.clear()
             self.main.description_panel.caption_edit.setEnabled(False)
