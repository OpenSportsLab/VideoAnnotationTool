import os
import json
import glob
import ssl
import copy
import uuid
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import QMessageBox

os.environ["WANDB_MODE"] = "disabled"
ssl._create_default_https_context = ssl._create_unverified_context

from soccernetpro import model

class InferenceWorker(QThread):
    finished_signal = pyqtSignal(str, str, dict)
    error_signal = pyqtSignal(str)

    def __init__(self, config_path, base_dir, action_id, json_path):
        super().__init__()
        self.config_path = config_path
        self.base_dir = base_dir
        self.action_id = str(action_id)
        self.json_path = json_path
        
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

            with open(self.json_path, 'r', encoding='utf-8') as f:
                original_data = json.load(f)

            target_item = None
            for item in original_data.get("data", []):
                if str(item.get("id")) == self.action_id:
                    target_item = copy.deepcopy(item)
                    break

            if not target_item:
                raise ValueError(f"Action ID '{self.action_id}' not found in the original JSON file.")

            json_dir = os.path.dirname(os.path.abspath(self.json_path))
            for inp in target_item.get("inputs", []):
                if "path" in inp:
                    video_rel_path = inp["path"]
                    if not os.path.isabs(video_rel_path):
                        abs_path = os.path.normpath(os.path.join(json_dir, video_rel_path))
                        if not os.path.exists(abs_path):
                            raise FileNotFoundError(f"Video missing: {abs_path}\nPlease check if the video exists next to your JSON.")
                        inp["path"] = abs_path

            if "labels" not in target_item:
                target_item["labels"] = {}
            if "action" not in target_item["labels"]:
                target_item["labels"]["action"] = {}
            target_item["labels"]["action"]["label"] = "Tackling"

            temp_data = {
                "version": original_data.get("version", "2.0"),
                "task": original_data.get("task", "classification"),
                "labels": original_data.get("labels", {}),
                "data": [target_item]
            }
            
            unique_id = uuid.uuid4().hex[:8]
            temp_json_path = os.path.join(writable_dir, f"temp_infer_{self.action_id}_{unique_id}.json")
            
            with open(temp_json_path, 'w', encoding='utf-8') as f:
                json.dump(temp_data, f, indent=4)

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_text = f.read()
            
            logs_dir_fwd = os.path.join(writable_dir, "logs").replace('\\', '/')
            
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

            if "data" in pred_data and isinstance(pred_data["data"], list):
                for item in pred_data["data"]:
                    if str(item.get("id")) == self.action_id:
                        try:
                            raw_action_data = item["labels"]["action"]
                            predicted_label_idx = str(raw_action_data["label"]).strip()
                            confidence = float(raw_action_data["confidence"])
                            break
                        except KeyError:
                            pass
            
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


class InferenceManager(QObject):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.ui = main_window.ui
        
        import sys
        if hasattr(sys, '_MEIPASS'):
            self.base_dir = sys._MEIPASS
        else:
            self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            
        self.config_path = os.path.join(self.base_dir, "config.yaml")
        self.worker = None

    def start_inference(self):
        if not os.path.exists(self.config_path):
            QMessageBox.critical(self.main, "Error", f"config.yaml not found at:\n{self.config_path}")
            return

        current_json_path = self.main.model.current_json_path
        if not current_json_path or not os.path.exists(current_json_path):
            QMessageBox.warning(self.main, "Warning", "Please import a valid JSON project first.")
            return

        current_video_path = self.main.get_current_action_path()
        if not current_video_path:
            QMessageBox.warning(self.main, "Warning", "Please select an action from the list first.")
            return

        action_id = self.main.model.action_path_to_name.get(current_video_path, "unknown")

        self.ui.classification_ui.right_panel.show_inference_loading(True)

        self.worker = InferenceWorker(self.config_path, self.base_dir, action_id, current_json_path)
        self.worker.finished_signal.connect(self._on_inference_success)
        self.worker.error_signal.connect(self._on_inference_error)
        self.worker.start()

    def _on_inference_success(self, target_head, label, conf_dict):
        self.ui.classification_ui.right_panel.display_inference_result(target_head, label, conf_dict)
        self.worker = None 

    def _on_inference_error(self, error_msg):
        self.ui.classification_ui.right_panel.show_inference_loading(False)
        QMessageBox.critical(self.main, "Inference Error", f"An error occurred during inference:\n\n{error_msg}")
        print(f"[Smart Annotation Error] {error_msg}")
        self.worker = None
