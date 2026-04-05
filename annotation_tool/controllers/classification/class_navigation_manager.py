import os
from PyQt6.QtWidgets import QMessageBox, QFileDialog, QWidget
from PyQt6.QtCore import Qt, QModelIndex, QTimer
# [Ref] Import from the correct models location
from models.project_tree import ProjectTreeModel
from utils import SUPPORTED_EXTENSIONS
from controllers.media_controller import MediaController

class NavigationManager:
    """
    Handles file navigation (action tree), adding videos, and playback flow 
    for the Classification mode.
    Refactored for QTreeView (MV) and MediaController.
    """
    def __init__(self, main_window, media_controller: MediaController):
        self.main = main_window
        self.model = main_window.model
        self.media_controller = media_controller

    def add_items_via_dialog(self):
        """
        Allows user to add video/image files to the project.
        Smartly handles SV vs MV based on the loaded JSON flag.
        """
        from PyQt6.QtWidgets import QMessageBox, QFileDialog
        import os
        from collections import defaultdict

        if not self.model.json_loaded:
            QMessageBox.warning(self.main, "Warning", "Please create or load a project first.")
            return

        filters = "Media Files (*.mp4 *.avi *.mov *.mkv *.jpg *.jpeg *.png *.bmp);;All Files (*)"
        start_dir = self.model.current_working_directory or ""
        
        files, _ = QFileDialog.getOpenFileNames(self.main, "Select Data to Add", start_dir, filters)
        if not files: return
        
        if not self.model.current_working_directory:
            self.model.current_working_directory = os.path.dirname(files[0])

        added_count = 0
        
        is_mv = getattr(self.model, 'is_multi_view', False)

        if is_mv:
            grouped_files = defaultdict(list)
            
            for file_path in files:
                dir_name = os.path.dirname(file_path)
                grouped_files[dir_name].append(file_path)
                
            for dir_path, paths in grouped_files.items():
                paths.sort() 
                
                if len(paths) > 1:
                    name = os.path.basename(dir_path)
                else:
                    name = os.path.basename(paths[0])
                
                if any(d['name'] == name for d in self.model.action_item_data):
                    continue
                
                main_path = paths[0]
                self.model.action_item_data.append({'name': name, 'path': main_path, 'source_files': paths})
                
                item = self.main.tree_model.add_entry(name, main_path, paths)
                self.model.action_item_map[main_path] = item
                added_count += 1
                
        else:
            for file_path in files:
                if any(d['path'] == file_path for d in self.model.action_item_data):
                    continue
                
                name = os.path.basename(file_path)
                self.model.action_item_data.append({'name': name, 'path': file_path, 'source_files': [file_path]})
                
                item = self.main.tree_model.add_entry(name, file_path, [file_path])
                self.model.action_item_map[file_path] = item
                added_count += 1
            
        if added_count > 0:
            self.model.is_data_dirty = True
            self.apply_action_filter()
            self.main.show_temp_msg("Added", f"Added {added_count} items.")

            # [NEW] Force Smart Annotation dropdowns to update with the new videos
            self.main.sync_batch_inference_dropdowns()

    def remove_single_action_item(self, index: QModelIndex):
        """
        Removes an item given its QModelIndex.
        """
        path = index.data(ProjectTreeModel.FilePathRole)
        
        # 1. Remove from Data
        self.model.action_item_data = [d for d in self.model.action_item_data if d['path'] != path]
        
        if path in self.model.action_item_map:
            del self.model.action_item_map[path]
            
        # 2. Remove Annotation if exists
        if path in self.model.manual_annotations:
            del self.model.manual_annotations[path]
            
        # 3. Remove from UI (Model)
        self.main.tree_model.removeRow(index.row(), index.parent())
        
        self.model.is_data_dirty = True
        self.main.show_temp_msg("Removed", "Item removed.")
        self.main.update_save_export_button_state()

        # [NEW] Force Smart Annotation dropdowns to update after deletion
        self.main.sync_batch_inference_dropdowns()

    def on_item_selected(self, current, previous):
        """
        Called when the user clicks a different item in the left tree.
        Loads the video and forces playback using MediaController.
        """
        if not current.isValid(): return
        
        path = current.data(ProjectTreeModel.FilePathRole)

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
        tree_view = self.main.left_panel.tree
        curr_idx = tree_view.currentIndex()
        if not curr_idx.isValid(): return
        
        # Check if item has children rows
        model = self.main.tree_model
        if model.rowCount(curr_idx) == 0: return
        
        paths = []
        for i in range(model.rowCount(curr_idx)):
            child_idx = model.index(i, 0, curr_idx)
            paths.append(child_idx.data(ProjectTreeModel.FilePathRole))
            
        self.main.center_panel.media_preview.show_all_views([p for p in paths if p.lower().endswith(SUPPORTED_EXTENSIONS[:3])])

    def apply_action_filter(self, index=None):
        """
        Filter the tree based on 4 custom states for Classification.
        0: Show All
        1: Hand Labelled (Has manual annotation)
        2: Smart Labelled (Has confirmed smart annotation)
        3: No Labelled (Neither hand nor smart confirmed)
        """
        tree = self.main.left_panel.tree
        combo = self.main.left_panel.filter_combo
        
        # Use the passed index from the signal, or the current combo box index
        filter_idx = combo.currentIndex() if index is None else index
        if filter_idx < 0: return
        
        model = self.main.tree_model
        
        for row in range(model.rowCount()):
            idx = model.index(row, 0)
            item = model.itemFromIndex(idx)
            if not item: continue
                
            path = item.data(ProjectTreeModel.FilePathRole)
            
            # 1. Is it Hand Labelled? (Exists in manual_annotations)
            is_hand_labelled = path in self.model.manual_annotations and bool(self.model.manual_annotations[path])
            
            # 2. Is it Smart Labelled? (Has _confirmed flag in smart_annotations)
            smart_data = self.model.smart_annotations.get(path, {})
            # [MODIFIED] Removed the mutually exclusive condition "and not is_hand_labelled".
            # Now an item can be treated as both Hand Labelled and Smart Labelled simultaneously.
            is_smart_labelled = smart_data.get("_confirmed", False)
            
            # 3. No Labelled (Neither hand nor smart confirmed)
            is_no_labelled = not is_hand_labelled and not is_smart_labelled
            
            # 4. Apply hiding logic based on the selected filter index
            hidden = False
            if filter_idx == 1 and not is_hand_labelled:
                # Hide if "Hand Labelled" is selected but the item lacks hand labels
                hidden = True
            elif filter_idx == 2 and not is_smart_labelled:
                # Hide if "Smart Labelled" is selected but the item lacks smart labels
                hidden = True
            elif filter_idx == 3 and not is_no_labelled:
                # Hide if "No Labelled" is selected but the item has ANY label
                hidden = True
                
            tree.setRowHidden(row, QModelIndex(), hidden)

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
