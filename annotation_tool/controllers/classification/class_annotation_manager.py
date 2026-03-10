import copy
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QTimer
from models import CmdType

class AnnotationManager:
    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model
        self.ui = main_window.ui

    def confirm_smart_annotation_as_manual(self):
        """
        [MODIFIED] Mark current smart prediction(s) as confirmed.
        Added Undo/Redo support for Smart Annotations to fix history bugs.
        """
        import copy
        from models.app_state import CmdType # Ensure CmdType is available
        right_panel = self.ui.classification_ui.right_panel
        
        # Check if we are confirming a batch or a single inference
        if right_panel.is_batch_mode_active:
            # --- BATCH CONFIRMATION LOGIC ---
            batch_preds = right_panel.pending_batch_results
            if not batch_preds:
                self.main.show_temp_msg("Notice", "No batch predictions to confirm.")
                return
            
            old_batch_data = {}
            new_batch_data = {}
            confirmed_count = 0
            
            # Loop through all items in the batch
            for path, pred_data in batch_preds.items():
                # Store the old state for Undo
                old_batch_data[path] = copy.deepcopy(self.model.smart_annotations.get(path))
                
                # --- ROBUST DATA FORMATTING ---
                if isinstance(pred_data, str):
                    head = next(iter(self.model.label_definitions.keys()), "action")
                    formatted_data = {head: {"label": pred_data, "conf_dict": {pred_data: 1.0}}}
                elif isinstance(pred_data, dict) and "label" in pred_data:
                    head = next(iter(self.model.label_definitions.keys()), "action")
                    formatted_data = {head: copy.deepcopy(pred_data)}
                else:
                    formatted_data = copy.deepcopy(pred_data)

                # [NEW FIX] Ensure 'conf_dict' exists for the Donut Chart rendering!
                for h, h_data in formatted_data.items():
                    if isinstance(h_data, dict) and "label" in h_data:
                        if "conf_dict" not in h_data:
                            # Safely extract 'confidence', fallback to 1.0 if not found
                            conf = h_data.get("confidence", 1.0)
                            h_data["conf_dict"] = {h_data["label"]: conf}
                            # Also calculate the remaining percentage for the pie chart
                            rem = 1.0 - conf
                            if rem > 0.001:
                                h_data["conf_dict"]["Other Uncertainties"] = rem
                
                # Mark as confirmed safely
                formatted_data["_confirmed"] = True
                
                # Store the new state for Redo
                new_batch_data[path] = copy.deepcopy(formatted_data)
                
                # Save to model memory
                self.model.smart_annotations[path] = formatted_data
                self.main.update_action_item_status(path)
                confirmed_count += 1
            
            # [NEW] Push the batch confirmation to the Undo stack
            self.model.push_undo(CmdType.BATCH_SMART_ANNOTATION_RUN, old_data=old_batch_data, new_data=new_batch_data)
            
            self.model.is_data_dirty = True
            self.main.show_temp_msg("Saved", f"Batch Smart Annotations confirmed for {confirmed_count} items.", 2000)
            
            # Reset the batch UI back to normal after confirmation
            right_panel.reset_smart_inference()
            
        else:
            # --- SINGLE CONFIRMATION LOGIC ---
            path = self.main.get_current_action_path()
            if not path: return
            
            smart_data = self.model.smart_annotations.get(path)
            if not smart_data:
                self.main.show_temp_msg("Notice", "No smart annotation available to confirm.")
                return
                
            # Store the old state for Undo
            old_data = copy.deepcopy(smart_data)
            
            # Flag it as confirmed internally within the smart memory
            self.model.smart_annotations[path]["_confirmed"] = True
            self.model.is_data_dirty = True
            
            # Store the new state for Redo
            new_data = copy.deepcopy(self.model.smart_annotations[path])
            
            # [NEW] Push the single confirmation to the Undo stack
            self.model.push_undo(CmdType.SMART_ANNOTATION_RUN, path=path, old_data=old_data, new_data=new_data)
            
            self.main.update_action_item_status(path)
            self.main.show_temp_msg("Saved", "Smart Annotation confirmed independently.", 1000)

        # --- COMMON UI UPDATES ---
        self.main.update_save_export_button_state()
        
        # Apply filter immediately to reflect the new Smart Labelled status
        self.main.nav_manager.apply_action_filter()
        
        # Auto-advance to the next video clip
        tree = self.ui.classification_ui.left_panel.tree
        curr_idx = tree.currentIndex()
        if curr_idx.isValid():
            nxt_idx = tree.indexBelow(curr_idx)
            if nxt_idx.isValid():
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(500, lambda: [tree.setCurrentIndex(nxt_idx), tree.scrollTo(nxt_idx)])
                
    def save_manual_annotation(self, override_data=None):
        """
        [MODIFIED] Added 'override_data' parameter. 
        If provided (e.g., from Smart Annotation confirm), it uses the provided dict.
        Otherwise, it falls back to reading the Hand Annotation UI state.
        """
        path = self.main.get_current_action_path()
        if not path: return
        
        # Use provided data if available, otherwise read from the UI
        if override_data is not None:
            raw = override_data
        else:
            raw = self.ui.classification_ui.right_panel.get_annotation()
            
        cleaned = {k: v for k, v in raw.items() if v}
        if not cleaned: cleaned = None
        
        old = copy.deepcopy(self.model.manual_annotations.get(path))
        self.model.push_undo(CmdType.ANNOTATION_CONFIRM, path=path, old_data=old, new_data=cleaned)
        
        if cleaned:
            self.model.manual_annotations[path] = cleaned
            self.main.show_temp_msg("Saved", "Annotation saved.", 1000)
        else:
            if path in self.model.manual_annotations: del self.model.manual_annotations[path]
            self.main.show_temp_msg("Cleared", "Annotation cleared.", 1000)
            
        self.main.update_action_item_status(path)
        self.main.update_save_export_button_state()
        self.main.nav_manager.apply_action_filter()
        
        # [MV Fix] Auto-advance using QTreeView API
        tree = self.ui.classification_ui.left_panel.tree
        curr_idx = tree.currentIndex()
        if curr_idx.isValid():
            # Try to get index below
            nxt_idx = tree.indexBelow(curr_idx)
            if nxt_idx.isValid():
                QTimer.singleShot(500, lambda: [tree.setCurrentIndex(nxt_idx), tree.scrollTo(nxt_idx)])

    def clear_current_manual_annotation(self):
        path = self.main.get_current_action_path()
        if not path: return
        
        old = copy.deepcopy(self.model.manual_annotations.get(path))
        if old:
            self.model.push_undo(CmdType.ANNOTATION_CONFIRM, path=path, old_data=old, new_data=None)
            if path in self.model.manual_annotations: del self.model.manual_annotations[path]
            self.main.update_action_item_status(path)
            self.main.update_save_export_button_state()
            self.main.show_temp_msg("Cleared", "Selection cleared.")
        self.ui.classification_ui.right_panel.clear_selection()

    def clear_current_smart_annotation(self):
        """[NEW] Clear the smart annotation for the current video, with Undo support."""
        path = self.main.get_current_action_path()
        if not path: return
        
        old_smart = copy.deepcopy(self.model.smart_annotations.get(path))
        if old_smart:
            # Push the clearing action to the Undo stack using the SMART_ANNOTATION_RUN cmd
            self.model.push_undo(
                CmdType.SMART_ANNOTATION_RUN, 
                path=path, 
                old_data=old_smart, 
                new_data=None
            )
            
            # Remove from model memory
            if path in self.model.smart_annotations: 
                del self.model.smart_annotations[path]
                
            self.model.is_data_dirty = True
            self.main.show_temp_msg("Cleared", "Smart Annotation cleared.", 1000)
            self.main.update_save_export_button_state()
            
        # Visually hide the donut chart and text without affecting the Hand Annotation UI
        self.ui.classification_ui.right_panel.chart_widget.setVisible(False)
        self.ui.classification_ui.right_panel.batch_result_text.setVisible(False)

    def display_manual_annotation(self, path):
        # 1. Restore manual annotation (This will reset the UI and hide the chart by default)
        data = self.model.manual_annotations.get(path, {})
        self.ui.classification_ui.right_panel.set_annotation(data)

        # 2. [NEW] Re-display the Smart Annotation Donut Chart if data exists
        smart_data = self.model.smart_annotations.get(path, {})
        if smart_data:
            # We display the chart for the first available head (typically 'action')
            for head, s_data in smart_data.items():
                self.ui.classification_ui.right_panel.chart_widget.update_chart(
                    s_data["label"], 
                    s_data.get("conf_dict", {})
                )
                self.ui.classification_ui.right_panel.chart_widget.setVisible(True)
                break

    def handle_ui_selection_change(self, head, new_val):
        if self.main.history_manager._is_undoing_redoing: 
            return

        path = self.main.get_current_action_path()
        if not path: return
        
        old_val = self.model.manual_annotations.get(path, {}).get(head)
        for cmd in reversed(self.model.undo_stack):
            if cmd['type'] == CmdType.UI_CHANGE and cmd['path'] == path and cmd['head'] == head:
                old_val = cmd['new_val']; break
                
        self.model.push_undo(CmdType.UI_CHANGE, path=path, head=head, old_val=old_val, new_val=new_val)

    # ... handle_add_label_head, handle_remove_label_head ...
    # These methods below generally don't touch the TreeView, so they are fine as is, 
    # but I'll include them to ensure the file is complete.

    def handle_add_label_head(self, name):
        clean = name.strip().replace(' ', '_').lower()
        if not clean or clean in self.model.label_definitions: return
        
        msg = QMessageBox(self.main); msg.setText(f"Type for '{name}'?")
        b1 = msg.addButton("Single Label", QMessageBox.ButtonRole.ActionRole)
        b2 = msg.addButton("Multi Label", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        
        type_str = "single_label" if msg.clickedButton() == b1 else "multi_label" if msg.clickedButton() == b2 else None
        if not type_str: return
        
        defn = {"type": type_str, "labels": []}
        self.model.push_undo(CmdType.SCHEMA_ADD_CAT, head=clean, definition=defn)
        self.model.label_definitions[clean] = defn
        self.ui.classification_ui.right_panel.new_head_edit.clear()
        self.main.setup_dynamic_ui()

    def handle_remove_label_head(self, head):
        if head not in self.model.label_definitions: return
        if QMessageBox.question(self.main, "Remove", f"Remove '{head}'?") == QMessageBox.StandardButton.No: return
        
        affected = {}
        for k, v in self.model.manual_annotations.items():
            if head in v: affected[k] = copy.deepcopy(v[head])
            
        self.model.push_undo(CmdType.SCHEMA_DEL_CAT, head=head, definition=copy.deepcopy(self.model.label_definitions[head]), affected_data=affected)
        
        del self.model.label_definitions[head]
        for k in affected: 
            del self.model.manual_annotations[k][head]
            if not self.model.manual_annotations[k]: del self.model.manual_annotations[k]
            self.main.update_action_item_status(k)
            
        self.main.setup_dynamic_ui()
        self.display_manual_annotation(self.main.get_current_action_path())

    def add_custom_type(self, head):
        group = self.ui.classification_ui.right_panel.label_groups.get(head)
        txt = group.input_field.text().strip()
        if not txt: return
        
        labels = self.model.label_definitions[head]['labels']
        if any(l.lower() == txt.lower() for l in labels):
            self.main.show_temp_msg("Duplicate", "Label exists.", icon=QMessageBox.Icon.Warning)
            return
            
        self.model.push_undo(CmdType.SCHEMA_ADD_LBL, head=head, label=txt)
        labels.append(txt); labels.sort()
        
        # Update UI directly
        from ui.classification.event_editor import DynamicSingleLabelGroup
        if isinstance(group, DynamicSingleLabelGroup): group.update_radios(labels)
        else: group.update_checkboxes(labels)
        group.input_field.clear()

    def remove_custom_type(self, head, lbl):
        defn = self.model.label_definitions[head]
        if len(defn['labels']) <= 1: return
        
        affected = {}
        for k, v in self.model.manual_annotations.items():
            if defn['type'] == 'single_label' and v.get(head) == lbl: affected[k] = lbl
            elif defn['type'] == 'multi_label' and lbl in v.get(head, []): affected[k] = copy.deepcopy(v[head])
            
        self.model.push_undo(CmdType.SCHEMA_DEL_LBL, head=head, label=lbl, affected_data=affected)
        
        if lbl in defn['labels']: defn['labels'].remove(lbl)
        
        for k, val in self.model.manual_annotations.items():
            if defn['type'] == 'single_label' and val.get(head) == lbl: val[head] = None
            elif defn['type'] == 'multi_label' and lbl in val.get(head, []): val[head].remove(lbl)
            
        from ui.classification.event_editor import DynamicSingleLabelGroup
        group = self.ui.classification_ui.right_panel.label_groups.get(head)
        if isinstance(group, DynamicSingleLabelGroup): group.update_radios(defn['labels'])
        else: group.update_checkboxes(defn['labels'])
        self.display_manual_annotation(self.main.get_current_action_path())
