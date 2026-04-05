import os
import sys
import json
import glob
import ssl
import copy
import uuid
import re
import yaml
from models import CmdType
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import QMessageBox
from utils import natural_sort_key

os.environ["WANDB_MODE"] = "disabled"
ssl._create_default_https_context = ssl._create_unverified_context

from opensportslib import model


def _run_opensportslib_inference(base_config_path: str, temp_data: dict, prefix: str):
    """
    [REFACTORED] A shared helper function to handle the repetitive setup, 
    execution, and cleanup of the opensportslib inference process.
    Used by both Single Inference and Batch Inference workers.
    """
    writable_dir = os.path.join(os.path.expanduser("~"), ".soccernet_workspace")
    os.makedirs(writable_dir, exist_ok=True)
    
    writable_dir_fwd = writable_dir.replace('\\', '/')
    logs_dir_fwd = os.path.join(writable_dir, "logs").replace('\\', '/')

    unique_id = uuid.uuid4().hex[:8]
    temp_json_path = os.path.join(writable_dir, f"temp_{prefix}_{unique_id}.json")
    temp_config_path = os.path.join(writable_dir, f"temp_config_{prefix}_{unique_id}.yaml")

    try:
        # 1. Write the temporary JSON data
        with open(temp_json_path, 'w', encoding='utf-8') as f:
            json.dump(temp_data, f, indent=4)

        # 2. Read and modify the YAML config dynamically
        with open(base_config_path, 'r', encoding='utf-8') as f:
            config_text = f.read()
        
        config_text = config_text.replace('./temp_workspace', writable_dir_fwd)
        config_text = config_text.replace('./logs', logs_dir_fwd)

        with open(temp_config_path, 'w', encoding='utf-8') as f:
            f.write(config_text)

        # 3. Initialize model and run inference
        myModel = model.classification(config=temp_config_path)
        metrics = myModel.infer(
            test_set=temp_json_path,
            pretrained="jeetv/snpro-classification-mvit"
        )

        # 4. Search for the generated prediction output
        checkpoint_dir = os.path.join(writable_dir, "checkpoints")
        search_pattern = os.path.join(checkpoint_dir, "**", "predictions_test_epoch_*.json")
        pred_files = glob.glob(search_pattern, recursive=True)

        if not pred_files:
            raise FileNotFoundError("Could not find the generated prediction JSON file.")

        latest_pred_file = max(pred_files, key=os.path.getctime)
        with open(latest_pred_file, 'r', encoding='utf-8') as pf:
            pred_data = json.load(pf)

        return metrics if metrics else {}, pred_data

    finally:
        # 5. Guaranteed cleanup of temporary payload files
        if os.path.exists(temp_json_path):
            try: os.remove(temp_json_path)
            except: pass
        if os.path.exists(temp_config_path):
            try: os.remove(temp_config_path)
            except: pass


class InferenceWorker(QThread):
    finished_signal = pyqtSignal(str, str, dict)
    error_signal = pyqtSignal(str)

    def __init__(self, config_path, base_dir, action_id, json_path, video_path, label_map):
        super().__init__()
        self.config_path = config_path
        self.base_dir = base_dir
        self.action_id = str(action_id)
        self.json_path = json_path
        self.video_path = video_path 
        
        # [DYNAMIC] Assigned from config.yaml, no more hardcoding!
        self.label_map = label_map

    def run(self):
        try:
            video_abs_path = self.video_path
            if not os.path.isabs(video_abs_path):
                if self.json_path and os.path.exists(self.json_path):
                    video_abs_path = os.path.join(os.path.dirname(self.json_path), self.video_path)
                else:
                    video_abs_path = os.path.abspath(self.video_path)
                    
            video_abs_path = os.path.normpath(video_abs_path).replace('\\', '/')
            
            if not os.path.exists(video_abs_path):
                raise FileNotFoundError(f"Cannot find video file at absolute path:\n{video_abs_path}\nPlease ensure the file exists.")

            original_data = {}
            target_item = None

            if self.json_path and os.path.exists(self.json_path):
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    original_data = json.load(f)

                for item in original_data.get("data", []):
                    if str(item.get("id")) == self.action_id:
                        target_item = copy.deepcopy(item)
                        break

            # Dynamic default fallback from the schema instead of hardcoded strings
            default_label = list(self.label_map.values())[0] if self.label_map else "Unknown"

            if not target_item:
                target_item = {
                    "id": self.action_id,
                    "inputs": [{"type": "video", "path": video_abs_path}],
                    "labels": {
                        "action": {"label": default_label, "confidence": 1.0}
                    }
                }
            else:
                for inp in target_item.get("inputs", []):
                    inp["path"] = video_abs_path
                    if "type" not in inp:
                        inp["type"] = "video"
                        
                if "labels" not in target_item:
                    target_item["labels"] = {}
                if "action" not in target_item["labels"]:
                    target_item["labels"]["action"] = {"label": default_label}

            global_labels = original_data.get("labels", {})
            if not isinstance(global_labels, dict):
                global_labels = {}
                
            if "action" not in global_labels:
                global_labels["action"] = {
                    "type": "single_label",
                    "labels": list(self.label_map.values())
                }

            temp_data = {
                "version": original_data.get("version", "2.0"),
                "task": "classification", 
                "labels": global_labels,
                "data": [target_item]
            }
            
            # Use the shared helper function to run inference
            metrics, pred_data = _run_opensportslib_inference(self.config_path, temp_data, "infer")

            predicted_label_idx = None
            confidence = 0.0
            raw_action_data = {} 

            pred_items = pred_data.get("data", [])
            
            if len(pred_items) == 1:
                raw_action_data = pred_items[0].get("labels", {}).get("action", {})
                if "label" in raw_action_data:
                    predicted_label_idx = str(raw_action_data["label"]).strip()
                    confidence = float(raw_action_data.get("confidence", 0.0))
            else:
                clean_action_id = re.sub(r'_view\d+', '', self.action_id)
                for item in pred_items:
                    out_id = str(item.get("id"))
                    if out_id == self.action_id or out_id == clean_action_id:
                        raw_action_data = item.get("labels", {}).get("action", {})
                        if "label" in raw_action_data:
                            predicted_label_idx = str(raw_action_data["label"]).strip()
                            confidence = float(raw_action_data.get("confidence", 0.0))
                        break
            
            if predicted_label_idx is None:
                raise ValueError(f"Dataloader dropped the sample or prediction missing for ID '{self.action_id}'.")

            final_label = "Unknown"
            valid_class_names = list(self.label_map.values())

            if predicted_label_idx in valid_class_names:
                final_label = predicted_label_idx
            elif predicted_label_idx in self.label_map:
                final_label = self.label_map[predicted_label_idx]
            elif predicted_label_idx.endswith(".0"):
                clean_idx = predicted_label_idx.replace(".0", "")
                if clean_idx in self.label_map:
                    final_label = self.label_map[clean_idx]

            conf_dict = {}
            if "confidences" in raw_action_data and isinstance(raw_action_data["confidences"], dict):
                for k, v in raw_action_data["confidences"].items():
                    key_name = self.label_map.get(str(k), str(k))
                    conf_dict[key_name] = float(v)
            else:
                conf_dict[final_label] = confidence
                remaining = max(0.0, 1.0 - confidence)
                if remaining > 0.001:
                    conf_dict["Other Uncertainties"] = remaining

            self.finished_signal.emit("action", final_label, conf_dict)

        except Exception as e:
            self.error_signal.emit(str(e))


class BatchInferenceWorker(QThread):
    finished_signal = pyqtSignal(dict, list) 
    error_signal = pyqtSignal(str)

    def __init__(self, config_path, base_dir, json_path, target_clips, label_map):
        super().__init__()
        self.config_path = config_path
        self.base_dir = base_dir
        self.json_path = json_path
        self.target_clips = target_clips 
        
        # [DYNAMIC] Load map from external source
        self.label_map = label_map

    def _map_label(self, raw_label):
        valid_class_names = list(self.label_map.values())
        if raw_label in valid_class_names: return raw_label
        elif raw_label in self.label_map: return self.label_map[raw_label]
        elif raw_label.endswith(".0"):
            clean_idx = raw_label.replace(".0", "")
            if clean_idx in self.label_map: return self.label_map[clean_idx]
        return "Unknown"

    def run(self):
        try:
            data_items = []
            default_label = list(self.label_map.values())[0] if self.label_map else "Unknown"

            for clip in self.target_clips:
                inputs = []
                for path in clip['paths']:
                    video_abs_path = path
                    if not os.path.isabs(video_abs_path):
                        if self.json_path and os.path.exists(self.json_path):
                            video_abs_path = os.path.join(os.path.dirname(self.json_path), video_abs_path)
                        else:
                            video_abs_path = os.path.abspath(video_abs_path)
                    video_abs_path = os.path.normpath(video_abs_path).replace('\\', '/')
                    inputs.append({"type": "video", "path": video_abs_path})

                # Fallback to default label instead of hardcoded strings
                safe_gt = clip['gt'] if clip['gt'] else default_label
                
                item = {
                    "id": clip['id'],
                    "inputs": inputs,
                    "labels": {"action": {"label": safe_gt, "confidence": 1.0}}
                }
                data_items.append(item)

            global_labels = {
                "action": {
                    "type": "single_label",
                    "labels": list(self.label_map.values())
                }
            }

            temp_data = {
                "version": "2.0",
                "task": "classification",
                "labels": global_labels,
                "data": data_items
            }
            
            # Use the shared helper function to run inference
            metrics, pred_data = _run_opensportslib_inference(self.config_path, temp_data, "batch_infer")

            pred_items = pred_data.get("data", [])
            out_dict = {}
            for item in pred_items:
                out_id = str(item.get("id"))
                raw_action = item.get("labels", {}).get("action", {})
                raw_label = str(raw_action.get("label", "")).strip()
                conf = float(raw_action.get("confidence", 0.0))
                out_dict[out_id] = (self._map_label(raw_label), conf)

            results = []
            for clip in self.target_clips:
                aid = clip['id']
                clean_id = os.path.splitext(aid)[0]
                
                pred_label, conf = out_dict.get(aid, (None, 0.0))
                if pred_label is None:
                    pred_label, conf = out_dict.get(clean_id, ("Unknown", 0.0))

                results.append({
                    'id': aid,
                    'gt': clip['gt'],
                    'pred': pred_label,
                    'conf': conf,
                    'original_items': clip['original_items']
                })

            self.finished_signal.emit(metrics, results)

        except Exception as e:
            self.error_signal.emit(str(e))


class InferenceManager(QObject):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        
        if hasattr(sys, '_MEIPASS'):
            self.base_dir = sys._MEIPASS
        else:
            self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            
        self.config_path = os.path.join(self.base_dir, "config.yaml")
        self.worker = None
        self.batch_worker = None
        
        self.main.classification_panel.batch_run_requested.connect(self.start_batch_inference)
        self.main.classification_panel.batch_confirm_requested.connect(self.confirm_batch_inference)

    def _get_label_map_from_config(self) -> dict:
        """
        [DYNAMIC PARSING] Reads the config.yaml on-the-fly to extract the classes list.
        Prevents hardcoding so the framework scales effortlessly to new sports/models.
        """
        label_map = {}
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
                
            # Extract classes array safely from YAML structure
            if config_data and 'DATA' in config_data and 'classes' in config_data['DATA']:
                classes_list = config_data['DATA']['classes']
                for i, cls_name in enumerate(classes_list):
                    label_map[str(i)] = cls_name
        except Exception as e:
            print(f"Warning: Could not read classes from config.yaml dynamically: {e}")
            
        # Absolute failsafe if the user forgot to write `classes:` in their yaml
        if not label_map:
            label_map = {
                '0': 'Challenge', '1': 'Dive', '2': 'Elbowing', '3': 'High leg', 
                '4': 'Holding', '5': 'Pushing', '6': 'Standing tackling', '7': 'Tackling'
            }
            
        return label_map

    def start_inference(self):
        if not os.path.exists(self.config_path):
            QMessageBox.critical(self.main, "Error", f"config.yaml not found at:\n{self.config_path}")
            return

        current_json_path = self.main.model.current_json_path 
        current_video_path = self.main.get_current_action_path()
        if not current_video_path:
            QMessageBox.warning(self.main, "Warning", "Please select an action/video from the list first.")
            return

        action_id = self.main.model.action_path_to_name.get(current_video_path, os.path.basename(current_video_path))

        self.main.classification_panel.show_inference_loading(True)

        # 1. Dynamically load labels from config
        label_map = self._get_label_map_from_config()

        # 2. Pass labels to worker
        self.worker = InferenceWorker(self.config_path, self.base_dir, action_id, current_json_path, current_video_path, label_map)
        self.worker.finished_signal.connect(self._on_inference_success)
        self.worker.error_signal.connect(self._on_inference_error)
        self.worker.start()

    def _on_inference_success(self, target_head, label, conf_dict):
        # Auto-create the schema (Category) if it's a completely blank/new project
        if target_head not in self.main.model.label_definitions:
            if self.worker:
                # Use dynamically generated labels
                default_labels = list(self.worker.label_map.values())
                self.main.model.label_definitions[target_head] = {
                    "type": "single_label",
                    "labels": sorted(default_labels)
                }
                # Force UI regeneration to display radio buttons
                self.main.setup_dynamic_ui()

        # [NEW] Save raw inference result to smart_annotations memory
        current_video_path = self.main.get_current_action_path()
        # [NEW] Capture old state before overwriting
        old_data = self.main.model.smart_annotations.get(current_video_path, {})
        new_data = {
            target_head: {"label": label, "conf_dict": conf_dict}
        }
        
        # [NEW] Push to Undo History
        import copy
        self.main.model.push_undo(
            CmdType.SMART_ANNOTATION_RUN,
            path=current_video_path,
            old_data=copy.deepcopy(old_data),
            new_data=copy.deepcopy(new_data)
        )

        # Save new data
        if current_video_path not in self.main.model.smart_annotations:
            self.main.model.smart_annotations[current_video_path] = {}
        self.main.model.smart_annotations[current_video_path] = new_data
        
        self.main.model.is_data_dirty = True
        self.main.classification_panel.display_inference_result(target_head, label, conf_dict)
        self.worker = None

    def _on_inference_error(self, error_msg):
        self.main.classification_panel.show_inference_loading(False)
        QMessageBox.critical(self.main, "Inference Error", f"An error occurred during inference:\n\n{error_msg}")
        self.worker = None

    def start_batch_inference(self, start_idx: int, end_idx: int):
        if not os.path.exists(self.config_path):
            QMessageBox.critical(self.main, "Error", f"config.yaml not found at:\n{self.config_path}")
            return

        sorted_items = sorted(self.main.model.action_item_data, key=lambda x: natural_sort_key(x.get('name', '')))
        
        action_groups = {}
        for item in sorted_items:
            base_id = re.sub(r'_view\d+', '', item['name'])
            if base_id not in action_groups:
                action_groups[base_id] = []
            action_groups[base_id].append(item)
            
        sorted_base_ids = list(action_groups.keys())
        max_idx = len(sorted_base_ids) - 1
        
        if start_idx < 0 or end_idx > max_idx or start_idx > end_idx:
            QMessageBox.warning(self.main, "Invalid Range", f"Please enter a valid range between 0 and {max_idx}.")
            return

        target_base_ids = sorted_base_ids[start_idx : end_idx + 1]
        
        target_clips = []
        for base_id in target_base_ids:
            items = action_groups[base_id]
            paths = [it['path'] for it in items]
            
            # Extract current ground truth
            gt_label = ""
            for it in items:
                ann = self.main.model.manual_annotations.get(it['path'], {})
                if 'action' in ann:
                    gt_label = ann['action']
                    break
                    
            target_clips.append({'id': base_id, 'paths': paths, 'gt': gt_label, 'original_items': items})

        self.main.classification_panel.show_inference_loading(True)
        
        # 1. Dynamically load labels from config
        label_map = self._get_label_map_from_config()

        # 2. Pass labels to batch worker
        self.batch_worker = BatchInferenceWorker(self.config_path, self.base_dir, self.main.model.current_json_path, target_clips, label_map)
        self.batch_worker.finished_signal.connect(self._on_batch_inference_success)
        self.batch_worker.error_signal.connect(self._on_batch_inference_error)
        self.batch_worker.start()

    def _on_batch_inference_success(self, metrics: dict, results_list: list):
        # Auto-create the schema (Category) if it's a completely blank/new project
        target_head = "action"
        if target_head not in self.main.model.label_definitions:
            if self.batch_worker:
                default_labels = list(self.batch_worker.label_map.values())
                self.main.model.label_definitions[target_head] = {
                    "type": "single_label",
                    "labels": sorted(default_labels)
                }
                self.main.setup_dynamic_ui()

        # Start building the output text without the accuracy metrics
        text = "BATCH INFERENCE PREDICTIONS:\n\n"
        batch_predictions = {}
        
        old_batch_data = {} 
        new_batch_data = {} 
        import copy
        
        for r in results_list:
            text += f"Video ID: {r['id']}\nPredicted Class: {r['pred']} (Confidence: {r['conf']*100:.1f}%)\n\n"
            
            for item in r['original_items']:
                path = item['path']
                
                # [NEW FIX 2] Store a rich dictionary instead of just a string!
                # This ensures the Confidence is passed to the UI for the Donut Chart.
                conf_dict = {r['pred']: r['conf']}
                if r['conf'] < 1.0: 
                    conf_dict["Other Uncertainties"] = 1.0 - r['conf']
                    
                batch_predictions[path] = {
                    "label": r['pred'],
                    "confidence": r['conf'],
                    "conf_dict": conf_dict
                }
                
                # Record old data for Undo
                if path not in old_batch_data:
                    old_batch_data[path] = self.main.model.smart_annotations.get(path, {})
                
                # Prepare new data for Redo
                new_batch_data[path] = {
                    target_head: {"label": r['pred'], "conf_dict": conf_dict}
                }
                
        # [NEW FIX 1] Push Batch to Undo History using CORRECT keys 'old_data' and 'new_data'
        self.main.model.push_undo(
            CmdType.BATCH_SMART_ANNOTATION_RUN,
            old_data=copy.deepcopy(old_batch_data),
            new_data=copy.deepcopy(new_batch_data)
        )
        
        # Apply new data to model
        for path, data in new_batch_data.items():
            self.main.model.smart_annotations[path] = data
            
        self.main.model.is_data_dirty = True
        self.main.classification_panel.display_batch_inference_result(text, batch_predictions)
        self.batch_worker = None

    def _on_batch_inference_error(self, error_msg):
        self.main.classification_panel.show_inference_loading(False)
        QMessageBox.critical(self.main, "Batch Inference Error", f"An error occurred during batch inference:\n\n{error_msg}")
        self.batch_worker = None

    def confirm_batch_inference(self, results: dict):
        """
        [MODIFIED] Acknowledge batch inference without polluting Hand Annotations.
        """
        applied_count = 0

        # Smart annotations were already pushed to memory and Undo stack 
        # during _on_batch_inference_success. Here we just mark them as confirmed.
        for path, label in results.items():
            if path in self.main.model.smart_annotations:
                # [NEW] Set a confirmed flag directly in smart memory
                self.main.model.smart_annotations[path]["_confirmed"] = True
                self.main.update_action_item_status(path)
                applied_count += 1
        
        # Update UI global states
        if applied_count > 0:
            self.main.model.is_data_dirty = True
            self.main.update_save_export_button_state()
            self.main.show_temp_msg("Batch Annotation", f"Confirmed {applied_count} smart annotations independently.")
        else:
            self.main.show_temp_msg("Batch Annotation", "No smart annotations to confirm.")
