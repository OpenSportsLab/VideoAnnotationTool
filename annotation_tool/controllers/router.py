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
            self.main.dataset_explorer_controller.create_new_project(dlg.selected_mode)

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

        if not self.main.dataset_explorer_controller.load_project(data, file_path):
            QMessageBox.critical(self.main, "Error", "Unknown JSON format or Task Type.")

    def close_project(self):
        """Handles closing the current project."""
        self.main.dataset_explorer_controller.close_project()
