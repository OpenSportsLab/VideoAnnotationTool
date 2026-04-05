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
            import torch
            if not torch.cuda.is_available():
                torch.cuda.FloatTensor = torch.FloatTensor
                torch.cuda.LongTensor = torch.LongTensor
                torch.cuda.IntTensor = torch.IntTensor
                torch.cuda.DoubleTensor = torch.DoubleTensor
            # ==========================================
            
            # Import library inside thread to avoid blocking main thread at startup
            from opensportslib import model
            import subprocess
            import imageio_ffmpeg 
            
            orig_cwd = os.getcwd()
            
            with tempfile.TemporaryDirectory() as tmp_dir:
                os.chdir(tmp_dir)
                
                try: 
                    # Use FFmpeg to cut clips
                    clip_video_path = os.path.join(tmp_dir, "clipped_segment.mp4")
                    
                    def ms_to_ffmpeg(ms):
                        s = ms // 1000
                        return f"{s // 3600:02}:{(s % 3600) // 60:02}:{s % 60:02}.{ms % 1000:03}"

                    start_time_str = ms_to_ffmpeg(self.start_ms)
                    duration_ms = self.end_ms - self.start_ms if self.end_ms > 0 else 0
                    
                    ffmpeg_exe_path = imageio_ffmpeg.get_ffmpeg_exe() 
                    
                    cmd = [ffmpeg_exe_path, '-y', '-ss', start_time_str, '-i', self.video_path]
                    if duration_ms > 0:
                        cmd += ['-t', ms_to_ffmpeg(duration_ms)]
                    cmd += ['-c', 'copy', clip_video_path]
                    
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

                    tmp_input_json = os.path.join(tmp_dir, "temp_test.json")
                    tmp_config_yaml = os.path.join(tmp_dir, "temp_config.yaml")
                    # --- 1. Load and dynamically patch the YAML config ---
                    with open(self.config_path, 'r', encoding='utf-8') as f:
                        config_dict = yaml.safe_load(f)
                    
                    classes = config_dict.get("DATA", {}).get("classes", [])
                    
                    # 🚀 [MAC CPU ADAPTATION & PATH FIXES] 🚀
                    if "SYSTEM" not in config_dict: config_dict["SYSTEM"] = {}
                    config_dict["SYSTEM"]["work_dir"] = tmp_dir
                    config_dict["SYSTEM"]["device"] = "cpu"
                    config_dict["SYSTEM"]["GPU"] = -1
                    config_dict["SYSTEM"]["gpu_id"] = -1
                    
                    if "MODEL" not in config_dict: config_dict["MODEL"] = {}
                    config_dict["MODEL"]["multi_gpu"] = False

                    if "DATA" in config_dict and "test" in config_dict["DATA"]:
                        config_dict["DATA"]["test"]["video_path"] = tmp_dir 
                        config_dict["DATA"]["test"]["path"] = tmp_input_json
                        config_dict["DATA"]["test"]["results"] = "predictions"
                        
                    if "dataloader" not in config_dict["DATA"]["test"]:
                        config_dict["DATA"]["test"]["dataloader"] = {}
                    config_dict["DATA"]["test"]["dataloader"]["pin_memory"] = False

                    with open(tmp_config_yaml, 'w', encoding='utf-8') as f:
                        yaml.dump(config_dict, f)

                    # --- 2. Create temporary JSON for the clipped video ---
                    test_data = {
                        "version": "2.0",
                        "task": "action_spotting",
                        "labels": {"ball_action": {"type": "single_label", "labels": classes}},
                        "data": [{
                            "id": "inf_vid",
                            "inputs": [{"path": clip_video_path, "type": "video", "fps": 25.0}],
                            "events": [{"head": "ball_action", "label": classes[0] if classes else "Unknown", "position_ms": 0}]
                        }]
                    }
                    with open(tmp_input_json, 'w', encoding='utf-8') as f:
                        json.dump(test_data, f)
                    
                    # --- 3. Execute model inference ---
                    loc_model = model.localization(config=tmp_config_yaml)
                    
                    try:
                        loc_model.infer(
                            test_set=tmp_input_json, 
                            pretrained="jeetv/snpro-snbas-2024"
                        )

                    except Exception as eval_err:
                        print(f"Ignored evaluation error: {eval_err}")
                        pass
                    
                    # --- 4. Parse result JSON and compensate timestamps ---
                    search_pattern = os.path.join(tmp_dir, "**", "*.json")
                    all_jsons = glob.glob(search_pattern, recursive=True)
                    
                    valid_preds = []
                    for f in all_jsons:
                        filename = os.path.basename(f)
                        if "temp_test" not in filename and "temp_config" not in filename:
                            valid_preds.append(f)
                    
                    if valid_preds:
                        actual_output_json = max(valid_preds, key=os.path.getctime)
                    else:
                        raise FileNotFoundError(f"Could not find any generated prediction JSON in {tmp_dir}")

                    predicted_events = []
                    if os.path.exists(actual_output_json):
                        with open(actual_output_json, 'r', encoding='utf-8') as f:
                            output_data = json.load(f)
                        
                        raw_evts = output_data.get("data", [{}])[0].get("events", [])
                        for evt in raw_evts:
                            p_ms_relative = int(evt.get("position_ms", 0))
                            
                            if p_ms_relative == 0 and evt.get("label") == (classes[0] if classes else "Unknown"):
                                continue
                            p_ms_absolute = p_ms_relative + self.start_ms
                                
                            if self.end_ms == 0 or p_ms_absolute <= self.end_ms:
                                # Get confidence 
                                conf = evt.get("confidence", evt.get("score", 0.99))
                                predicted_events.append({
                                    "head": "ball_action",
                                    "label": evt.get("label", "Unknown"),
                                    "position_ms": p_ms_absolute,
                                    "confidence": conf 
                                })
                    
                    self.finished_signal.emit(predicted_events)
                
                finally:
                    os.chdir(orig_cwd)
                
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
        
        import sys
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.abspath(".")
            
        config_path = os.path.join(base_path, "loc_config.yaml")
        
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
