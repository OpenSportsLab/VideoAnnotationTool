import os
import sys
import json
import glob
import ssl
import copy
import uuid
import re
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import QMessageBox
from utils import natural_sort_key

os.environ["WANDB_MODE"] = "disabled"
ssl._create_default_https_context = ssl._create_unverified_context

from soccernetpro import model

class InferenceWorker(QThread):
    finished_signal = pyqtSignal(str, str, dict)
    error_signal = pyqtSignal(str)

    def __init__(self, config_path, base_dir, action_id, json_path, video_path):
        super().__init__()
        self.config_path = config_path
        self.base_dir = base_dir
        self.action_id = str(action_id)
        self.json_path = json_path
        self.video_path = video_path 
        
        self.label_map = {
            '0': 'Challenge', '1': 'Dive', '2': 'Elbowing', '3': 'High leg', 
            '4': 'Holding', '5': 'Pushing', '6': 'Standing tackling', '7': 'Tackling'
        }

    def run(self):
        temp_json_path = ""
        temp_config_path = ""
        try:
            writable_dir = os.path.join(os.path.expanduser("~"), ".soccernet_workspace")
            os.makedirs(writable_dir, exist_ok=True)
            
            writable_dir_fwd = writable_dir.replace('\\', '/')
            logs_dir_fwd = os.path.join(writable_dir, "logs").replace('\\', '/')

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

            if not target_item:
                target_item = {
                    "id": self.action_id,
                    "inputs": [{"type": "video", "path": video_abs_path}],
                    "labels": {
                        "action": {"label": "Tackling", "confidence": 1.0}
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
                    target_item["labels"]["action"] = {"label": "Tackling"}

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
            
            unique_id = uuid.uuid4().hex[:8]
            temp_json_path = os.path.join(writable_dir, f"temp_infer_{unique_id}.json")
            
            with open(temp_json_path, 'w', encoding='utf-8') as f:
                json.dump(temp_data, f, indent=4)

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_text = f.read()
            
            config_text = config_text.replace('./temp_workspace', writable_dir_fwd)
            config_text = config_text.replace('./logs', logs_dir_fwd)

            temp_config_path = os.path.join(writable_dir, f"temp_config_{unique_id}.yaml")
            with open(temp_config_path, 'w', encoding='utf-8') as f:
                f.write(config_text)

            myModel = model.classification(config=temp_config_path)
            metrics = myModel.infer(
                test_set=temp_json_path,
                pretrained="jeetv/snpro-classification-mvit"
            )

            checkpoint_dir = os.path.join(writable_dir, "checkpoints")
            search_pattern = os.path.join(checkpoint_dir, "**", "predictions_test_epoch_*.json")
            pred_files = glob.glob(search_pattern, recursive=True)

            if not pred_files:
                raise FileNotFoundError("Could not find the generated prediction JSON file.")

            latest_pred_file = max(pred_files, key=os.path.getctime)
            with open(latest_pred_file, 'r', encoding='utf-8') as pf:
                pred_data = json.load(pf)

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
            else:
                final_label = "Unknown"

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
        
        finally:
            if os.path.exists(temp_json_path):
                try: os.remove(temp_json_path)
                except: pass
            if os.path.exists(temp_config_path):
                try: os.remove(temp_config_path)
                except: pass


class BatchInferenceWorker(QThread):
    finished_signal = pyqtSignal(dict, list) 
    error_signal = pyqtSignal(str)

    def __init__(self, config_path, base_dir, json_path, target_clips):
        super().__init__()
        self.config_path = config_path
        self.base_dir = base_dir
        self.json_path = json_path
        self.target_clips = target_clips 
        
        self.label_map = {
            '0': 'Challenge', '1': 'Dive', '2': 'Elbowing', '3': 'High leg', 
            '4': 'Holding', '5': 'Pushing', '6': 'Standing tackling', '7': 'Tackling'
        }

    def _map_label(self, raw_label):
        valid_class_names = list(self.label_map.values())
        if raw_label in valid_class_names: return raw_label
        elif raw_label in self.label_map: return self.label_map[raw_label]
        elif raw_label.endswith(".0"):
            clean_idx = raw_label.replace(".0", "")
            if clean_idx in self.label_map: return self.label_map[clean_idx]
        return "Unknown"

    def run(self):
        temp_json_path = ""
        temp_config_path = ""
        try:
            writable_dir = os.path.join(os.path.expanduser("~"), ".soccernet_workspace")
            os.makedirs(writable_dir, exist_ok=True)
            
            writable_dir_fwd = writable_dir.replace('\\', '/')
            logs_dir_fwd = os.path.join(writable_dir, "logs").replace('\\', '/')

            data_items = []
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

                safe_gt = clip['gt'] if clip['gt'] else "Tackling"
                
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
            
            unique_id = uuid.uuid4().hex[:8]
            temp_json_path = os.path.join(writable_dir, f"temp_batch_infer_{unique_id}.json")
            
            with open(temp_json_path, 'w', encoding='utf-8') as f:
                json.dump(temp_data, f, indent=4)

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_text = f.read()
            
            config_text = config_text.replace('./temp_workspace', writable_dir_fwd)
            config_text = config_text.replace('./logs', logs_dir_fwd)

            temp_config_path = os.path.join(writable_dir, f"temp_batch_config_{unique_id}.yaml")
            with open(temp_config_path, 'w', encoding='utf-8') as f:
                f.write(config_text)

            myModel = model.classification(config=temp_config_path)
            metrics = myModel.infer(
                test_set=temp_json_path,
                pretrained="jeetv/snpro-classification-mvit"
            )
            if not metrics: metrics = {}

            checkpoint_dir = os.path.join(writable_dir, "checkpoints")
            search_pattern = os.path.join(checkpoint_dir, "**", "predictions_test_epoch_*.json")
            pred_files = glob.glob(search_pattern, recursive=True)

            if not pred_files:
                raise FileNotFoundError("Could not find the generated prediction JSON file.")

            latest_pred_file = max(pred_files, key=os.path.getctime)
            with open(latest_pred_file, 'r', encoding='utf-8') as pf:
                pred_data = json.load(pf)

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
        
        finally:
            if os.path.exists(temp_json_path):
                try: os.remove(temp_json_path)
                except: pass
            if os.path.exists(temp_config_path):
                try: os.remove(temp_config_path)
                except: pass


class InferenceManager(QObject):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.ui = main_window.ui
        
        if hasattr(sys, '_MEIPASS'):
            self.base_dir = sys._MEIPASS
        else:
            self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            
        self.config_path = os.path.join(self.base_dir, "config.yaml")
        self.worker = None
        self.batch_worker = None
        
        self.ui.classification_ui.right_panel.batch_run_requested.connect(self.start_batch_inference)
        self.ui.classification_ui.right_panel.batch_confirm_requested.connect(self.confirm_batch_inference)

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

        self.ui.classification_ui.right_panel.show_inference_loading(True)

        self.worker = InferenceWorker(self.config_path, self.base_dir, action_id, current_json_path, current_video_path)
        self.worker.finished_signal.connect(self._on_inference_success)
        self.worker.error_signal.connect(self._on_inference_error)
        self.worker.start()

    def _on_inference_success(self, target_head, label, conf_dict):
        self.ui.classification_ui.right_panel.display_inference_result(target_head, label, conf_dict)
        self.worker = None 

    def _on_inference_error(self, error_msg):
        self.ui.classification_ui.right_panel.show_inference_loading(False)
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
            
            # Ground Truth 
            gt_label = ""
            for it in items:
                ann = self.main.model.manual_annotations.get(it['path'], {})
                if 'action' in ann:
                    gt_label = ann['action']
                    break
                    
            target_clips.append({'id': base_id, 'paths': paths, 'gt': gt_label, 'original_items': items})

        self.ui.classification_ui.right_panel.show_inference_loading(True)
        self.batch_worker = BatchInferenceWorker(self.config_path, self.base_dir, self.main.model.current_json_path, target_clips)
        self.batch_worker.finished_signal.connect(self._on_batch_inference_success)
        self.batch_worker.error_signal.connect(self._on_batch_inference_error)
        self.batch_worker.start()

    def _on_batch_inference_success(self, metrics: dict, results_list: list):
        text = "OVERALL ACCURACY METRICS:\n"
        text += f"- Top_2_accuracy: {metrics.get('top_2_accuracy', 0.0):.4f}\n"
        text += f"- Accuracy: {metrics.get('accuracy', 0.0):.4f}\n"
        text += f"- Balanced accuracy: {metrics.get('balanced_accuracy', 0.0):.4f}\n"
        text += f"- F1: {metrics.get('f1', 0.0):.4f}\n"
        text += f"- Precision: {metrics.get('precision', 0.0):.4f}\n"
        text += f"- Recall: {metrics.get('recall', 0.0):.4f}\n\n"

        batch_predictions = {}
        for r in results_list:
            gt_str = r['gt'] if r['gt'] else "None"
            
            if gt_str == "None":
                match_str = "N/A"
            elif gt_str == r['pred']:
                match_str = "Match ✅"
            else:
                match_str = "Mismatch ❌"
                
            text += f"Video ID: {r['id']} - Ground Truth: {gt_str} -- Predicted: {r['pred']} (Confidence: {r['conf']*100:.1f}%) ({match_str})\n\n"
            
            for item in r['original_items']:
                batch_predictions[item['path']] = r['pred']

        self.ui.classification_ui.right_panel.display_batch_inference_result(text, batch_predictions)
        self.batch_worker = None

    def _on_batch_inference_error(self, error_msg):
        self.ui.classification_ui.right_panel.show_inference_loading(False)
        QMessageBox.critical(self.main, "Batch Inference Error", f"An error occurred during batch inference:\n\n{error_msg}")
        self.batch_worker = None

    def confirm_batch_inference(self, results: dict):
        from models import CmdType
        import copy

        batch_changes = {}
        applied_count = 0

        # 1. Collect old and new states for all affected videos into a single dictionary
        for path, label in results.items():
            old_data = copy.deepcopy(self.main.model.manual_annotations.get(path))
            
            new_data = copy.deepcopy(old_data) if old_data else {}
            new_data['action'] = label
            
            # Only record if there is an actual change
            if old_data != new_data:
                batch_changes[path] = {
                    'old_data': old_data,
                    'new_data': new_data
                }

        # If nothing actually changed, just return
        if not batch_changes:
            self.main.show_temp_msg("Batch Annotation", "No new labels to apply.")
            return

        # 2. Push the ENTIRE batch as a SINGLE command to the undo stack
        self.main.model.push_undo(
            CmdType.BATCH_ANNOTATION_CONFIRM, 
            batch_changes=batch_changes
        )

        # 3. Actually apply the changes to the model
        for path, changes in batch_changes.items():
            self.main.model.manual_annotations[path] = changes['new_data']
            self.main.update_action_item_status(path)
            applied_count += 1
        
        # 4. Update UI global states
        if applied_count > 0:
            self.main.model.is_data_dirty = True
            self.main.update_save_export_button_state()
            self.main.show_temp_msg("Batch Annotation", f"Applied labels to {applied_count} items. (1 Undo Step)")
