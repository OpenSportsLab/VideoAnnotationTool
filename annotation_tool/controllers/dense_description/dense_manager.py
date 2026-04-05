import os
import copy
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor

from models import CmdType 
from controllers.media_controller import MediaController

class DenseManager:
    """
    Controller for Dense Description mode.
    Handles free-text annotation at specific timestamps, synchronized with video and timeline.
    """
    def __init__(self, main_window, media_controller: MediaController):
        self.main = main_window
        self.model = main_window.model
        self.tree_model = main_window.tree_model 
        
        # Access UI components from the Dense Description view
        self.dataset_explorer_panel = main_window.dataset_explorer_panel
        self.center_panel = main_window.center_panel
        self.right_panel = main_window.dense_panel
        
        # Media Controller setup
        self.media_controller = media_controller
        
        self.current_video_path = None
        
        # Timer to throttle text updates during playback/scrubbing
        self.sync_timer = QTimer(self.main)
        self.sync_timer.setSingleShot(True)
        self.sync_timer.setInterval(100)
        self.sync_timer.timeout.connect(self._sync_editor_to_timeline)

    def reset_ui(self):
        """Reset the dense description editor UI for a new project."""
        self.right_panel.table.set_data([])
        self.right_panel.input_widget.set_text("")
        self.right_panel.setEnabled(False)
        self.current_video_path = None

    def setup_connections(self):
        """Link UI signals to logic handlers."""
        # --- Left Panel (Clip Tree) handled centrally in main_window.py ---
        
        # --- Center Panel (Playback & Timeline) ---
        media = self.center_panel.media_preview
        timeline = self.center_panel.timeline
        pb = self.center_panel.playback
        
        media.positionChanged.connect(self._on_media_position_changed)
        
        # --- Right Panel (Text Input & Table) ---
        input_w = self.right_panel.input_widget
        table = self.right_panel.table
        
        # Handle "Confirm Description" button
        input_w.descriptionSubmitted.connect(self._on_description_submitted)
        
        # Table interactions
        table.annotationSelected.connect(self._on_event_selected_from_table)
        table.annotationDeleted.connect(self._on_delete_single_annotation)
        table.annotationModified.connect(self._on_annotation_modified)

    def _on_media_position_changed(self, ms):
        """Update timeline and the time label in the input widget."""
        self.center_panel.timeline.set_position(ms)
        time_str = self._fmt_ms_full(ms)
        self.right_panel.input_widget.update_time(time_str)
        
        # Try to sync editor text if playback stops or during scrub
        if not self.sync_timer.isActive():
            self.sync_timer.start()

    def _on_clip_selected(self, current_idx, previous_idx):
        """Load video and refresh annotations when a tree item is clicked."""
        if not current_idx.isValid(): 
            self.current_video_path = None
            return
        
        path = current_idx.data(Qt.ItemDataRole.UserRole)
        if path == self.current_video_path: return
            
        if path and os.path.exists(path):
            self.current_video_path = path
            
            # Clear editor first to avoid ghost text from previous video
            self.right_panel.input_widget.set_text("")
            
            self.media_controller.load_and_play(path)
            self._display_events_for_item(path)
        else:
            if path: QMessageBox.warning(self.main, "Error", f"File not found: {path}")

    def _on_event_selected_from_table(self, ms):
        """
        Called when user clicks a row in the table.
        1. Seek video to timestamp.
        2. Populate input widget with the text of that event.
        """
        # 1. Seek
        self.center_panel.media_preview.set_position(ms)
        
        # 2. Sync Editor (Force immediate sync)
        self._sync_editor_to_timeline()

    def _on_description_submitted(self, text):
        """
        Logic for adding OR updating an annotation.
        If an event exists at the current time (within tolerance), update it.
        Otherwise, add a new one.
        """
        if not self.current_video_path:
            QMessageBox.warning(self.main, "Warning", "Please select a video first.")
            return
            
        pos_ms = self.center_panel.media_preview.player.position()
        events = self.model.dense_description_events.get(self.current_video_path, [])
        
        tolerance = 50 
        existing_event = None
        existing_index = -1
        
        for i, e in enumerate(events):
            if abs(e['position_ms'] - pos_ms) <= tolerance:
                existing_event = e
                existing_index = i
                break
        
        if existing_event:
            # --- MODIFY EXISTING EVENT ---
            if existing_event['text'] == text:
                return # No change
                
            new_event = copy.deepcopy(existing_event)
            new_event['text'] = text
            
            self.model.push_undo(CmdType.DENSE_EVENT_MOD, 
                                video_path=self.current_video_path, 
                                old_event=copy.deepcopy(existing_event), 
                                new_event=new_event)
            
            events[existing_index] = new_event
            self.main.show_temp_msg("Updated", "Description updated.")
            # [FIX] Do NOT clear input widget here, user wants to see the updated text.
            
        else:
            # --- ADD NEW EVENT ---
            new_event = {
                "position_ms": pos_ms,
                "lang": "en", 
                "text": text
            }
            
            self.model.push_undo(CmdType.DENSE_EVENT_ADD, video_path=self.current_video_path, event=new_event)
            
            if self.current_video_path not in self.model.dense_description_events:
                self.model.dense_description_events[self.current_video_path] = []
                
            self.model.dense_description_events[self.current_video_path].append(new_event)
            self.main.show_temp_msg("Added", "Dense description created.")
            
            # [FIX] Clear input widget ONLY on Add
            self.right_panel.input_widget.set_text("")

        # Common Update Logic
        self.model.is_data_dirty = True
        self._display_events_for_item(self.current_video_path)
        self.main.update_action_item_status(self.current_video_path)
        self.main.update_save_export_button_state()

    def _display_events_for_item(self, path):
        """Refresh the table and timeline markers for the current video."""
        # [FIX] 1. Capture current selection (if any) before resetting model
        current_selection_ms = None
        indexes = self.right_panel.table.table.selectionModel().selectedRows()
        if indexes:
            # Get the object from the model before it changes
            row = indexes[0].row()
            item = self.right_panel.table.model.get_annotation_at(row)
            if item:
                current_selection_ms = item.get('position_ms')

        # 2. Update Data
        events = self.model.dense_description_events.get(path, [])
        sorted_events = sorted(events, key=lambda x: x.get('position_ms', 0))
        
        self.right_panel.table.set_data(sorted_events)
        
        markers = [{'start_ms': e.get('position_ms', 0), 'color': QColor("#FFD700")} for e in sorted_events]
        self.center_panel.timeline.set_markers(markers)
        
        # [FIX] 3. Restore Selection
        if current_selection_ms is not None:
            self._select_row_by_time(current_selection_ms)

        # 4. Sync Editor
        if path == self.current_video_path:
            self._sync_editor_to_timeline()

    def _sync_editor_to_timeline(self):
        """
        Checks if there is an event at the current playback position.
        If yes, populates the editor with its text.
        """
        if not self.current_video_path: return
        
        current_ms = self.center_panel.media_preview.player.position()
        events = self.model.dense_description_events.get(self.current_video_path, [])
        
        # Same tolerance as submission
        tolerance = 50 
        target_text = ""
        found = False
        
        for e in events:
            if abs(e['position_ms'] - current_ms) <= tolerance:
                target_text = e['text']
                found = True
                break
        
        # Update UI only if changed to avoid cursor jumping
        # Only update if we found an event. If we didn't find one, we keep the text 
        # (user might be typing a new one, or we just undid an Add).
        if found:
            current_ui_text = self.right_panel.input_widget.text_editor.toPlainText()
            if current_ui_text != target_text:
                self.right_panel.input_widget.set_text(target_text)

    def _on_annotation_modified(self, old_event, new_event):
        """Handles direct edits within the table cells."""
        events = self.model.dense_description_events.get(self.current_video_path, [])
        try:
            index = events.index(old_event)
        except ValueError:
            return 
            
        self.model.push_undo(CmdType.DENSE_EVENT_MOD, 
                            video_path=self.current_video_path, 
                            old_event=copy.deepcopy(old_event), 
                            new_event=new_event)
        
        events[index] = new_event
        self.model.is_data_dirty = True
        
        # Defer display refresh to fix QAbstractItemView error
        QTimer.singleShot(0, lambda: self._display_events_for_item(self.current_video_path))
        
        self.main.show_temp_msg("Updated", "Description modified.")
        self.main.update_save_export_button_state()

    def _on_delete_single_annotation(self, item_data):
        """Handles the deletion of a specific description point."""
        events = self.model.dense_description_events.get(self.current_video_path, [])
        if item_data not in events: return
        
        self.model.push_undo(CmdType.DENSE_EVENT_DEL, video_path=self.current_video_path, event=copy.deepcopy(item_data))
        events.remove(item_data)
        self.model.is_data_dirty = True
        self._display_events_for_item(self.current_video_path)
        self.main.update_action_item_status(self.current_video_path)
        self.main.update_save_export_button_state()
        self.right_panel.input_widget.set_text("") # Clear editor on delete

    def _navigate_clip(self, step):
        tree = self.dataset_explorer_panel.tree
        curr = tree.currentIndex()
        if not curr.isValid(): return
        nxt = tree.indexBelow(curr) if step > 0 else tree.indexAbove(curr)
        if nxt.isValid(): tree.setCurrentIndex(nxt)

    def _navigate_annotation(self, step):
        events = self.model.dense_description_events.get(self.current_video_path, [])
        if not events: return
        sorted_evts = sorted(events, key=lambda x: x.get('position_ms', 0))
        cur_pos = self.center_panel.media_preview.player.position()
        target = None
        if step > 0:
            for e in sorted_evts:
                if e['position_ms'] > cur_pos + 100: target = e; break
        else:
            for e in reversed(sorted_evts):
                if e['position_ms'] < cur_pos - 100: target = e; break
        
        if target is not None: 
            self.center_panel.media_preview.set_position(target['position_ms'])
            # Ensure navigation also populates the text box
            self._select_row_by_time(target['position_ms'])
            self.right_panel.input_widget.set_text(target['text'])

    def _select_row_by_time(self, time_ms):
        """Selects the row in the table that matches the given timestamp."""
        model = self.right_panel.table.model
        for row in range(model.rowCount()):
            item = model.get_annotation_at(row)
            if item and abs(item.get('position_ms', 0) - time_ms) < 20:
                self.right_panel.table.table.selectRow(row)
                break

    def _fmt_ms_full(self, ms):
        s = ms // 1000
        m = s // 60
        h = m // 60
        return f"{h:02}:{m%60:02}:{s%60:02}.{ms%1000:03}"
