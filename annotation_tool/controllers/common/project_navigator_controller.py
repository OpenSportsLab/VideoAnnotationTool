import os
from PyQt6.QtCore import Qt, QModelIndex, pyqtSignal, QObject
from PyQt6.QtWidgets import QMessageBox

from models.project_tree import ProjectTreeModel
from controllers.media_controller import MediaController
from utils import natural_sort_key

from controllers.classification.class_file_manager import ClassFileManager
from controllers.localization.loc_file_manager import LocFileManager
from controllers.description.desc_file_manager import DescFileManager
from controllers.dense_description.dense_file_manager import DenseFileManager

class ProjectNavigatorController(QObject):
    """
    The Controller in the Panel-Model-Controller architecture for the Project Navigator.
    Coordinates between ProjectNavigatorPanel (View), ProjectTreeModel (UI Model),
    and AppStateModel (Data Model).
    """
    
    def __init__(self, main_window, panel, tree_model, app_state, media_controller):
        super().__init__()
        self.main = main_window
        self.panel = panel
        self.tree_model = tree_model
        self.app_state = app_state
        self.media_controller = media_controller
        
        # [NEW] File Managers (File Navigation Controller Role)
        self.class_fm = ClassFileManager(main_window)
        self.loc_fm = LocFileManager(main_window)
        self.desc_fm = DescFileManager(main_window)
        self.dense_fm = DenseFileManager(main_window)
        
        self._setup_connections()

    def _setup_connections(self):
        """Connect Panel signals to Controller slots."""
        self.panel.addVideoRequested.connect(self.handle_add_video)
        self.panel.clear_btn.clicked.connect(self.handle_clear_workspace)
        self.panel.request_remove_item.connect(self.handle_remove_item)
        self.panel.filter_combo.currentIndexChanged.connect(self.handle_filter_change)
        
        # Selection handling is slightly complex due to mode-switching dispatch in MainWindow,
        # but we can handle the generic tree part here.
        self.panel.tree.selectionModel().currentChanged.connect(self._on_selection_changed)

    def populate_tree(self):
        """
        Populates the ProjectTreeModel from the AppStateModel's action_item_data.
        This is the core 'loading' logic for the navigator.
        """
        self.tree_model.clear()
        self.app_state.action_item_map.clear()
        
        # Sort items by name naturally
        sorted_list = sorted(
            self.app_state.action_item_data, 
            key=lambda d: natural_sort_key(d.get("name", ""))
        )
        
        # Update external dropdowns if necessary (e.g. classification inference)
        if hasattr(self.main, 'sync_batch_inference_dropdowns'):
            self.main.sync_batch_inference_dropdowns()

        for data in sorted_list:
            path = data["path"]
            name = data["name"]
            sources = data.get("source_files")
            
            # Create entry in UI model
            item = self.tree_model.add_entry(name=name, path=path, source_files=sources)
            
            # Map path to item for status updates (icons)
            self.app_state.action_item_map[path] = item
            
            # Update the 'Done' icon based on existing annotations
            self.update_item_status(path)
            
        # Apply current filter
        self.handle_filter_change(self.panel.filter_combo.currentIndex())
        
        # Auto-select first item if possible
        if self.tree_model.rowCount() > 0:
            first_index = self.tree_model.index(0, 0)
            if first_index.isValid():
                self.panel.tree.setCurrentIndex(first_index)

    def update_item_status(self, action_path: str):
        """Updates the icon (done/not done) for a specific item."""
        item = self.app_state.action_item_map.get(action_path)
        if not item:
            return
            
        is_done = False
        # The logic for 'is_done' depends on the active mode in AppState
        # Here we use a generic check across all possible annotation storage
        if action_path in self.app_state.localization_events:
            is_done = len(self.app_state.localization_events[action_path]) > 0
        elif action_path in self.app_state.manual_annotations:
            is_done = len(self.app_state.manual_annotations[action_path]) > 0
        elif action_path in self.app_state.dense_description_events:
            is_done = len(self.app_state.dense_description_events[action_path]) > 0
        # Check descriptions/captions if in description data
        for d in self.app_state.action_item_data:
            if d.get("path") == action_path:
                if any(c.get("text", "").strip() for c in d.get("captions", [])):
                    is_done = True
                break
        
        # Use main_window's cached icons if available
        done_icon = getattr(self.main, 'done_icon', None)
        empty_icon = getattr(self.main, 'empty_icon', None)
        
        if done_icon and empty_icon:
            item.setIcon(done_icon if is_done else empty_icon)

    def handle_add_video(self):
        """Dispatcher for adding videos, delegates to main window for mode-aware logic."""
        self.main._dispatch_add_video()

    def handle_clear_workspace(self):
        """Dispatcher for clearing workspace."""
        self.main._dispatch_clear_workspace()

    def handle_remove_item(self, index: QModelIndex):
        """Dispatcher for removing an item from the project."""
        self.main._on_remove_item_requested(index)

    def handle_filter_change(self, index):
        """Dispatcher for filter changes."""
        self.main._dispatch_filter_change(index)

    def _on_selection_changed(self, current, previous):
        """Initial selection handling before dispatching to global mode managers."""
        self.main._on_tree_selection_changed(current, previous)

    # ---------------------------------------------------------------------
    # Project Lifecycle (File Navigation Controller)
    # ---------------------------------------------------------------------
    def load_project(self, data, file_path, json_type):
        """Unified entry point for loading a project based on its detected type."""
        if json_type == "classification":
            if self.class_fm.load_project(data, file_path):
                self.main.show_classification_view()
                return True
        elif json_type == "localization":
            if self.loc_fm.load_project(data, file_path):
                self.main.show_localization_view()
                return True
        elif json_type == "description":
            if self.desc_fm.load_project(data, file_path):
                self.main.show_description_view()
                return True
        elif json_type == "dense_description":
            if self.dense_fm.load_project(data, file_path):
                self.main.show_dense_description_view()
                return True
        return False

    def create_new_project(self, mode):
        """Unified entry point for creating a new project of a specific mode."""
        if mode == "classification":
            self.class_fm.create_new_project()
        elif mode == "localization":
            self.loc_fm.create_new_project()
        elif mode == "description":
            self.desc_fm.create_new_project()
        elif mode == "dense_description":
            self.dense_fm.create_new_project()

    def save_project(self):
        """Unified entry point for saving the current project."""
        mode_idx = self.main.right_tabs.currentIndex()
        if mode_idx == 1: # Localization
            return self.loc_fm.overwrite_json()
        elif mode_idx == 2: # Description
            self.main.desc_annot_manager.save_current_annotation()
            return self.desc_fm.save_json()
        elif mode_idx == 3: # Dense
            return self.dense_fm.overwrite_json()
        else: # Classification (Default)
            return self.class_fm.save_json()

    def export_project(self):
        """Unified entry point for exporting a project to a new file."""
        mode_idx = self.main.right_tabs.currentIndex()
        if mode_idx == 1:
            return self.loc_fm.export_json()
        elif mode_idx == 2:
            return self.desc_fm.export_json()
        elif mode_idx == 3:
            return self.dense_fm.export_json()
        else:
            return self.class_fm.export_json()

    def close_project(self):
        """Handles project closure and workspace cleanup."""
        if not self.main.check_and_close_current_project():
            return

        self.main.reset_all_managers()

        # Full reset across all managers
        self.class_fm._clear_workspace(full_reset=True)
        self.loc_fm._clear_workspace(full_reset=True)
        self.desc_fm._clear_workspace(full_reset=True)
        self.dense_fm._clear_workspace(full_reset=True)

        self.main.show_welcome_view()
        self.main.show_temp_msg("Project Closed", "Returned to Home Screen", duration=1000)
