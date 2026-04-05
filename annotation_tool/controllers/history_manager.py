import copy
from models import CmdType
from ui.classification.event_editor import DynamicSingleLabelGroup, DynamicMultiLabelGroup

class HistoryManager:
    """
    General History Manager: Responsible for handling operations on the Undo/Redo stack.
    Supports Classification, Localization, Description, and Dense Description modes.
    """
    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model
        self._is_undoing_redoing = False

    def perform_undo(self):
        if not self.model.undo_stack: return
        self._is_undoing_redoing = True
        
        cmd = self.model.undo_stack.pop()
        self.model.redo_stack.append(cmd)
        
        self._apply_state_change(cmd, is_undo=True)
        
        self.main.update_save_export_button_state()
        self._is_undoing_redoing = False

    def perform_redo(self):
        if not self.model.redo_stack: return
        self._is_undoing_redoing = True
        
        cmd = self.model.redo_stack.pop()
        self.model.undo_stack.append(cmd)
        
        self._apply_state_change(cmd, is_undo=False)
        
        self.main.update_save_export_button_state()
        self._is_undoing_redoing = False

    def _refresh_active_view(self):
        """
        Refreshes the currently active UI tab after a state change.
        Uses the tab index logic to call the appropriate manager's refresh method.
        """
        # Use the right_tabs index to determine the mode
        tab_idx = self.main.right_tabs.currentIndex()
        
        # 0: Classification Mode
        if tab_idx == 0:
            # Rebuild the right-side dynamic control
            self.main.setup_dynamic_ui()
            # Refresh the left and annotation status
            self.main.refresh_ui_after_undo_redo(self.main.get_current_action_path())

        # 1: Localization Mode
        elif tab_idx == 1:
            # Refresh Schema (Tabs)
            self.main.loc_manager._refresh_schema_ui()
            # Refresh Events (Table & Timeline)
            self.main.loc_manager._refresh_current_clip_events()
            # Refresh left side
            self.main.dataset_explorer_controller.populate_tree()

        # 2: Description Mode
        elif tab_idx == 2:
            # Refresh the editor text by re-triggering selection logic
            tree = self.main.dataset_explorer_panel.tree
            current_idx = tree.selectionModel().currentIndex()
            if current_idx.isValid():
                # Force reload of data from model to UI (pass None as previous index)
                self.main.desc_nav_manager.on_item_selected(current_idx, None)
        
        # 3: Dense Description Mode
        elif tab_idx == 3:
            # Refresh the table and timeline markers
            # Using the path stored in dense_manager
            path = self.main.dense_manager.current_video_path
            if path:
                self.main.dense_manager._display_events_for_item(path)

    def _apply_state_change(self, cmd, is_undo):
        ctype = cmd['type']
        
        # 1. Classification Specific
        if ctype == CmdType.ANNOTATION_CONFIRM:
            path = cmd['path']
            data = cmd['old_data'] if is_undo else cmd['new_data']
            if data is None:
                if path in self.model.manual_annotations: del self.model.manual_annotations[path]
            else: self.model.manual_annotations[path] = copy.deepcopy(data)
            self.main.refresh_ui_after_undo_redo(path)

        # [NEW] Handle batch annotation confirm
        elif ctype == CmdType.BATCH_ANNOTATION_CONFIRM:
            batch_changes = cmd['batch_changes'] # Retrieve the packed dictionary
            
            # Loop through every video that was modified in this batch
            for path, changes in batch_changes.items():
                data = changes['old_data'] if is_undo else changes['new_data']
                
                # Apply the data
                if data:
                    self.model.manual_annotations[path] = copy.deepcopy(data)
                else:
                    if path in self.model.manual_annotations:
                        del self.model.manual_annotations[path]
                        
                # Update the checkmark status in the Tree UI for this video
                self.main.update_action_item_status(path)
                
            # Refresh the right panel if the currently selected item was affected
            self._refresh_active_view()
            
        # [NEW] Handle single smart annotation run (Donut Chart)
        elif ctype == CmdType.SMART_ANNOTATION_RUN:
            path = cmd['path']
            data = cmd['old_data'] if is_undo else cmd['new_data']
            
            if data:
                self.model.smart_annotations[path] = copy.deepcopy(data)
            else:
                if path in self.model.smart_annotations:
                    del self.model.smart_annotations[path]
            
            # Refresh the UI to immediately show or hide the Donut Chart
            self._refresh_active_view()

        # [NEW] Handle batch smart annotation run
        elif ctype == CmdType.BATCH_SMART_ANNOTATION_RUN:
            batch_data = cmd['old_data'] if is_undo else cmd['new_data']
            
            for path, data in batch_data.items():
                if data:
                    self.model.smart_annotations[path] = copy.deepcopy(data)
                else:
                    if path in self.model.smart_annotations:
                        del self.model.smart_annotations[path]
                        
            # Refresh the UI to reflect batch smart annotations
            self._refresh_active_view()

            
        elif ctype == CmdType.UI_CHANGE:
            path = cmd['path']
            if self.main.get_current_action_path() == path:
                val = cmd['old_val'] if is_undo else cmd['new_val']
                grp = self.main.classification_panel.label_groups.get(cmd['head'])
                if grp:
                    if isinstance(grp, DynamicSingleLabelGroup): grp.set_checked_label(val)
                    else: grp.set_checked_labels(val)

       

        # =========================================================
        # 2. Localization Specific (Events)
        # =========================================================
        elif ctype == CmdType.LOC_EVENT_ADD:
            # Add: Undo -> Remove; Redo -> Add
            path = cmd['video_path']
            evt = cmd['event']
            events = self.model.localization_events.get(path, [])
            
            if is_undo:
                if evt in events: events.remove(evt)
            else:
                events.append(evt)
            
            self.model.localization_events[path] = events
            self._refresh_active_view()
            
        elif ctype == CmdType.LOC_EVENT_DEL:
            # Del: Undo -> Add back; Redo -> Remove
            path = cmd['video_path']
            evt = cmd['event']
            events = self.model.localization_events.get(path, [])
            
            if is_undo:
                events.append(evt)
                if path not in self.model.localization_events: self.model.localization_events[path] = events
            else:
                if evt in events: events.remove(evt)
            
            self._refresh_active_view()
            
        elif ctype == CmdType.LOC_EVENT_MOD:
            # Mod: Swap old/new
            path = cmd['video_path']
            old_e = cmd['old_event']
            new_e = cmd['new_event']
            events = self.model.localization_events.get(path, [])
            
            target = new_e if is_undo else old_e
            replacement = old_e if is_undo else new_e
            
            try:
                idx = events.index(target)
                events[idx] = replacement
            except ValueError:
                pass # Event not found
            
            self._refresh_active_view()

        # =========================================================
        # 3. Description Specific
        # =========================================================
        elif ctype == CmdType.DESC_EDIT:
            path = cmd['path']
            # Determine whether to apply old or new data
            data_to_apply = cmd['old_data'] if is_undo else cmd['new_data']
            
            # Find the corresponding item in the data model
            target_entry = None
            for item in self.model.action_item_data:
                if item.get("metadata", {}).get("path") == path:
                    target_entry = item
                    break
            
            if target_entry:
                # 1. Restore the 'captions' list
                target_entry["captions"] = copy.deepcopy(data_to_apply)
                
                # 2. Update the tree icon status (Empty vs Done)
                has_text = False
                if data_to_apply and len(data_to_apply) > 0:
                    text_val = data_to_apply[0].get("text", "")
                    if text_val and text_val.strip():
                        has_text = True
                
                tree_item = self.model.action_item_map.get(path)
                if tree_item:
                    tree_item.setIcon(self.main.done_icon if has_text else self.main.empty_icon)

            self._refresh_active_view()

        # =========================================================
        # 4. Dense Description Specific [NEW]
        # =========================================================
        elif ctype == CmdType.DENSE_EVENT_ADD:
            path = cmd['video_path']
            evt = cmd['event']
            events = self.model.dense_description_events.get(path, [])
            
            if is_undo:
                # Undo Add -> Remove
                if evt in events: events.remove(evt)
            else:
                # Redo Add -> Add
                events.append(evt)
            
            self.model.dense_description_events[path] = events
            self._refresh_active_view()

        elif ctype == CmdType.DENSE_EVENT_DEL:
            path = cmd['video_path']
            evt = cmd['event']
            events = self.model.dense_description_events.get(path, [])
            
            if is_undo:
                # Undo Del -> Add back
                events.append(evt)
                if path not in self.model.dense_description_events: 
                    self.model.dense_description_events[path] = events
            else:
                # Redo Del -> Remove
                if evt in events: events.remove(evt)
                
            self._refresh_active_view()

        elif ctype == CmdType.DENSE_EVENT_MOD:
            path = cmd['video_path']
            old_e = cmd['old_event']
            new_e = cmd['new_event']
            events = self.model.dense_description_events.get(path, [])
            
            # Undo -> revert to old; Redo -> set to new
            target = new_e if is_undo else old_e
            replacement = old_e if is_undo else new_e
            
            try:
                # We rely on dictionary equality or object identity if not copied
                idx = events.index(target)
                events[idx] = replacement
            except ValueError:
                # Should not happen if logic is correct
                pass 
                
            self._refresh_active_view()

        # =========================================================
        # 5. Schema Changes (Shared)
        # =========================================================
        elif ctype == CmdType.SCHEMA_ADD_CAT:
            head = cmd['head']
            if is_undo:
                if head in self.model.label_definitions:
                    del self.model.label_definitions[head]
            else:
                self.model.label_definitions[head] = cmd['definition']
            self._refresh_active_view()
            
        elif ctype == CmdType.SCHEMA_DEL_CAT:
            head = cmd['head']
            if is_undo:
                self.model.label_definitions[head] = cmd['definition']
                
                if 'affected_data' in cmd:
                    for k, v in cmd['affected_data'].items():
                        if k not in self.model.manual_annotations: self.model.manual_annotations[k] = {}
                        self.model.manual_annotations[k][head] = v
                
                if 'loc_affected_events' in cmd:
                    for vid, events_list in cmd['loc_affected_events'].items():
                        if vid not in self.model.localization_events: self.model.localization_events[vid] = []
                        self.model.localization_events[vid].extend(events_list)
            else:
                if head in self.model.label_definitions:
                    del self.model.label_definitions[head]
                
                if 'affected_data' in cmd:
                    for k in cmd['affected_data']:
                        if head in self.model.manual_annotations.get(k, {}): 
                            del self.model.manual_annotations[k][head]
                            
                if 'loc_affected_events' in cmd:
                    for vid in self.model.localization_events:
                        self.model.localization_events[vid] = [
                            e for e in self.model.localization_events[vid] 
                            if e.get('head') != head
                        ]

            self._refresh_active_view()

        elif ctype == CmdType.SCHEMA_REN_CAT:
            old_n = cmd['old_name']
            new_n = cmd['new_name']
            
            src = new_n if is_undo else old_n
            dst = old_n if is_undo else new_n
            
            if src in self.model.label_definitions:
                self.model.label_definitions[dst] = self.model.label_definitions.pop(src)
            
            for anno in self.model.manual_annotations.values():
                if src in anno:
                    anno[dst] = anno.pop(src)
            
            for events in self.model.localization_events.values():
                for evt in events:
                    if evt.get('head') == src:
                        evt['head'] = dst
            
            self._refresh_active_view()
            
        elif ctype == CmdType.SCHEMA_ADD_LBL:
            head = cmd['head']; lbl = cmd['label']
            if head in self.model.label_definitions:
                lst = self.model.label_definitions[head]['labels']
                if is_undo:
                    if lbl in lst: lst.remove(lbl)
                else:
                    if lbl not in lst: lst.append(lbl); lst.sort()
            
            self._refresh_active_view()
            
        elif ctype == CmdType.SCHEMA_DEL_LBL:
            head = cmd['head']; lbl = cmd['label']
            if head in self.model.label_definitions:
                lst = self.model.label_definitions[head]['labels']
                
                if is_undo:
                    if lbl not in lst: lst.append(lbl); lst.sort()
                    if 'affected_data' in cmd:
                        for k, v in cmd['affected_data'].items():
                            if k not in self.model.manual_annotations: self.model.manual_annotations[k] = {}
                            if self.model.label_definitions[head]['type'] == 'single_label':
                                self.model.manual_annotations[k][head] = v
                            else:
                                cur = self.model.manual_annotations[k].get(head, [])
                                if lbl not in cur: cur.append(lbl)
                                self.model.manual_annotations[k][head] = cur
                                
                    if 'loc_affected_events' in cmd:
                        for vid, events_list in cmd['loc_affected_events'].items():
                            if vid not in self.model.localization_events: self.model.localization_events[vid] = []
                            self.model.localization_events[vid].extend(events_list)
                            
                else:
                    if lbl in lst: lst.remove(lbl)
                    if 'affected_data' in cmd:
                        for k in cmd['affected_data']:
                            anno = self.model.manual_annotations.get(k, {})
                            if self.model.label_definitions[head]['type'] == 'single_label':
                                if anno.get(head) == lbl: anno[head] = None
                            else:
                                if lbl in anno.get(head, []): anno[head].remove(lbl)
                    
                    if 'loc_affected_events' in cmd:
                        for vid in self.model.localization_events:
                            self.model.localization_events[vid] = [
                                e for e in self.model.localization_events[vid]
                                if not (e.get('head') == head and e.get('label') == lbl)
                            ]

            self._refresh_active_view()
            
        elif ctype == CmdType.SCHEMA_REN_LBL:
            head = cmd['head']
            old_l = cmd['old_lbl']
            new_l = cmd['new_lbl']
            
            src = new_l if is_undo else old_l
            dst = old_l if is_undo else new_l
            
            if head in self.model.label_definitions:
                lst = self.model.label_definitions[head]['labels']
                if src in lst:
                    idx = lst.index(src)
                    lst[idx] = dst
                    
            for anno in self.model.manual_annotations.values():
                val = anno.get(head)
                if isinstance(val, str) and val == src:
                    anno[head] = dst
                elif isinstance(val, list) and src in val:
                    val[val.index(src)] = dst
                    
            for events in self.model.localization_events.values():
                for evt in events:
                    if evt.get('head') == head and evt.get('label') == src:
                        evt['label'] = dst
                        
            self._refresh_active_view()
