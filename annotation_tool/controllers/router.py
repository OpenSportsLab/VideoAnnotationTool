import json
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from controllers.classification.class_file_manager import ClassFileManager
from controllers.localization.loc_file_manager import LocFileManager
from controllers.description.desc_file_manager import DescFileManager
from controllers.dense_description.dense_file_manager import DenseFileManager

from ui.common.dialogs import ProjectTypeDialog

class AppRouter:
    """
    Handles application entry points and routing:
    1. Open JSON / Create New Project
    2. Determine Mode (Classification vs Localization vs Description vs Dense)
    3. Delegate to specific Managers
    4. Handle Project Closure
    """
    def __init__(self, main_window):
        self.main = main_window
        self.class_fm = ClassFileManager(main_window)
        self.loc_fm = LocFileManager(main_window)
        self.desc_fm = DescFileManager(main_window)
        self.dense_fm = DenseFileManager(main_window)

    def create_new_project_flow(self):
        """Unified entry point for creating a new project."""
        if not self.main.check_and_close_current_project():
            return

        dlg = ProjectTypeDialog(self.main)
        if dlg.exec():
            mode = dlg.selected_mode
            
            if mode == "classification":
                self.class_fm.create_new_project()
            elif mode == "localization":
                self.loc_fm.create_new_project()
            elif mode == "description":
                self.desc_fm.create_new_project()
            elif mode == "dense_description":
                self.dense_fm.create_new_project()

    def import_annotations(self):
        """Global entry point for loading a JSON file."""
        if not self.main.check_and_close_current_project():
            return
        
        file_path, _ = QFileDialog.getOpenFileName(
            self.main, "Select Project JSON", "", "JSON Files (*.json)"
        )
        if not file_path:
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f: 
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self.main, "Error", f"Invalid JSON: {e}")
            return

        # Detect the type using heuristics
        json_type = self._detect_json_type(data)

        if json_type == "classification":
            if self.class_fm.load_project(data, file_path):
                self.main.ui.show_classification_view()
            
        elif json_type == "localization":
            if self.loc_fm.load_project(data, file_path):
                self.main.ui.show_localization_view()

        elif json_type == "description":
            # [FIXED] Check return value to ensure validation passed before switching view
            if self.desc_fm.load_project(data, file_path):
                self.main.ui.show_description_view()
            
        elif json_type == "dense_description":
            if self.dense_fm.load_project(data, file_path):
                self.main.ui.show_dense_description_view()
            
        else:
            QMessageBox.critical(self.main, "Error", "Unknown JSON format or Task Type.")

    def close_project(self):
        """Handles closing the current project."""
        if not self.main.check_and_close_current_project():
            return

        self.class_fm._clear_workspace(full_reset=True)
        self.loc_fm._clear_workspace(full_reset=True)
        self.desc_fm._clear_workspace(full_reset=True)
        self.dense_fm._clear_workspace(full_reset=True)

        self.main.ui.show_welcome_view()
        self.main.show_temp_msg("Project Closed", "Returned to Home Screen", duration=1000)

    def _detect_json_type(self, data):
        """
        Heuristics to identify the project type from JSON structure.
        Refined to better detect Description tasks even if malformed.
        """
        task = str(data.get("task", "")).lower()
        
        # 1. Explicit task string check (Highest Priority)
        if "dense" in task:
            return "dense_description"
        
        if "caption" in task or "description" in task:
            return "description"
        
        if "spotting" in task or "localization" in task:
            return "localization"
            
        if "classification" in task:
            return "classification"

        # 2. Top-level Structure Check
        if "labels" in data and isinstance(data["labels"], dict):
            return "localization"

        # 3. Item Structure Heuristics (Fallback)
        items = data.get("data", [])
        if not items: 
            return "unknown"
            
        first = items[0] if isinstance(items[0], dict) else {}

        # Dense checks
        if "dense_captions" in first:
            return "dense_description"
        if "events" in first:
            evts = first.get("events", [])
            if evts and isinstance(evts, list) and len(evts) > 0 and "text" in evts[0]:
                return "dense_description"
            if evts and isinstance(evts, list) and len(evts) > 0 and "label" in evts[0]:
                return "localization"
        
        # Description checks
        if "captions" in first:
            return "description"

        # Classification checks
        if "labels" in first:
            return "classification"
            
        return "unknown"