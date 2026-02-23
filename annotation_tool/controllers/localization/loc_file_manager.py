import os
import json

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from PyQt6.QtCore import QUrl

from utils import natural_sort_key


class LocFileManager:
    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model
        self.ui = main_window.ui

    def create_new_project(self):
        """
        Create a new Localization project (Blank).
        Skips the wizard dialog and immediately unlocks the workspace.
        """
    
        # 2) Clear the existing workspace (Full Reset)
        # This clears the UI and resets model data
        self._clear_workspace(full_reset=True)

        # 3) Initialize default "Blank Project" state in the Model
        self.model.current_task_name = "Untitled Task"
        self.model.project_description = ""
        self.model.modalities = ["video"]
        # Empty schema initially. User will add heads via the UI.
        self.model.label_definitions = {} 

        # Set Localization-mode states
        self.model.current_working_directory = None
        self.model.current_json_path = None
        
        # [KEY STEP] Mark project as loaded to enable UI interactions
        self.model.json_loaded = True
        self.model.is_data_dirty = True

        # 4) Refresh Localization UI
        # This updates the tabs to show ONLY the "+" button.
        self.main.loc_manager.right_panel.annot_mgmt.update_schema(self.model.label_definitions)
        
        # Reset the left tree (empty at creation time)
        self.main.loc_manager.populate_tree()

        # 5) Switch view to Localization
        self.main.ui.show_localization_view()
        self.main.update_save_export_button_state()

        # 6) [CRITICAL] Explicitly unlock the Localization UI
        # This ensures the Right Panel is enabled (clickable) even with 0 videos.
        if hasattr(self.main, "prepare_new_localization_ui"):
            self.main.prepare_new_localization_ui()
        self.main.statusBar().showMessage("Project Created — Localization Workspace Ready", 5000)


    def load_project(self, data, file_path):
        """
        Load a Localization project from JSON.
        """
        # Validate JSON if the model provides a validator
        if hasattr(self.model, "validate_loc_json"):
            is_valid, error_msg, warning_msg = self.model.validate_loc_json(data)

            if not is_valid:
                if len(error_msg) > 800:
                    error_msg = error_msg[:800] + "\n... (truncated)"
                QMessageBox.critical(
                    self.main,
                    "Validation Error",
                    "Critical errors found in JSON. Load aborted.\n\n" + error_msg,
                )
                return False

            if warning_msg:
                if len(warning_msg) > 800:
                    warning_msg = warning_msg[:800] + "\n... (truncated)"
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

        # Clear workspace before loading
        self._clear_workspace(full_reset=True)

        project_root = os.path.dirname(os.path.abspath(file_path))
        self.model.current_working_directory = project_root

        # Basic metadata
        self.model.current_task_name = data.get("dataset_name", data.get("task", "Localization Task"))
        self.model.modalities = data.get("modalities", ["video"])

        # Labels / schema
        if "labels" in data:
            self.model.label_definitions = data["labels"]
            self.main.loc_manager.right_panel.annot_mgmt.update_schema(self.model.label_definitions)

            # Choose a reasonable default head
            default_head = None
            if "ball_action" in self.model.label_definitions:
                default_head = "ball_action"
            elif "action" in self.model.label_definitions:
                default_head = "action"
            elif list(self.model.label_definitions.keys()):
                default_head = list(self.model.label_definitions.keys())[0]

            if default_head:
                self.main.loc_manager.current_head = default_head
                self.main.loc_manager.right_panel.annot_mgmt.tabs.set_current_head(default_head)

        missing_files = []
        loaded_count = 0

        # Load items (clips) and events
        for item in data.get("data", []):
            inputs = item.get("inputs", [])
            if not inputs or not isinstance(inputs, list):
                continue

            raw_path = inputs[0].get("path", "")
            aid = item.get("id")
            if not aid:
                aid = os.path.splitext(os.path.basename(raw_path))[0]

            final_path = raw_path

            # Path resolution logic
            if os.path.isabs(raw_path) and os.path.exists(raw_path):
                final_path = raw_path
            else:
                norm_raw = raw_path.replace("\\", "/")
                abs_path_strict = os.path.normpath(os.path.join(project_root, norm_raw))

                if os.path.exists(abs_path_strict):
                    final_path = abs_path_strict
                else:
                    filename = os.path.basename(norm_raw)
                    abs_path_flat = os.path.join(project_root, filename)

                    if os.path.exists(abs_path_flat):
                        final_path = abs_path_flat
                    else:
                        final_path = abs_path_strict
                        missing_files.append(f"{aid}: {filename}")

            # Register clip in the model
            self.model.action_item_data.append(
                {"name": aid, "path": final_path, "source_files": [final_path]}
            )
            self.model.action_path_to_name[final_path] = aid

            # Process events
            raw_events = item.get("events", [])
            processed_events = []

            if isinstance(raw_events, list):
                for evt in raw_events:
                    if not isinstance(evt, dict):
                        continue
                    try:
                        pos_ms = int(evt.get("position_ms", 0))
                    except ValueError:
                        pos_ms = 0

                    processed_events.append(
                        {
                            "head": evt.get("head", "action"),
                            "label": evt.get("label", "?"),
                            "position_ms": pos_ms,
                        }
                    )

            if processed_events:
                self.model.localization_events[final_path] = processed_events

            loaded_count += 1

        # Update model status after loading
        self.model.current_json_path = file_path
        self.model.json_loaded = True

        # Refresh UI tree
        self.main.loc_manager.populate_tree()

        # Report missing files (if any)
        if missing_files:
            shown_missing = missing_files[:5]
            msg = (
                f"Loaded {loaded_count} clips.\n\n"
                f"WARNING: {len(missing_files)} videos not found locally:\n"
                + "\n".join(shown_missing)
            )
            if len(missing_files) > 5:
                msg += "\n..."
            QMessageBox.warning(self.main, "Load Warning", msg)
        else:
            self.main.statusBar().showMessage(
                f"Mode Switched — Loaded {loaded_count} clips. Current Mode: LOCALIZATION",
                1500
            )


        return True

    def overwrite_json(self):
        """Overwrite current JSON if exists, else export."""
        if self.model.current_json_path:
            return self._write_json(self.model.current_json_path)
        return self.export_json()

    def export_json(self):
        """Export Localization JSON to a user-selected file path."""
        path, _ = QFileDialog.getSaveFileName(
            self.main, "Export Localization JSON", "", "JSON (*.json)"
        )
        if path:
            if self._write_json(path):
                self.model.current_json_path = path
                self.model.is_data_dirty = False
                return True
        return False

    def _write_json(self, path):
        """Write the current Localization project state into a JSON file."""
        output = {
            "version": "2.0",
            "date": "2025-12-16",
            "task": "action_spotting",
            "dataset_name": self.model.current_task_name,
            "metadata": {
                "source": "Annotation Tool Export",
                "created_by": "User",
            },
            "labels": self.model.label_definitions,
            "data": [],
        }

        base_dir = os.path.dirname(path)
        sorted_items = sorted(
            self.model.action_item_data, key=lambda d: natural_sort_key(d.get("name", ""))
        )

        for data in sorted_items:
            abs_path = data["path"]
            events = self.model.localization_events.get(abs_path, [])

            # Store path as relative if possible
            try:
                rel_path = os.path.relpath(abs_path, base_dir).replace(os.sep, "/")
            except Exception:
                rel_path = abs_path

            # Convert events to export format
            export_events = []
            for e in events:
                export_events.append(
                    {
                        "head": e.get("head"),
                        "label": e.get("label"),
                        "position_ms": str(e.get("position_ms")),
                    }
                )

            entry = {
                "inputs": [
                    {
                        "type": "video",
                        "path": rel_path,
                        "fps": 25.0,
                    }
                ],
                "events": export_events,
            }
            output["data"].append(entry)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=4, ensure_ascii=False)

            self.model.is_data_dirty = False
            self.main.statusBar().showMessage(f"Saved — {os.path.basename(path)}", 1500)
            return True
        except Exception as e:
            QMessageBox.critical(self.main, "Error", f"Save failed: {e}")
            return False

    def _clear_workspace(self, full_reset=False):
        """
        Clear UI panels and reset the model state.
        """
        if hasattr(self.main, "loc_manager"):
            # Left panel: clear clip tree
            self.main.tree_model.clear() 

            # Center panel: stop media preview and clear source
            self.main.loc_manager.center_panel.media_preview.stop()
            self.main.loc_manager.center_panel.media_preview.player.setSource(QUrl())

            # Right panel: clear table and schema
            self.main.loc_manager.right_panel.table.set_data([])
            self.main.loc_manager.right_panel.annot_mgmt.update_schema({})

        # Reset model data
        self.model.reset(full_reset)

        # Optionally show welcome screen
        if full_reset:
            self.main.ui.show_welcome_view()
