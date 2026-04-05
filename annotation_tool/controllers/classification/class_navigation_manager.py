from PyQt6.QtCore import Qt, QModelIndex
from utils import SUPPORTED_EXTENSIONS
from controllers.media_controller import MediaController

class NavigationManager:
    """
    Handles file navigation (action tree) and playback flow for Classification mode.
    Refactored for QTreeView (MV) and MediaController.
    """
    def __init__(self, main_window, media_controller: MediaController):
        self.main = main_window
        self.model = main_window.model
        self.media_controller = media_controller

    def on_item_selected(self, current, previous):
        """
        Called when the user clicks a different item in the left tree.
        Loads the video and forces playback using MediaController.
        """
        if not current.isValid(): return
        
        path = current.data(self.main.tree_model.FilePathRole)

        # Update Right Panel (Annotations)
        self.main.annot_manager.display_manual_annotation(path)
        self.main.classification_panel.manual_box.setEnabled(True)
        
        # [CHANGED] Use MediaController for robust loading logic
        # This replaces the manual stop/load/timer sequence.
        self.media_controller.load_and_play(path)
        
        # [UI FIX] Ensure we are in Single View mode (in case we were in Multi-View)
        center_panel = self.main.center_panel
        if hasattr(center_panel, 'view_layout'):
             center_panel.view_layout.setCurrentWidget(center_panel.single_view_widget)

    def play_video(self):
        """Toggle Play/Pause"""
        # [CHANGED] Use MediaController
        self.media_controller.toggle_play_pause()

    def show_all_views(self):
        # [MV] Handle Multi-View
        tree_view = self.main.dataset_explorer_panel.tree
        curr_idx = tree_view.currentIndex()
        if not curr_idx.isValid(): return
        
        # Check if item has children rows
        model = self.main.tree_model
        if model.rowCount(curr_idx) == 0: return
        
        paths = []
        for i in range(model.rowCount(curr_idx)):
            child_idx = model.index(i, 0, curr_idx)
            paths.append(child_idx.data(self.main.tree_model.FilePathRole))
            
        self.main.center_panel.media_preview.show_all_views([p for p in paths if p.lower().endswith(SUPPORTED_EXTENSIONS[:3])])

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
            # Navigate Top Level Items (Siblings)
            # If current is a child, get parent first
            if curr.parent().isValid():
                curr = curr.parent()
                
            new_row = curr.row() + step
            
            # Simple bounds check, logic can be improved to skip hidden items
            if 0 <= new_row < model.rowCount(QModelIndex()):
                # Check visibility (filter)
                while 0 <= new_row < model.rowCount(QModelIndex()):
                    if not tree.isRowHidden(new_row, QModelIndex()):
                        new_idx = model.index(new_row, 0, QModelIndex())
                        tree.setCurrentIndex(new_idx)
                        tree.scrollTo(new_idx)
                        break
                    new_row += step
        else:
            # Navigate Children
            parent = curr.parent()
            if not parent.isValid():
                # Currently on top, go to child 0 if step 1
                if step == 1 and model.rowCount(curr) > 0:
                    nxt = model.index(0, 0, curr)
                    tree.setCurrentIndex(nxt); tree.scrollTo(nxt)
            else:
                # Currently on child
                new_row = curr.row() + step
                if 0 <= new_row < model.rowCount(parent):
                    nxt = model.index(new_row, 0, parent)
                    tree.setCurrentIndex(nxt); tree.scrollTo(nxt)
