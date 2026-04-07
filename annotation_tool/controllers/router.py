import json
import os
from typing import List

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from ui.dialogs import ProjectTypeDialog


class AppRouter:
    """
    Handles application entry points and routing:
    1. Open JSON / Create New Project
    2. Determine Mode (Classification vs Localization vs Description vs Dense)
    3. Delegate to specific Managers
    4. Handle Project Closure
    """
    SETTINGS_ORG = "OpenSportsLab"
    SETTINGS_APP = "VideoAnnotationTool"
    RECENT_DATASETS_KEY = "welcome/recent_datasets"
    MAX_RECENT_DATASETS_DISPLAY = 10

    def __init__(self, main_window):
        self.main = main_window
        self.settings = QSettings(
            self.SETTINGS_ORG,
            self.SETTINGS_APP,
        )

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
        file_path, _ = QFileDialog.getOpenFileName(
            self.main, "Select Project JSON", "", "JSON Files (*.json)"
        )
        if not file_path:
            return

        self.open_project_from_path(file_path)

    def close_project(self):
        """Handles closing the current project."""
        self.main.dataset_explorer_controller.close_project()

    def open_project_from_path(self, file_path: str) -> bool:
        """
        Open a project JSON from a concrete path.
        Returns True when the dataset was loaded successfully.
        """
        normalized_path = self._normalize_project_path(file_path)
        if not normalized_path:
            return False

        if not os.path.exists(normalized_path):
            QMessageBox.warning(
                self.main,
                "Dataset Not Found",
                f"Dataset file does not exist and will be removed from recents:\n{normalized_path}",
            )
            self._remove_recent_project(normalized_path)
            return False

        if not self.main.check_and_close_current_project():
            return False

        # Reset all mode UIs before loading new data to prevent ghost state.
        self.main.reset_all_managers()

        try:
            with open(normalized_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            QMessageBox.critical(self.main, "Error", f"Invalid JSON: {exc}")
            return False

        loaded = self.main.dataset_explorer_controller.load_project(data, normalized_path)
        if not loaded:
            QMessageBox.critical(self.main, "Error", "Unknown JSON format or Task Type.")
            return False

        self._add_recent_project(normalized_path)
        return True

    def get_recent_projects(self) -> List[str]:
        """
        Return recent datasets for UI display (newest first, max 5).
        """
        return self._read_recent_projects()[: self.MAX_RECENT_DATASETS_DISPLAY]

    def get_max_recent_datasets_displayed(self) -> int:
        """
        Return the maximum number of recent datasets to display in the UI.
        """
        return self.MAX_RECENT_DATASETS_DISPLAY

    def remove_all_recent_project(self):
        self.settings.setValue(self.RECENT_DATASETS_KEY, [])
        self.settings.sync()

    def remove_recent_project(self, path: str):
        """Public API for removing one recent dataset entry."""
        self._remove_recent_project(path)

    def _read_recent_projects(self) -> List[str]:
        raw_value = self.settings.value(self.RECENT_DATASETS_KEY, [])

        if isinstance(raw_value, str):
            paths = [raw_value]
        elif isinstance(raw_value, (list, tuple)):
            paths = [str(path) for path in raw_value if path]
        else:
            paths = []

        return [self._normalize_project_path(path) for path in paths if path]

    def _add_recent_project(self, path: str):
        normalized_path = self._normalize_project_path(path)
        if not normalized_path:
            return

        existing = self._read_recent_projects()
        target_key = self._path_key(normalized_path)
        deduped = [p for p in existing if self._path_key(p) != target_key]
        # Persist full deduplicated history; UI display limits to MAX_RECENT_DATASETS_DISPLAY.
        updated = [normalized_path, *deduped]
        self._write_recent_projects(updated)

    def _remove_recent_project(self, path: str):
        normalized_path = self._normalize_project_path(path)
        if not normalized_path:
            return

        target_key = self._path_key(normalized_path)
        updated = [p for p in self._read_recent_projects() if self._path_key(p) != target_key]
        self._write_recent_projects(updated)

    def _write_recent_projects(self, paths: List[str]):
        self.settings.setValue(self.RECENT_DATASETS_KEY, paths)
        self.settings.sync()


    def _normalize_project_path(self, path: str) -> str:
        if not path:
            return ""
        return os.path.abspath(os.path.normpath(path))

    def _path_key(self, path: str) -> str:
        return os.path.normcase(os.path.normpath(path))
