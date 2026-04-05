import os
import copy
from PyQt6.QtWidgets import QMessageBox, QInputDialog, QMenu, QFileDialog
from PyQt6.QtCore import Qt, QUrl, QModelIndex, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtMultimedia import QMediaPlayer

from utils import natural_sort_key
from models import CmdType 
# [NEW] Import the unified MediaController
from controllers.media_controller import MediaController
from .loc_inference import LocalizationInferenceManager

class LocalizationManager:
    """
    Manages logic for the UI2 Localization Interface.
    Refactored to support QTreeView + QStandardItemModel (MV Architecture).
    """
    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model
        self.tree_model = main_window.tree_model 
        
        self.ui_root = main_window.ui.localization_ui
        self.left_panel = self.ui_root.left_panel
        self.center_panel = self.ui_root.center_panel
        self.right_panel = self.ui_root.right_panel

        self.inference_manager = LocalizationInferenceManager(self.main)
        self.inference_manager.inference_finished.connect(self._on_inference_success)
        self.inference_manager.inference_error.connect(self._on_inference_error)
        
        # [NEW] Initialize Media Controller
        # We access the underlying QMediaPlayer from the UI wrapper
        preview_widget = self.center_panel.media_preview
        player = preview_widget.player
        
        # [CRITICAL FIX] Retrieve the actual QVideoWidget to allow forced repaints
        # This fixes the "stuck frame" issue when switching modes
        video_widget = preview_widget.video_widget
        
        self.media_controller = MediaController(player, video_widget)
        
        self.current_video_path = None
        self.current_head = None 

    def setup_connections(self):
        # --- Left Panel ---
        # Note: Create/Load/Close/Save/Export are handled by the File menu bar.
        # Add Data is wired from viewer.py -> left_panel.addVideoRequested
        
        # Tree Interactions
        self.left_panel.tree.selectionModel().currentChanged.connect(self.on_clip_selected)
        self.left_panel.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.left_panel.tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self.left_panel.filter_combo.currentIndexChanged.connect(self._apply_clip_filter)
        self.left_panel.clear_btn.clicked.connect(self._on_clear_all_clicked)
        
        # --- Center Panel ---
        media = self.center_panel.media_preview
        timeline = self.center_panel.timeline
        pb = self.center_panel.playback
        
        media.positionChanged.connect(self._on_media_position_changed)
        media.durationChanged.connect(timeline.set_duration)
        timeline.seekRequested.connect(media.set_position)
        
        # Use MediaController for playback control
        pb.stopRequested.connect(self.media_controller.stop)
        pb.playPauseRequested.connect(self.media_controller.toggle_play_pause)
        
        pb.playbackRateRequested.connect(media.set_playback_rate)
        pb.seekRelativeRequested.connect(lambda d: media.set_position(media.player.position() + d))
        
        pb.nextPrevClipRequested.connect(self._navigate_clip)
        pb.nextPrevAnnotRequested.connect(self._navigate_annotation)
        
        # --- Right Panel ---
        #Smart Annotation UI
        if hasattr(self.right_panel, 'smart_widget'):
            smart_ui = self.right_panel.smart_widget
            smart_ui.setTimeRequested.connect(self._on_smart_set_time)
            smart_ui.runInferenceRequested.connect(self._run_localization_inference)
            smart_ui.confirmSmartRequested.connect(self._confirm_smart_events)
            smart_ui.clearSmartRequested.connect(self._clear_smart_events)
            
            # Tab switch to toggle timeline markers
            self.right_panel.tabs.currentChanged.connect(self._on_tab_switched)


        tabs = self.right_panel.annot_mgmt.tabs
        table = self.right_panel.table
        
        tabs.headAdded.connect(self._on_head_added)
        tabs.headRenamed.connect(self._on_head_renamed)
        tabs.headDeleted.connect(self._on_head_deleted)
        tabs.headSelected.connect(self._on_head_selected)
        
        tabs.spottingTriggered.connect(self._on_spotting_triggered)
        tabs.labelAddReq.connect(self._on_label_add_req)
        tabs.labelRenameReq.connect(self._on_label_rename_req)
        tabs.labelDeleteReq.connect(self._on_label_delete_req)
        
        table.annotationSelected.connect(lambda ms: media.set_position(ms))
        table.annotationDeleted.connect(self._on_delete_single_annotation)
        table.annotationModified.connect(self._on_annotation_modified)

        table.updateTimeForSelectedRequested.connect(self._on_update_time_for_selected)

    def _on_media_position_changed(self, ms):
        self.center_panel.timeline.set_position(ms)
        time_str = self._fmt_ms_full(ms)
        self.right_panel.annot_mgmt.tabs.update_current_time(time_str)

    def _on_update_time_for_selected(self, old_event):
        """
            Handles the logic when the user clicks the
            'Set to Current Video Time' button.
        """
        if not self.current_video_path:
            return

        # 1. Get the current playback position in milliseconds
        current_ms = self.center_panel.media_preview.player.position()

        # 2. Copy the old event and update its timestamp
        new_event = old_event.copy()
        new_event['position_ms'] = current_ms

        # 3. Reuse the existing modification logic
        self._on_annotation_modified(old_event, new_event)


    # --- Video Loading Logic (Strict Classification Style via Controller) ---
    def on_clip_selected(self, current_idx, previous_idx):
        if not current_idx.isValid(): 
            self.current_video_path = None
            return
        
        path = current_idx.data(Qt.ItemDataRole.UserRole)
        
        if path == self.current_video_path: 
            return
            
        if path and os.path.exists(path):
            self.current_video_path = path
            
            # [CHANGED] Use MediaController for standardized playback
            # This handles the Stop -> Load -> Delay -> Play sequence automatically
            self.media_controller.load_and_play(path)
            
            # Update UI for events
            self._display_events_for_item(path)
            
        else:
            if path: QMessageBox.warning(self.main, "Error", f"File not found: {path}")

    def _on_add_video_clicked(self):
        start_dir = self.model.current_working_directory or ""
        files, _ = QFileDialog.getOpenFileNames(self.main, "Select Video(s)", start_dir, "Video (*.mp4 *.avi *.mov *.mkv)")
        if not files: return
        if not self.model.current_working_directory:
            self.model.current_working_directory = os.path.dirname(files[0])
        
        added_count = 0
        first_new_item_idx = None 

        for file_path in files:
            if any(d['path'] == file_path for d in self.model.action_item_data):
                continue
            
            name = os.path.basename(file_path)
            self.model.action_item_data.append({'name': name, 'path': file_path, 'source_files': [file_path]})
            self.model.action_path_to_name[file_path] = name
            item = self.tree_model.add_entry(name=name, path=file_path, source_files=[file_path])
            self.model.action_item_map[file_path] = item
            
            if added_count == 0:
                first_new_item_idx = item.index()
            added_count += 1

        if added_count > 0:
            self.model.is_data_dirty = True
            self.main.show_temp_msg("Videos Added", f"Added {added_count} clips.")
            
            # Auto-select the first added video
            if first_new_item_idx and first_new_item_idx.isValid():
                self.left_panel.tree.setCurrentIndex(first_new_item_idx)
                # Manually trigger load since setting index via code sometimes skips the signal
                self.on_clip_selected(first_new_item_idx, None)

    # --- Head Management ---
    def handle_add_head(self):
        text, ok = QInputDialog.getText(self.main, "New Category", "Enter name for new Category (Head):")
        if ok and text.strip(): self._on_head_added(text.strip())

    def _on_head_selected(self, head_name): self.current_head = head_name

    def _on_head_added(self, head_name):
        if any(h.lower() == head_name.lower() for h in self.model.label_definitions):
            self.main.show_temp_msg("Error", f"Head '{head_name}' already exists!", icon=QMessageBox.Icon.Warning); return
        definition = {"type": "single_label", "labels": []}
        self.model.push_undo(CmdType.SCHEMA_ADD_CAT, head=head_name, definition=definition)
        self.model.label_definitions[head_name] = definition
        self.model.is_data_dirty = True
        self._refresh_schema_ui()
        self.right_panel.annot_mgmt.tabs.set_current_head(head_name)
        self.main.show_temp_msg("Head Added", f"Created '{head_name}'")
        self.main.update_save_export_button_state() 

    def _on_head_renamed(self, old_name, new_name):
        if old_name == new_name: return
        if any(h.lower() == new_name.lower() for h in self.model.label_definitions):
            self.main.show_temp_msg("Error", "Name already exists!", icon=QMessageBox.Icon.Warning); return
        self.model.push_undo(CmdType.SCHEMA_REN_CAT, old_name=old_name, new_name=new_name)
        self.model.label_definitions[new_name] = self.model.label_definitions.pop(old_name)
        for vid_path, events in self.model.localization_events.items():
            for evt in events:
                if evt.get('head') == old_name: evt['head'] = new_name
        self.model.is_data_dirty = True
        self._refresh_schema_ui()
        self.right_panel.annot_mgmt.tabs.set_current_head(new_name)
        self._refresh_current_clip_events()
        self.main.show_temp_msg("Head Renamed", "Updated events.")
        self.main.update_save_export_button_state() 

    def _on_head_deleted(self, head_name):
        res = QMessageBox.warning(self.main, "Delete Head", f"Delete head '{head_name}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if res != QMessageBox.StandardButton.Yes: return
        loc_affected = {}
        for vid_path, events in self.model.localization_events.items():
            affected_evts = [copy.deepcopy(e) for e in events if e.get('head') == head_name]
            if affected_evts: loc_affected[vid_path] = affected_evts
        definition = copy.deepcopy(self.model.label_definitions.get(head_name))
        self.model.push_undo(CmdType.SCHEMA_DEL_CAT, head=head_name, definition=definition, loc_affected_events=loc_affected)
        del self.model.label_definitions[head_name]
        for vid_path in self.model.localization_events:
            self.model.localization_events[vid_path] = [e for e in self.model.localization_events[vid_path] if e.get('head') != head_name]
        self.model.is_data_dirty = True
        self._refresh_schema_ui()
        self._refresh_current_clip_events()
        self.main.show_temp_msg("Head Deleted", "Removed.")
        self.main.update_save_export_button_state() 

    # --- Label Management ---
    def _on_label_add_req(self, head):
        player = self.center_panel.media_preview.player
        was_playing = (player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        if was_playing: player.pause()
        current_pos = player.position()
        text, ok = QInputDialog.getText(self.main, "Add Label", f"Add label to '{head}':")
        if not ok or not text.strip():
            if was_playing: player.play()
            return
        label_name = text.strip()
        labels_list = self.model.label_definitions[head].get('labels', [])
        if any(l.lower() == label_name.lower() for l in labels_list):
            self.main.show_temp_msg("Error", "Label exists!", icon=QMessageBox.Icon.Warning)
            if was_playing: player.play()
            return
        self.model.push_undo(CmdType.SCHEMA_ADD_LBL, head=head, label=label_name)
        labels_list.append(label_name)
        self.model.is_data_dirty = True
        if self.current_video_path:
            new_event = {"head": head, "label": label_name, "position_ms": current_pos}
            self.model.push_undo(CmdType.LOC_EVENT_ADD, video_path=self.current_video_path, event=new_event)
            if self.current_video_path not in self.model.localization_events: self.model.localization_events[self.current_video_path] = []
            self.model.localization_events[self.current_video_path].append(new_event)
        self._refresh_schema_ui()
        self.right_panel.annot_mgmt.tabs.set_current_head(head)
        if self.current_video_path: 
            self._display_events_for_item(self.current_video_path)
            self.refresh_tree_icons()
        self.main.show_temp_msg("Added", f"{head}: {label_name}")
        self.main.update_save_export_button_state()
        if was_playing: player.play()

    def _on_label_rename_req(self, head, old_label):
        new_label, ok = QInputDialog.getText(self.main, "Rename Label", f"Rename '{old_label}' to:", text=old_label)
        if not ok or not new_label.strip() or new_label == old_label: return
        new_label = new_label.strip()
        labels_list = self.model.label_definitions[head].get('labels', [])
        if any(l.lower() == new_label.lower() for l in labels_list if l != old_label):
             self.main.show_temp_msg("Error", "Label exists!", icon=QMessageBox.Icon.Warning); return
        self.model.push_undo(CmdType.SCHEMA_REN_LBL, head=head, old_lbl=old_label, new_lbl=new_label)
        index = labels_list.index(old_label)
        labels_list[index] = new_label
        for vid_path, events in self.model.localization_events.items():
            for evt in events:
                if evt.get('head') == head and evt.get('label') == old_label: evt['label'] = new_label
        self.model.is_data_dirty = True
        self._refresh_schema_ui()
        self.right_panel.annot_mgmt.tabs.set_current_head(head)
        self._refresh_current_clip_events()
        self.main.update_save_export_button_state() 

    def _on_label_delete_req(self, head, label):
        res = QMessageBox.warning(self.main, "Delete Label", f"Delete '{label}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if res != QMessageBox.StandardButton.Yes: return
        loc_affected = {}
        for vid_path, events in self.model.localization_events.items():
            aff = [copy.deepcopy(e) for e in events if e.get('head') == head and e.get('label') == label]
            if aff: loc_affected[vid_path] = aff
        self.model.push_undo(CmdType.SCHEMA_DEL_LBL, head=head, label=label, loc_affected_events=loc_affected)
        labels_list = self.model.label_definitions[head].get('labels', [])
        if label in labels_list: labels_list.remove(label)
        for vid_path in self.model.localization_events:
            events = self.model.localization_events[vid_path]
            self.model.localization_events[vid_path] = [e for e in events if not (e.get('head') == head and e.get('label') == label)]
        self.model.is_data_dirty = True
        self._refresh_schema_ui()
        self.right_panel.annot_mgmt.tabs.set_current_head(head)
        self._refresh_current_clip_events()
        self.main.update_save_export_button_state() 

    # --- Spotting (Data Creation) ---
    def _on_spotting_triggered(self, head, label):
        if not self.current_video_path: QMessageBox.warning(self.main, "Warning", "No video selected."); return
        pos_ms = self.center_panel.media_preview.player.position()
        new_event = {"head": head, "label": label, "position_ms": pos_ms}
        self.model.push_undo(CmdType.LOC_EVENT_ADD, video_path=self.current_video_path, event=new_event)
        if self.current_video_path not in self.model.localization_events: self.model.localization_events[self.current_video_path] = []
        self.model.localization_events[self.current_video_path].append(new_event)
        self.model.is_data_dirty = True
        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons() 
        self.main.show_temp_msg("Event Created", f"{head}: {label}")
        self.main.update_save_export_button_state() 

        self._reselect_event(new_event)

    # --- Table Modification ---
    def _on_annotation_modified(self, old_event, new_event):
        events = self.model.localization_events.get(self.current_video_path, [])
        try: index = events.index(old_event)
        except ValueError: return 
        self.model.push_undo(CmdType.LOC_EVENT_MOD, video_path=self.current_video_path, old_event=copy.deepcopy(old_event), new_event=new_event)
        new_head = new_event['head']
        new_label = new_event['label']
        schema_changed = False
        if new_head not in self.model.label_definitions:
            self.model.label_definitions[new_head] = {"type": "single_label", "labels": []}
            schema_changed = True
        if new_label and new_label != "???":
            labels_list = self.model.label_definitions[new_head]['labels']
            if not any(l.lower() == new_label.lower() for l in labels_list):
                labels_list.append(new_label)
                schema_changed = True
        events[index] = new_event
        self.model.is_data_dirty = True
        if schema_changed:
            self._refresh_schema_ui()
            self.right_panel.annot_mgmt.tabs.set_current_head(new_head)
        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons()
        self.main.show_temp_msg("Event Updated", "Modified")
        self.main.update_save_export_button_state() 

        self._reselect_event(new_event)

    def _on_delete_single_annotation(self, item_data):
        events = self.model.localization_events.get(self.current_video_path, [])
        if item_data not in events: return
        reply = QMessageBox.question(self.main, "Delete Event", "Delete this event?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return
        self.model.push_undo(CmdType.LOC_EVENT_DEL, video_path=self.current_video_path, event=copy.deepcopy(item_data))
        events.remove(item_data)
        self.model.is_data_dirty = True
        self._display_events_for_item(self.current_video_path)
        self.refresh_tree_icons()
        self.main.update_save_export_button_state() 

    # --- Helper Refresh Methods ---
    def _refresh_schema_ui(self):
        self.right_panel.table.set_schema(self.model.label_definitions)
        self.right_panel.annot_mgmt.update_schema(self.model.label_definitions)

    def _refresh_current_clip_events(self):
        if self.current_video_path: self._display_events_for_item(self.current_video_path)

    # --- Video & Project Logic ---
    def _on_load_clicked(self): self.main.router.import_annotations()
    def _on_save_clicked(self): self.main.router.loc_fm.overwrite_json()
    def _on_export_clicked(self): self.main.router.loc_fm.export_json()

    def _on_clear_all_clicked(self):
        if not self.model.action_item_data: return
        res = QMessageBox.question(self.main, "Clear All", "Are you sure?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res != QMessageBox.StandardButton.Yes: return
        self.model.action_item_data = []
        self.model.action_path_to_name = {}
        self.model.localization_events = {}
        self.model.label_definitions = {} 
        self.model.is_data_dirty = False 
        self.current_video_path = None
        self.current_head = None 
        self.model.undo_stack.clear()
        self.model.redo_stack.clear()
        
        # [CHANGED] Use MediaController stop
        self.media_controller.stop()
        self.center_panel.media_preview.player.setSource(QUrl())
        self.center_panel.media_preview.video_widget.update()
        
        self.center_panel.timeline.set_markers([])
        self.tree_model.clear()
        self._refresh_schema_ui() 
        self.right_panel.table.set_data([]) 
        self.main.show_temp_msg("Cleared", "Workspace reset.")
        self.main.update_save_export_button_state() 

    def _on_tree_context_menu(self, pos):
        index = self.left_panel.tree.indexAt(pos)
        if not index.isValid(): return
        path = index.data(Qt.ItemDataRole.UserRole)
        name = index.data(Qt.ItemDataRole.DisplayRole)
        menu = QMenu(self.left_panel.tree)
        remove_action = menu.addAction(f"Remove '{name}'")
        action = menu.exec(self.left_panel.tree.mapToGlobal(pos))
        if action == remove_action: self._remove_single_video(path, index)

    def _remove_single_video(self, path, index):
        self.model.action_item_data = [d for d in self.model.action_item_data if d['path'] != path]
        if path in self.model.action_path_to_name: del self.model.action_path_to_name[path]
        if path in self.model.localization_events: del self.model.localization_events[path]
        self.model.is_data_dirty = True
        if self.current_video_path == path:
            self.current_video_path = None
            
            # [CHANGED] Use MediaController stop
            self.media_controller.stop()
            self.center_panel.media_preview.player.setSource(QUrl())
            
            self.right_panel.table.set_data([])
            self.center_panel.timeline.set_markers([])
        if index.isValid(): self.tree_model.removeRow(index.row(), index.parent())
        self.main.show_temp_msg("Removed", "Video removed from list.")
        self.main.update_save_export_button_state() 

    def populate_tree(self):
        self.left_panel.tree.blockSignals(True) 
        self.tree_model.clear()
        self.model.action_item_map.clear()
        sorted_list = sorted(self.model.action_item_data, key=lambda d: natural_sort_key(d.get('name', '')))
        first_idx = None
        for i, data in enumerate(sorted_list):
            name = data['name']
            path = data['path']
            item = self.tree_model.add_entry(name, path, data.get('source_files'))
            self.model.action_item_map[path] = item
            events = self.model.localization_events.get(path, [])
            item.setIcon(self.main.done_icon if events else self.main.empty_icon)
            if i == 0: first_idx = item.index()
        self._refresh_schema_ui()
        if self.current_head: self.right_panel.annot_mgmt.tabs.set_current_head(self.current_head)
        self._apply_clip_filter(self.left_panel.filter_combo.currentIndex())
        if first_idx and first_idx.isValid():
            self.left_panel.tree.setCurrentIndex(first_idx)
            self.on_clip_selected(first_idx, None)
        self.left_panel.tree.blockSignals(False)

    def refresh_tree_icons(self):
        for path, item in self.model.action_item_map.items():
            events = self.model.localization_events.get(path, [])
            item.setIcon(self.main.done_icon if events else self.main.empty_icon)

    def _apply_clip_filter(self, combo_index):
        root = self.tree_model.invisibleRootItem()
        for i in range(root.rowCount()):
            item = root.child(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            events = self.model.localization_events.get(path, [])
            has_anno = len(events) > 0
            should_hide = False
            if combo_index == 1 and not has_anno: should_hide = True 
            elif combo_index == 2 and has_anno: should_hide = True   
            self.left_panel.tree.setRowHidden(i, QModelIndex(), should_hide)
    
    def _display_events_for_item(self, path):
        events = self.model.localization_events.get(path, [])
        display_data = []
        clip_name = os.path.basename(path)
        for e in events:
            d = e.copy(); d['clip'] = clip_name; display_data.append(e) 
        display_data.sort(key=lambda x: x.get('position_ms', 0))
        self.right_panel.table.set_data(display_data)
        markers = [{'start_ms': e.get('position_ms', 0), 'color': QColor("#00BFFF")} for e in events]
        self.center_panel.timeline.set_markers(markers)

    def _navigate_clip(self, step):
        tree = self.left_panel.tree
        curr_idx = tree.currentIndex()
        if not curr_idx.isValid(): return
        next_idx = tree.indexBelow(curr_idx) if step > 0 else tree.indexAbove(curr_idx)
        if next_idx.isValid(): tree.setCurrentIndex(next_idx)

    def _navigate_annotation(self, step):
        if not self.current_video_path: return
        events = self.model.localization_events.get(self.current_video_path, [])
        if not events: return
        sorted_events = sorted(events, key=lambda x: x.get('position_ms', 0))
        current_pos = self.center_panel.media_preview.player.position()
        target_time = None
        if step > 0:
            for e in sorted_events:
                if e.get('position_ms', 0) > current_pos + 100: target_time = e.get('position_ms'); break
        else:
            for e in reversed(sorted_events):
                if e.get('position_ms', 0) < current_pos - 100: target_time = e.get('position_ms'); break
        if target_time is not None:
            self.center_panel.media_preview.set_position(target_time)
            self._select_row_by_time(target_time)

    def _select_row_by_time(self, time_ms):
        model = self.right_panel.table.model
        for row in range(model.rowCount()):
            item = model.get_annotation_at(row)
            if item and abs(item.get('position_ms', 0) - time_ms) < 10:
                idx = model.index(row, 0)
                self.right_panel.table.table.selectRow(row)
                self.right_panel.table.table.scrollTo(idx)
                break

    def _reselect_event(self, target_event):
        model = self.right_panel.table.model
        table_view = self.right_panel.table.table
        
        table_view.selectionModel().blockSignals(True)
        
        for row in range(model.rowCount()):
            item = model.get_annotation_at(row)
            if not item: continue
            
            if (item.get('position_ms') == target_event.get('position_ms') and 
                item.get('head') == target_event.get('head') and 
                item.get('label') == target_event.get('label')):
                
                idx = model.index(row, 0)
                
                table_view.selectRow(row)
                table_view.scrollTo(idx)
                
                if hasattr(self.right_panel.table, 'btn_set_time'):
                    self.right_panel.table.btn_set_time.setEnabled(True)
                
                break 
                
        table_view.selectionModel().blockSignals(False)

    def _fmt_ms_full(self, ms):
        s = ms // 1000
        m = s // 60
        h = m // 60
        return f"{h:02}:{m%60:02}:{s%60:02}.{ms%1000:03}"
    

    # ==========================================
    # --- Smart Annotation Control Logic ---
    # ==========================================

    def _on_smart_set_time(self, target: str):
        """
        Triggered when 'Set to Current' is clicked in Smart Spotting UI.
        Gets current player position and updates the smart UI.
        """
        player = self.center_panel.media_preview.player
        current_ms = player.position()
        time_str = self._fmt_ms_full(current_ms)
        
        # Update the UI display and internal state in the Smart Widget
        self.right_panel.smart_widget.update_time_display(target, time_str, current_ms)


    def _run_localization_inference(self, start_ms: int, end_ms: int):
        if not self.current_video_path:
            return
        if start_ms >= end_ms and end_ms != 0:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self.main, "Invalid Range", "End time must be greater than Start time.")
            return
            
        self.main.show_temp_msg("Smart Inference", "Running OpenSportsLib Localization Model...")
        self.right_panel.smart_widget.btn_run_infer.setEnabled(False)
        self.inference_manager.start_inference(self.current_video_path, start_ms, end_ms)


    def _on_inference_success(self, predicted_events: list):
        self.right_panel.smart_widget.btn_run_infer.setEnabled(True)
        if not self.current_video_path:
            return
            
        self.model.smart_localization_events[self.current_video_path] = predicted_events
        self.main.show_temp_msg("Smart Inference", f"Success: Found {len(predicted_events)} events.")
        
        if self.right_panel.tabs.currentIndex() == 1:
            self._display_smart_events(self.current_video_path)

    def _on_inference_error(self, error_msg: str):
        self.right_panel.smart_widget.btn_run_infer.setEnabled(True)
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(self.main, "Inference Error", f"Failed to run model:\n{error_msg}")

    def _confirm_smart_events(self):
        # Merge smart predictions into hand annotations
        if not self.current_video_path:
            return
            
        smart_events = self.model.smart_localization_events.get(self.current_video_path, [])
        if not smart_events:
            return
            
        # Initialize the hand annotations list for the current video (if it doesn't exist)
        if self.current_video_path not in self.model.localization_events:
            self.model.localization_events[self.current_video_path] = []
            
        # Merge events (undo/redo is not handled here currently)
        self.model.localization_events[self.current_video_path].extend(smart_events)
        
        # Sort by time
        self.model.localization_events[self.current_video_path].sort(key=lambda x: x.get('position_ms', 0))
        
        # Clear current Smart Events
        self.model.smart_localization_events[self.current_video_path] = []
        self._display_smart_events(self.current_video_path) # Refresh with an empty table
        
        # Notify user
        self.main.show_temp_msg("Smart Spotting", "Predictions confirmed and merged into Hand Annotations.")
        self.model.is_data_dirty = True
        self.main.update_save_export_button_state()

    def _clear_smart_events(self):
        if not self.current_video_path:
            return
        self.model.smart_localization_events[self.current_video_path] = []
        self._display_smart_events(self.current_video_path)
        self.main.show_temp_msg("Smart Spotting", "Cleared smart predictions.")

    def _display_smart_events(self, video_path: str):
        """Dedicated method to display ONLY smart events in the smart table and timeline."""
        events = self.model.smart_localization_events.get(video_path, [])
        # Update Smart Table
        self.right_panel.smart_widget.smart_table.set_data(events)
        # Update Timeline
        markers = []
        for evt in events:
            # Smart events can also use a different color, like blue, to distinguish them from hand annotations (red)
            from PyQt6.QtGui import QColor
            markers.append({
                'start_ms': evt.get('position_ms', 0),
                'color': QColor('deepskyblue')
            })
        self.center_panel.timeline.set_markers(markers)

    def _on_tab_switched(self, index: int):
        # Isolate visual states when switching tabs
        if not self.current_video_path:
            return
            
        if index == 0:
            # Go back to hand annotations, load original hand events
            self._display_events_for_item(self.current_video_path)
        elif index == 1:
            # Go to smart annotations, load smart events
            self._display_smart_events(self.current_video_path)
