import os
from PyQt6.QtCore import QModelIndex, QTimer, QUrl
from PyQt6.QtWidgets import QMessageBox, QFileDialog

from models.project_tree import ProjectTreeModel

class DescNavigationManager:
    """
    Handles file navigation, video playback, data addition, and filtering for Description Mode.
    """
    def __init__(self, main_window):
        self.main = main_window
        self.ui = main_window.ui
        self.model = main_window.model

    def setup_connections(self):
        """Called by viewer.py to wire up signals."""
        # Tree Selection
        tree = self.ui.description_ui.left_panel.tree
        tree.selectionModel().currentChanged.connect(self.on_item_selected)

        # Center Panel Controls
        center = self.ui.description_ui.center_panel
        center.play_btn.clicked.connect(center.toggle_play_pause)
        center.prev_action.clicked.connect(self.nav_prev_action)
        center.prev_clip.clicked.connect(self.nav_prev_clip)
        center.next_clip.clicked.connect(self.nav_next_clip)
        center.next_action.clicked.connect(self.nav_next_action)

    def add_items_via_dialog(self):
        """Allows user to add video files to the Description project."""
        if not self.model.json_loaded:
            QMessageBox.warning(self.main, "Warning", "Please create or load a project first.")
            return

        filters = "Media Files (*.mp4 *.avi *.mov *.mkv *.jpg *.jpeg *.png *.bmp);;All Files (*)"
        start_dir = self.model.current_working_directory or ""
        
        files, _ = QFileDialog.getOpenFileNames(self.main, "Select Videos to Add", start_dir, filters)
        if not files: return
        
        if not self.model.current_working_directory:
            self.model.current_working_directory = os.path.dirname(files[0])

        added_count = 0
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
            item = self.main.tree_model.add_entry(name=name, path=file_path, source_files=[file_path])
            self.model.action_item_map[file_path] = item
            added_count += 1
            
        if added_count > 0:
            self.model.is_data_dirty = True
            self.main.show_temp_msg("Added", f"Added {added_count} items.")
            self.main.update_save_export_button_state()
            # Re-apply filter to include new items if applicable
            self.apply_action_filter()

    def on_item_selected(self, current: QModelIndex, previous: QModelIndex):
        """Triggered when user clicks an item in the tree."""
        if not current.isValid(): return

        path = current.data(ProjectTreeModel.FilePathRole)
        model = self.main.tree_model
        
        if model.hasChildren(current):
            first_child_idx = model.index(0, 0, current)
            if first_child_idx.isValid():
                path = first_child_idx.data(ProjectTreeModel.FilePathRole)
            else:
                return 

        cwd = self.model.current_working_directory
        if path and cwd and not os.path.isabs(path):
            full_path = os.path.normpath(os.path.join(cwd, path))
        else:
            full_path = path

        if not full_path or not os.path.exists(full_path):
            return

        center = self.ui.description_ui.center_panel
        player = center.player
        player.stop()
        center.load_video(full_path)
        QTimer.singleShot(150, player.play)

    def apply_action_filter(self):
        """
        [NEW] Filters the tree items based on Done/Not Done status.
        Connected to the combo box in Description View.
        """
        idx = self.ui.description_ui.left_panel.filter_combo.currentIndex()
        tree_view = self.ui.description_ui.left_panel.tree
        model = self.main.tree_model
        
        # Access constants from main window
        FILTER_ALL = self.main.FILTER_ALL
        FILTER_DONE = self.main.FILTER_DONE
        FILTER_NOT_DONE = self.main.FILTER_NOT_DONE
        
        root = model.invisibleRootItem()
        for i in range(root.rowCount()):
            item = root.child(i)
            # Use the item's path/ID to find data
            # Note: For description mode, we usually store path in item data
            path = item.data(ProjectTreeModel.FilePathRole)
            
            # Find corresponding data to check status
            # We assume path matches metadata['path'] or id matches text
            is_done = False
            
            # Find data item
            data_item = None
            # Search by path
            for d in self.model.action_item_data:
                if d.get("metadata", {}).get("path") == path:
                    data_item = d
                    break
            
            # Fallback search by ID (text)
            if not data_item:
                for d in self.model.action_item_data:
                    if d.get("id") == item.text():
                        data_item = d
                        break
            
            if data_item:
                captions = data_item.get("captions", [])
                # Consider done if there is at least one caption with text
                if captions and captions[0].get("text", "").strip():
                    is_done = True
            
            should_hide = False
            if idx == FILTER_DONE and not is_done: should_hide = True
            elif idx == FILTER_NOT_DONE and is_done: should_hide = True
            
            tree_view.setRowHidden(i, QModelIndex(), should_hide)

    # --- Navigation Helpers ---
    def nav_prev_action(self): self._nav_tree(step=-1, level='top')
    def nav_next_action(self): self._nav_tree(step=1, level='top')
    def nav_prev_clip(self): self._nav_tree(step=-1, level='child')
    def nav_next_clip(self): self._nav_tree(step=1, level='child')

    def _nav_tree(self, step, level):
        tree = self.ui.description_ui.left_panel.tree
        curr = tree.currentIndex()
        if not curr.isValid(): return
        
        model = self.main.tree_model
        
        if level == 'top':
            if curr.parent().isValid(): curr = curr.parent()
            new_row = curr.row() + step
            
            # Bounds check with loop to skip hidden items (filtering support)
            if 0 <= new_row < model.rowCount(QModelIndex()):
                # Simple jump for now, ideally iterate to find visible
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