import os
import json
import datetime
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from PyQt6.QtCore import QUrl
from utils import natural_sort_key

class DenseFileManager:
    """
    Handles JSON I/O for Dense Video Captioning projects.
    Includes validation and metadata preservation.
    """
    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model

    def create_new_project(self):
        """
        Create a new Dense Description project (Blank).
        Initializes default metadata and workspace.
        """
        # 1. Safety Check
        if not self.main.check_and_close_current_project():
            return

        # 2. Clear Workspace
        self._clear_workspace(full_reset=True)

        # 3. Initialize Model State
        self.model.current_task_name = "Untitled Dense Task"
        self.model.project_description = ""
        self.model.modalities = ["video"]
        self.model.dense_description_events = {}
        
        # [NEW] Initialize default Global Metadata for new projects
        self.model.dense_global_metadata = {
            "version": "1.0",
            "date": datetime.date.today().isoformat(),
            "metadata": {
                "source": "SoccerNet Annotation Tool",
                "created_by": "User",
                "license": "CC-BY-NC 4.0"
            }
        }
        
        # Reset paths
        self.model.current_working_directory = None
        self.model.current_json_path = None
        
        # Mark as loaded
        self.model.json_loaded = True
        self.model.is_data_dirty = True

        # 4. Refresh UI
        self.main.dense_manager.populate_tree()
        self.main.ui.show_dense_description_view()
        self.main.update_save_export_button_state()
        
        if hasattr(self.main, "prepare_new_dense_ui"):
            self.main.prepare_new_dense_ui()
            
        self.main.statusBar().showMessage("Project Created — Dense Description Workspace Ready", 5000)

    def load_project(self, data, file_path):
        """
        Loads dense description project from JSON data.
        Performs strict validation and preserves metadata.
        """
        # --- [STEP 1] VALIDATION ---
        # Call the strict validator defined in AppStateModel
        if hasattr(self.model, "validate_dense_json"):
            is_valid, error_msg, warning_msg = self.model.validate_dense_json(data)

            if not is_valid:
                # Truncate extremely long error messages for display
                if len(error_msg) > 1000:
                    error_msg = error_msg[:1000] + "\n... (truncated)"
                
                QMessageBox.critical(
                    self.main,
                    "Validation Error (Dense Description)",
                    "The imported JSON contains critical errors and cannot be loaded.\n\n" + error_msg,
                )
                return False

            if warning_msg:
                # Show warnings but allow loading to proceed
                if len(warning_msg) > 1000:
                    warning_msg = warning_msg[:1000] + "\n... (truncated)"
                res = QMessageBox.warning(
                    self.main,
                    "Validation Warnings",
                    "The file contains warnings:\n\n"
                    + warning_msg
                    + "\n\nDo you want to continue loading?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if res != QMessageBox.StandardButton.Yes:
                    return False

        # --- [STEP 2] CLEAR & SETUP ---
        self._clear_workspace(full_reset=True)
        
        project_root = os.path.dirname(os.path.abspath(file_path))
        self.model.current_working_directory = project_root
        self.model.current_task_name = data.get("dataset_name", data.get("task", "Dense Captioning"))

        # [NEW] Preserve Global Metadata
        self.model.dense_global_metadata = {
            "version": data.get("version", "1.0"),
            "date": data.get("date", datetime.date.today().isoformat()),
            "metadata": data.get("metadata", {})
        }

        missing_files = []
        loaded_count = 0

        # --- [STEP 3] LOAD ITEMS ---
        for item in data.get("data", []):
            inputs = item.get("inputs", [])
            if not inputs: continue
            
            raw_path = inputs[0].get("path", "")
            # ID Priority: explicit 'id' -> filename without extension
            aid = item.get("id") or os.path.splitext(os.path.basename(raw_path))[0]
            
            # Resolve Path
            final_path = os.path.normpath(os.path.join(project_root, raw_path))
            if not os.path.exists(final_path):
                missing_files.append(aid)

            # [NEW] Preserve Item-level Metadata (using AppState's imported_action_metadata)
            if "metadata" in item:
                self.model.imported_action_metadata[aid] = item["metadata"]

            # Register Clip
            self.model.action_item_data.append({"name": aid, "path": final_path, "source_files": [final_path]})
            self.model.action_path_to_name[final_path] = aid

            # Load Events (dense_captions)
            events = item.get("dense_captions", item.get("events", []))
            if events:
                self.model.dense_description_events[final_path] = []
                for e in events:
                    self.model.dense_description_events[final_path].append({
                        "position_ms": int(e.get("position_ms", 0)),
                        "lang": e.get("lang", "en"),
                        "text": e.get("text", "")
                    })
            loaded_count += 1

        self.model.current_json_path = file_path
        self.model.json_loaded = True
        
        # --- [STEP 4] FINALIZE ---
        self.main.dense_manager.populate_tree()
        
        if missing_files:
            QMessageBox.warning(self.main, "Load Warning", f"Could not find {len(missing_files)} video files locally.")
        else:
            self.main.statusBar().showMessage(f"Dense Mode: Loaded {loaded_count} clips.", 2000)
            
        return True

    def overwrite_json(self):
        if self.model.current_json_path:
            return self._write_json(self.model.current_json_path)
        return self.export_json()

    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(self.main, "Export Dense JSON", "", "JSON (*.json)")
        if path: return self._write_json(path)
        return False

    def _write_json(self, path):
        """Serializes current dense description state to JSON, preserving all metadata."""
        
        # [NEW] Retrieve Global Metadata from Model (or defaults)
        global_meta = getattr(self.model, "dense_global_metadata", {})
        
        output = {
            "version": global_meta.get("version", "1.0"),
            "date": global_meta.get("date", datetime.date.today().isoformat()),
            "task": "dense_video_captioning",
            "dataset_name": self.model.current_task_name,
            "metadata": global_meta.get("metadata", {
                "source": "SoccerNet Annotation Tool",
                "created_by": "User"
            }),
            "data": []
        }
        
        base_dir = os.path.dirname(path)
        
        sorted_items = sorted(
            self.model.action_item_data, key=lambda d: natural_sort_key(d.get("name", ""))
        )

        for data in sorted_items:
            abs_path = data["path"]
            aid = data["name"]
            events = self.model.dense_description_events.get(abs_path, [])
            
            try:
                rel_path = os.path.relpath(abs_path, base_dir).replace(os.sep, "/")
            except:
                rel_path = abs_path

            # Format Events
            export_events = []
            sorted_events = sorted(events, key=lambda x: x.get("position_ms", 0))
            
            for e in sorted_events:
                export_events.append({
                    "position_ms": e["position_ms"],
                    "lang": e["lang"],
                    "text": e["text"]
                })

            # Build Item Entry
            entry = {
                "id": aid,
                "inputs": [{"type": "video", "path": rel_path, "fps": 25}], # FPS is hardcoded or needs retrieval
                "dense_captions": export_events
            }
            
            # [NEW] Inject Item-level Metadata if available
            item_meta = self.model.imported_action_metadata.get(aid)
            if item_meta:
                entry["metadata"] = item_meta
                
            output["data"].append(entry)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=4, ensure_ascii=False)
            
            self.model.current_json_path = path
            self.model.is_data_dirty = False
            self.main.statusBar().showMessage(f"Saved — {os.path.basename(path)}", 1500)
            return True
        except Exception as e:
            QMessageBox.critical(self.main, "Error", f"Save failed: {e}")
            return False

    def _clear_workspace(self, full_reset=False):
        """Resets the workspace for Dense Description mode."""
        self.model.reset(full_reset)
        
        # [NEW] Clear global metadata explicitly if full reset
        if full_reset:
             self.model.dense_global_metadata = {}

        if hasattr(self.main, "dense_manager"):
            self.main.dense_manager.media_controller.stop()
            self.main.dense_manager.right_panel.table.set_data([])
            self.main.dense_manager.right_panel.input_widget.set_text("")
