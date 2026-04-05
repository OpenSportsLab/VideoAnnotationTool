import os
from PyQt6.QtCore import QModelIndex
from PyQt6.QtWidgets import QMessageBox, QFileDialog, QWidget

# [Ref] Import Model Roles
from models.project_tree import ProjectTreeModel

# [Ref] Import the Unified MediaController
from controllers.media_controller import MediaController

class DescNavigationManager:
    """
    Handles file navigation, video playback, data addition, and filtering for Description Mode.
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

        path = current.data(ProjectTreeModel.FilePathRole)
        model = self.main.tree_model
        
        # Handle folder selection: try to play first child
        if model.hasChildren(current):
            first_child_idx = model.index(0, 0, current)
            if first_child_idx.isValid():
                path = first_child_idx.data(ProjectTreeModel.FilePathRole)
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
    #  Data Management (Adding items, Filtering)
    # -------------------------------------------------------------------------

    def add_items_via_dialog(self):
        """Allows user to add video files to the Description project."""
        if not self.model.json_loaded:
            QMessageBox.warning(self.main, "Warning", "Please create or load a project first.")
            return

        filters = "Media Files (*.mp4 *.avi *.mov *.mkv *.jpg *.jpeg *.png *.bmp);;All Files (*)"
        start_dir = self.model.current_working_directory or ""
        
        # [FIXED] Call QFileDialog FIRST before accessing 'files'
        files, _ = QFileDialog.getOpenFileNames(self.main, "Select Videos to Add", start_dir, filters)
        if not files: return
        
        if not self.model.current_working_directory:
            self.model.current_working_directory = os.path.dirname(files[0])

        added_count = 0
        first_new_idx = None # [NEW] Track the first new item index

        for file_path in files:
            if any(d.get('metadata', {}).get('path') == file_path for d in self.model.action_item_data):
                continue
            
            name = os.path.basename(file_path)
            
            new_item = {
                "id": name,
                "metadata": {"path": file_path, "questions": []},
                "inputs": [{"type": "video", "name": name, "path": file_path}],
                "captions": []
            }
            
            self.model.action_item_data.append(new_item)
            
            # Add entry to the tree model
            item = self.main.tree_model.add_entry(name=name, path=file_path, source_files=[file_path])
            self.model.action_item_map[file_path] = item
            
            # [NEW] Capture the index of the first added item
            if added_count == 0:
                first_new_idx = item.index()
                
            added_count += 1
            
        if added_count > 0:
            self.model.is_data_dirty = True
            self.main.show_temp_msg("Added", f"Added {added_count} items.")
            self.main.update_save_export_button_state()
            self.apply_action_filter()
            
            # [CRITICAL FIX] Auto-select and play the first added video
            # This triggers on_item_selected -> media_controller.load_and_play
            if first_new_idx and first_new_idx.isValid():
                tree = self.main.left_panel.tree
                tree.setCurrentIndex(first_new_idx)
                tree.setFocus() # Ensure keyboard shortcuts work immediately

    def apply_action_filter(self):
        """Filters the tree items based on Done/Not Done status."""
        idx = self.main.left_panel.filter_combo.currentIndex()
        tree_view = self.main.left_panel.tree
        model = self.main.tree_model
        
        FILTER_DONE = self.main.FILTER_DONE
        FILTER_NOT_DONE = self.main.FILTER_NOT_DONE
        
        root = model.invisibleRootItem()
        for i in range(root.rowCount()):
            item = root.child(i)
            path = item.data(ProjectTreeModel.FilePathRole)
            
            is_done = False
            
            data_item = None
            for d in self.model.action_item_data:
                if d.get("metadata", {}).get("path") == path:
                    data_item = d
                    break
            
            if not data_item:
                for d in self.model.action_item_data:
                    if d.get("id") == item.text():
                        data_item = d
                        break
            
            if data_item:
                captions = data_item.get("captions", [])
                if captions and captions[0].get("text", "").strip():
                    is_done = True
            
            should_hide = False
            if idx == FILTER_DONE and not is_done: should_hide = True
            elif idx == FILTER_NOT_DONE and is_done: should_hide = True
            
            tree_view.setRowHidden(i, QModelIndex(), should_hide)

    # -------------------------------------------------------------------------
    #  Tree Navigation Helpers
    # -------------------------------------------------------------------------
    def nav_prev_action(self): self._nav_tree(step=-1, level='top')
    def nav_next_action(self): self._nav_tree(step=1, level='top')
    def nav_prev_clip(self): self._nav_tree(step=-1, level='child')
    def nav_next_clip(self): self._nav_tree(step=1, level='child')

    def _nav_tree(self, step, level):
        tree = self.main.left_panel.tree
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