import json
from PyQt6.QtWidgets import QFileDialog, QMessageBox

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

    def create_new_project_flow(self):
        """Unified entry point for creating a new project."""
        if not self.main.check_and_close_current_project():
            return
        
        self.main.reset_all_managers()

        dlg = ProjectTypeDialog(self.main)
        if dlg.exec():
            self.main.project_nav_controller.create_new_project(dlg.selected_mode)

    def import_annotations(self):
        """Global entry point for loading a JSON file."""
        if not self.main.check_and_close_current_project():
            return
        
        # [NEW] Reset all mode UIs before loading new data to prevent "Ghost UI" bugs
        self.main.reset_all_managers()
        
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

        if not self.main.project_nav_controller.load_project(data, file_path, json_type):
            QMessageBox.critical(self.main, "Error", "Unknown JSON format or Task Type.")

    def close_project(self):
        """Handles closing the current project."""
        self.main.project_nav_controller.close_project()

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