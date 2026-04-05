import os
import json
import tempfile
import yaml
import glob
from PyQt6.QtCore import QObject, QThread, pyqtSignal

class LocInferenceWorker(QThread):
    """
    Background worker for running OpenSportsLib Localization inference.
    Dynamically patches config for CPU usage (Mac M1/M2 compatibility).
    """
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, video_path, start_ms, end_ms, config_path):
        super().__init__()
        self.video_path = os.path.abspath(video_path)
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.config_path = config_path

    def run(self):
        try:
            # Import library inside thread to avoid blocking main thread at startup
            from opensportslib import model
            
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_input_json = os.path.join(tmp_dir, "temp_test.json")
                tmp_config_yaml = os.path.join(tmp_dir, "temp_config.yaml")
                tmp_output_json = os.path.join(tmp_dir, "predictions.json")
                
                # --- 1. Load and dynamically patch the YAML config ---
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config_dict = yaml.safe_load(f)
                
                classes = config_dict.get("DATA", {}).get("classes", [])
                
                # 🚀 [MAC CPU ADAPTATION & PATH FIXES] 🚀
                # Force CPU mode and disable Multi-GPU dynamically
                if "SYSTEM" not in config_dict: config_dict["SYSTEM"] = {}
                config_dict["SYSTEM"]["work_dir"] = tmp_dir
                config_dict["SYSTEM"]["device"] = "cpu"
                config_dict["SYSTEM"]["GPU"] = 0
                config_dict["SYSTEM"]["gpu_id"] = 0
                config_dict["SYSTEM"]["save_dir"] = os.path.join(tmp_dir, "checkpoints")
                
                if "MODEL" not in config_dict: config_dict["MODEL"] = {}
                config_dict["MODEL"]["multi_gpu"] = False
                
                # Override dataloader paths for test
                if "DATA" in config_dict and "test" in config_dict["DATA"]:
                    config_dict["DATA"]["test"]["video_path"] = os.path.dirname(self.video_path)
                    config_dict["DATA"]["test"]["path"] = tmp_input_json
                    config_dict["DATA"]["test"]["results"] = "predictions"
                
                with open(tmp_config_yaml, 'w', encoding='utf-8') as f:
                    yaml.dump(config_dict, f)

                # --- 2. Create temporary JSON for the single video ---
                test_data = {
                    "version": "2.0",
                    "task": "action_spotting",
                    "labels": {"ball_action": {"type": "single_label", "labels": classes}},
                    "data": [{
                        "id": "inf_vid",
                        "inputs": [{"path": self.video_path, "type": "video", "fps": 25.0}],
                        # Must include a dummy event to bypass the DataLoader
                        "events": [{"head": "ball_action", "label": classes[0] if classes else "Unknown", "position_ms": 0}]
                    }]
                }
                with open(tmp_input_json, 'w', encoding='utf-8') as f:
                    json.dump(test_data, f)
                
                # --- 3. Execute model inference ---
                loc_model = model.localization(config=tmp_config_yaml)
                
                try:
                    # Run inference. This will definitely throw a FileNotFoundError because the underlying evaluator cannot find the file
                    loc_model.infer(
                        test_set=tmp_input_json, 
                        pretrained="jeetv/snpro-snbas-2024"
                    )
                except FileNotFoundError:
                    # [Critical Fix 4]: Bossy ignore!
                    # Since the error occurs during the evaluation phase after inference is completed, we just catch the error directly,
                    # pretend nothing happened, and proceed to the next step to extract the generated JSON from the nested folder.
                    pass
                
                # --- 4. Parse result JSON ---
                # Recursively search for all .json files in the temp folder (perfectly pierces through nested checkpoints/xxx folders)
                search_pattern = os.path.join(tmp_dir, "**", "*.json")
                all_jsons = glob.glob(search_pattern, recursive=True)
                
                valid_preds = []
                for f in all_jsons:
                    filename = os.path.basename(f)
                    # Exclude the input data and config files we generated ourselves
                    if "temp_test" not in filename and "temp_config" not in filename:
                        valid_preds.append(f)
                
                if valid_preds:
                    # Find the most recently generated one (to prevent interference from multiple old files)
                    actual_output_json = max(valid_preds, key=os.path.getctime)
                else:
                    raise FileNotFoundError(f"Could not find any generated prediction JSON in {tmp_dir}/checkpoints/")

                predicted_events = []
                if os.path.exists(actual_output_json):
                    with open(actual_output_json, 'r', encoding='utf-8') as f:
                        output_data = json.load(f)
                    
                    raw_evts = output_data.get("data", [{}])[0].get("events", [])
                    for evt in raw_evts:
                        p_ms = int(evt.get("position_ms", 0))
                        
                        if p_ms == 0 and evt.get("label") == (classes[0] if classes else "Unknown"):
                            continue
                            
                        if p_ms >= self.start_ms and (self.end_ms == 0 or p_ms <= self.end_ms):
                            predicted_events.append({
                                "head": evt.get("head", "ball_action"),
                                "label": evt.get("label", "Unknown"),
                                "position_ms": p_ms
                            })
                
                self.finished_signal.emit(predicted_events)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error_signal.emit(str(e))


class LocalizationInferenceManager(QObject):
    """
    High-level controller that manages the inference thread lifecycle.
    """
    inference_finished = pyqtSignal(list)
    inference_error = pyqtSignal(str)
    
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self.worker = None

    def start_inference(self, video_path: str, start_ms: int, end_ms: int):
        if self.worker and self.worker.isRunning(): return
        config_path = os.path.join(os.getcwd(), "loc_config.yaml")
        self.worker = LocInferenceWorker(video_path, start_ms, end_ms, config_path)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.error_signal.connect(self._on_error)
        self.worker.start()

    def _on_finished(self, events):
        self.inference_finished.emit(events)
        self.worker = None

    def _on_error(self, err_msg):
        self.inference_error.emit(err_msg)
        self.worker = None