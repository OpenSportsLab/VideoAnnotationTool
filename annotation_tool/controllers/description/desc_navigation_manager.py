import os
from PyQt6.QtCore import QModelIndex

# [Ref] Import the Unified MediaController
from controllers.media_controller import MediaController

class DescNavigationManager:
    """
    Handles file navigation and video playback for Description mode.
    Refactored to STRICTLY follow Classification playback logic (No Looping) and pass video_widget for proper clearing.
    """
    def __init__(self, main_window, media_controller: MediaController):
        self.main = main_window
        self.model = main_window.model
        self.media_controller = media_controller
        
        # [CRITICAL] Disable looping to match Classification stability
        # self.media_controller.set_looping(True) 

    def reset_ui(self):
        """Reset the description editor UI for a new project."""
        self.main.description_panel.caption_edit.setPlainText("")
        self.main.description_panel.setEnabled(False)

    def setup_connections(self):
        """Called by main_window.py to wire up signals."""
        # [UPDATED] Tree selection and Unified Center Panel Controls are now handled centrally in main_window.py
        pass

    def toggle_play_pause(self):
        """Delegate play/pause to the controller."""
        self.media_controller.toggle_play_pause()

    def on_item_selected(self, current: QModelIndex, previous: QModelIndex):
        """
        Triggered when user clicks an item in the tree.
        Uses MediaController to load video smoothly.
        """
        if not current.isValid(): return

        path = current.data(self.main.tree_model.FilePathRole)
        model = self.main.tree_model
        
        # Handle folder selection: try to play first child
        if model.hasChildren(current):
            first_child_idx = model.index(0, 0, current)
            if first_child_idx.isValid():
                path = first_child_idx.data(self.main.tree_model.FilePathRole)
            else:
                return 

        # Resolve absolute path
        cwd = self.model.current_working_directory
        if path and cwd and not os.path.isabs(path):
            full_path = os.path.normpath(os.path.join(cwd, path))
        else:
            full_path = path

        if not full_path or not os.path.exists(full_path):
            return

        # [CRITICAL] EXACT Classification Logic
        # Stop -> Clear -> Load -> Delay 150ms -> Play
        self.media_controller.load_and_play(full_path)

    # -------------------------------------------------------------------------
    #  Tree Navigation Helpers
    # -------------------------------------------------------------------------
    def nav_prev_action(self): self._nav_tree(step=-1, level='top')
    def nav_next_action(self): self._nav_tree(step=1, level='top')
    def nav_prev_clip(self): self._nav_tree(step=-1, level='child')
    def nav_next_clip(self): self._nav_tree(step=1, level='child')

    def _nav_tree(self, step, level):
        tree = self.main.dataset_explorer_panel.tree
        curr = tree.currentIndex()
        if not curr.isValid(): return
        
        model = self.main.tree_model
        
        if level == 'top':
            if curr.parent().isValid(): curr = curr.parent()
            new_row = curr.row() + step
            
            if 0 <= new_row < model.rowCount(QModelIndex()):
                new_idx = model.index(new_row, 0, QModelIndex())
                tree.setCurrentIndex(new_idx); tree.scrollTo(new_idx)
        
        elif level == 'child':
            parent = curr.parent()
            if not parent.isValid():
                if step == 1 and model.rowCount(curr) > 0:
                    child = model.index(0, 0, curr)
                    tree.setCurrentIndex(child)
                elif step == -1:
                    self.nav_prev_action()
            else:
                new_row = curr.row() + step
                if 0 <= new_row < model.rowCount(parent):
                    new_idx = model.index(new_row, 0, parent)
                    tree.setCurrentIndex(new_idx)
                else:
                    if step == 1: self.nav_next_action()
                    else: self.nav_prev_action()
