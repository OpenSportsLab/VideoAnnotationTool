import os
import json
import datetime
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from utils import natural_sort_key

class ClassFileManager:
    def __init__(self, main_window):
        self.main = main_window
        self.model = main_window.model

    def load_project(self, data, file_path):
        """
        Load Classification Project.
        Returns:
            bool: True if loaded successfully, False if validation failed or cancelled.
        """
        
        # 1. Strict Validation
        valid, err, warn = self.model.validate_gac_json(data)
        
        if not valid:
             # Truncate extremely long error messages for display
            if len(err) > 1000:
                err = err[:1000] + "\n... (truncated)"

            error_text = (
                "The imported JSON contains critical errors and cannot be loaded.\n\n"
                f"{err}\n\n"
                "--------------------------------------------------\n"
                "💡 Please download the correct Classification JSON format from:\n"
                "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars"
            )
            
            QMessageBox.critical(
                self.main, 
                "Validation Error (Classification)", 
                error_text
            )
            return False # [FIX] Return False to signal failure
            
        if warn:
            if len(warn) > 1000:
                warn = warn[:1000] + "\n... (truncated)"
            
            res = QMessageBox.warning(
                self.main, "Validation Warnings", 
                "The file contains warnings:\n\n" + warn + "\n\nContinue loading?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if res != QMessageBox.StandardButton.Yes:
                return False # [FIX] Return False on user cancel
            
        # 2. Clear Workspace (Only if validation passed)
        self._clear_workspace(full_reset=True)
        
        self.model.current_working_directory = os.path.dirname(file_path)
        
        self.model.current_task_name = data.get('task', "N/A")
        self.model.modalities = data.get('modalities', [])
        
        # Load Labels
        self.model.label_definitions = {}
        if 'labels' in data:
            for k, v in data['labels'].items():
                clean_k = k.strip().replace(' ', '_').lower()
                self.model.label_definitions[clean_k] = {'type': v['type'], 'labels': sorted(list(set(v.get('labels', []))))}
        self.main.setup_dynamic_ui() 

        # Check if it is multi view
        is_multi = False
        for item in data.get('data', []):
            if len(item.get('inputs', [])) > 1:
                is_multi = True
                break
        self.model.is_multi_view = is_multi
        
        # Load Data
        for item in data.get('data', []):
            aid = item.get('id')
            if not aid: continue
            
            src_files = []
            for inp in item.get('inputs', []):
                p = inp.get('path', '')
                
                if os.path.isabs(p):
                    fp = p
                else:
                    fp = os.path.normpath(os.path.join(self.model.current_working_directory, p))
                
                src_files.append(fp)
                self.model.imported_input_metadata[(aid, os.path.basename(fp))] = inp.get('metadata', {})
            
            path_key = src_files[0] if src_files else aid
            
            self.model.action_item_data.append({'name': aid, 'path': path_key, 'source_files': src_files})
            self.model.action_path_to_name[path_key] = aid
            self.model.imported_action_metadata[path_key] = item.get('metadata', {})
            
            # Load Manual Annotations
            lbls = item.get('labels', {})
            manual = {}
            has_l = False
            for h, content in lbls.items():
                ck = h.strip().replace(' ', '_').lower()
                if ck in self.model.label_definitions:
                    defn = self.model.label_definitions[ck]
                    if isinstance(content, dict):
                        if defn['type'] == 'single_label' and content.get('label') in defn['labels']:
                            manual[ck] = content.get('label'); has_l = True
                        elif defn['type'] == 'multi_label':
                            vals = [x for x in content.get('labels', []) if x in defn['labels']]
                            if vals: manual[ck] = vals; has_l = True
            if has_l:
                self.model.manual_annotations[path_key] = manual

            # [NEW] Load Smart Annotations from JSON
            smart_lbls = item.get('smart_labels', {})
            smart = {}
            for h, content in smart_lbls.items():
                ck = h.strip().replace(' ', '_').lower()
                if ck in self.model.label_definitions and isinstance(content, dict):
                    # Reconstruct the prediction and confidence dictionary
                    smart[ck] = {
                        "label": content.get("label"),
                        "conf_dict": content.get("conf_dict", {content.get("label"): content.get("confidence", 1.0)})
                    }
            if smart:
                # [MODIFIED] Mark loaded smart annotations as confirmed so the Filter recognizes them
                smart["_confirmed"] = True 
                self.model.smart_annotations[path_key] = smart

        self.model.current_json_path = file_path
        self.model.json_loaded = True
        
        # [MV Note] populate_action_tree now uses self.main.tree_model internally
        self.main.populate_action_tree()
        self.main.update_save_export_button_state()
        
        self.main.show_temp_msg(
            "Mode Switched", 
            f"Project loaded with {len(self.model.action_item_data)} items.\n\nCurrent Mode: CLASSIFICATION",
            duration=1500,
            icon=QMessageBox.Icon.Information
        )
        
        return True # [FIX] Explicitly return True on success

    def save_json(self):
        if self.model.current_json_path: 
            return self._write_json(self.model.current_json_path)
        else: 
            return self.export_json()

    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(self.main, "Save Classification JSON", "", "JSON (*.json)")
        if path:
            result = self._write_json(path)
            if result:
                self.model.current_json_path = path
                self.main.update_save_export_button_state()
            return result
        return False

    def _write_json(self, save_path):
        out = {
            "version": "2.0",
            "date": datetime.datetime.now().isoformat().split('T')[0],
            "task": self.model.current_task_name,
            "description": self.model.project_description,
            "modalities": self.model.modalities,
            "labels": self.model.label_definitions,
            "data": []
        }
        
        json_dir = os.path.dirname(os.path.abspath(save_path))
        
        sorted_items = sorted(self.model.action_item_data, key=lambda x: natural_sort_key(x.get('name', '')))
        
        for item in sorted_items:
            path_key = item['path'] 
            aid = item['name']
            
            inputs = []
            for src_abs_path in item.get('source_files', []):
                try:
                    fpath = os.path.relpath(src_abs_path, json_dir)
                    fpath = fpath.replace('\\', '/')
                except ValueError:
                    fpath = src_abs_path.replace('\\', '/')
                
                meta = self.model.imported_input_metadata.get((aid, os.path.basename(src_abs_path)), {})
                
                inputs.append({
                    "type": "video", 
                    "path": fpath,
                    "metadata": meta
                })
            
            data_entry = {
                "id": aid,
                "inputs": inputs,
                "metadata": self.model.imported_action_metadata.get(path_key, {})
            }
            
            if path_key in self.model.manual_annotations:
                annots = self.model.manual_annotations[path_key]
                entry_labels = {}
                for head, val in annots.items():
                    defn = self.model.label_definitions.get(head)
                    if not defn: continue
                    
                    if defn['type'] == 'single_label':
                        entry_labels[head] = {"label": val, "confidence": 1.0, "manual": True}
                    elif defn['type'] == 'multi_label':
                        entry_labels[head] = {"labels": val, "confidence": 1.0, "manual": True}
                
                if entry_labels:
                    data_entry["labels"] = entry_labels
            
            # [NEW] Write smart_labels parallel to manual labels
            if path_key in self.model.smart_annotations:
                smart_annots = self.model.smart_annotations[path_key]
                # [MODIFIED] Only export if they were actually confirmed, and skip the internal flag
                if smart_annots.get("_confirmed", False):
                    entry_smart_labels = {}
                    for head, data_dict in smart_annots.items():
                        if head == "_confirmed": 
                            continue # Skip the internal boolean flag to prevent TypeError
                            
                        entry_smart_labels[head] = {
                            "label": data_dict["label"],
                            "confidence": data_dict.get("conf_dict", {}).get(data_dict["label"], 1.0),
                            "conf_dict": data_dict.get("conf_dict", {})
                        }
                    if entry_smart_labels:
                        data_entry["smart_labels"] = entry_smart_labels
            out["data"].append(data_entry)
        
        try:
            with open(save_path, 'w', encoding='utf-8') as f: 
                json.dump(out, f, indent=2, ensure_ascii=False)
            
            self.model.is_data_dirty = False
            self.main.update_save_export_button_state()
            self.main.show_temp_msg("Saved", f"Saved to {os.path.basename(save_path)}")
            return True
        except Exception as e:
            QMessageBox.critical(self.main, "Error", f"Save failed: {e}")
            return False

    def create_new_project(self):
        """
        Creates a blank project immediately, allowing the user to 
        build the schema in the right-hand panel.
        Now asks for SV/MV type before proceeding.
        """
        # Ask Single-View or Multi-View
        from ui.common.dialogs import ClassificationTypeDialog
        dialog = ClassificationTypeDialog(self.main)
        
        if not dialog.exec():
            return 
            
        # 1. Clear existing data (Full Reset)
        self._clear_workspace(full_reset=True)

        # 2. Initialize default "Blank Project" state in the Model
        self.model.current_task_name = "Untitled Task"
        self.model.modalities = ["video"]
        self.model.label_definitions = {} # Empty Category
        self.model.project_description = ""
        
        # 2. Initialize default "Blank Project" state in the Model
        # [MODIFIED] Changed from "Untitled Task" to "action_classification".
        self.model.current_task_name = "action_classification"
        
        # 3. Set flags to allow interaction
        self.model.json_loaded = True 
        self.model.is_data_dirty = True
        
        # No file: None
        self.model.current_json_path = None
        self.model.current_working_directory = None 
        
        # 4. Refresh UI and switch view
        self.main.setup_dynamic_ui()
        self.main.update_save_export_button_state()
        self.main.show_classification_view()
        
        # 5. [IMPORTANT] Explicitly unlock the UI for editing
        self.main.prepare_new_project_ui()

    def _clear_workspace(self, full_reset=False):
        # [MV Fix] Clear the Model, not the View
        self.main.tree_model.clear()
        
        self.model.reset(full_reset)
        self.main.update_save_export_button_state()
        
        # --- UI Resets ---
        self.main.classification_panel.manual_box.setEnabled(False)
        self.main.center_panel.media_preview.load_video(None)
        
        # [NEW] Explicitly reset the Smart Annotation UI (hide donut chart & batch results)
        if hasattr(self.main.classification_panel, 'reset_smart_inference'):
            self.main.classification_panel.reset_smart_inference()
            
        if hasattr(self.main.classification_panel, 'reset_train_ui'):
            self.main.classification_panel.reset_train_ui()
        if full_reset: 
            self.main.setup_dynamic_ui()

        # [NEW] Clear the Smart Annotation dropdowns when workspace is reset
        if hasattr(self.main, 'sync_batch_inference_dropdowns'):
            self.main.sync_batch_inference_dropdowns()