import json
import os
import shutil
import subprocess
import sys
import tempfile

import yaml
from PyQt6.QtCore import QObject, QThread, pyqtSignal


def _base_dir() -> str:
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _safe_current_working_directory() -> str:
    try:
        return os.getcwd()
    except FileNotFoundError:
        fallback = _base_dir()
        os.chdir(fallback)
        return fallback


def _restore_current_working_directory(path: str):
    target = path or _base_dir()
    try:
        os.chdir(target)
    except FileNotFoundError:
        os.chdir(_base_dir())


def _resolve_ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            return ffmpeg_path
    raise FileNotFoundError(
        "Could not find an FFmpeg executable. Install imageio-ffmpeg or make ffmpeg available on PATH."
    )


def _ms_to_ffmpeg_time(ms: int) -> str:
    ms = max(0, int(ms or 0))
    seconds = ms // 1000
    return f"{seconds // 3600:02}:{(seconds % 3600) // 60:02}:{seconds % 60:02}.{ms % 1000:03}"


def _build_temp_dataset(video_path: str, input_fps: float, head_name: str, labels: list[str]) -> dict:
    default_label = labels[0] if labels else "Unknown"
    return {
        "version": "2.0",
        "task": "action_spotting",
        "labels": {head_name: {"type": "single_label", "labels": list(labels)}},
        "data": [
            {
                "id": "inf_vid",
                "inputs": [{"path": video_path, "type": "video", "fps": float(input_fps or 25.0)}],
                "events": [{"head": head_name, "label": default_label, "position_ms": 0}],
            }
        ],
    }


def _runtime_confidence(event: dict) -> float:
    for key in ("confidence_score", "confidence", "score"):
        if key not in event:
            continue
        try:
            return max(0.0, min(1.0, float(event.get(key) or 0.0)))
        except Exception:
            return 1.0
    return 1.0

class LocInferenceWorker(QThread):
    """
    Background worker for running OpenSportsLib Localization inference.
    Dynamically patches config for CPU usage (Mac M1/M2 compatibility).
    """
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, video_path, start_ms, end_ms, config_path, model_id, head_name, labels, input_fps):
        super().__init__()
        self.video_path = os.path.abspath(video_path)
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.config_path = config_path
        self.model_id = str(model_id or "jeetv/snpro-snbas-2024")
        self.target_head = str(head_name or "ball_action")
        self.labels = [str(label) for label in list(labels or []) if str(label).strip()]
        self.input_fps = float(input_fps or 25.0)

    def _clip_video_if_needed(self, tmp_dir: str) -> tuple[str, int]:
        if self.start_ms <= 0 and self.end_ms <= 0:
            return self.video_path, 0

        clip_video_path = os.path.join(tmp_dir, "clipped_segment.mp4")
        cmd = [
            _resolve_ffmpeg_executable(),
            "-y",
            "-ss",
            _ms_to_ffmpeg_time(self.start_ms),
            "-i",
            self.video_path,
        ]
        if self.end_ms > 0:
            duration_ms = max(0, self.end_ms - self.start_ms)
            cmd.extend(["-t", _ms_to_ffmpeg_time(duration_ms)])
        cmd.extend(["-c", "copy", clip_video_path])
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return clip_video_path, self.start_ms

    def _build_runtime_config(self, tmp_dir: str, tmp_input_json: str) -> tuple[str, list[str]]:
        with open(self.config_path, "r", encoding="utf-8") as handle:
            config_dict = yaml.safe_load(handle) or {}

        data_cfg = config_dict.setdefault("DATA", {})
        model_labels = [str(label) for label in list(data_cfg.get("classes", [])) if str(label).strip()]
        if not model_labels:
            model_labels = list(self.labels)
            data_cfg["classes"] = list(model_labels)
        data_cfg["input_fps"] = int(round(self.input_fps)) if self.input_fps > 0 else 25

        test_cfg = data_cfg.setdefault("test", {})
        test_cfg["video_path"] = tmp_dir
        test_cfg["path"] = tmp_input_json
        test_cfg["results"] = "predictions"
        dataloader_cfg = test_cfg.setdefault("dataloader", {})
        dataloader_cfg["pin_memory"] = False
        dataloader_cfg["num_workers"] = 0

        model_cfg = config_dict.setdefault("MODEL", {})
        model_cfg["multi_gpu"] = False
        model_cfg["save_dir"] = os.path.join(tmp_dir, "checkpoints")
        model_cfg["work_dir"] = os.path.join(tmp_dir, "checkpoints")

        system_cfg = config_dict.setdefault("SYSTEM", {})
        system_cfg["work_dir"] = tmp_dir
        system_cfg["save_dir"] = os.path.join(tmp_dir, "checkpoints")
        system_cfg["log_dir"] = os.path.join(tmp_dir, "logs")
        system_cfg["device"] = "cpu"
        system_cfg["GPU"] = -1
        system_cfg["gpu_id"] = -1

        temp_config_path = os.path.join(tmp_dir, "temp_config.yaml")
        with open(temp_config_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(config_dict, handle, sort_keys=False)

        return temp_config_path, model_labels

    @staticmethod
    def _normalize_prediction_payload(predictions) -> dict:
        if isinstance(predictions, dict):
            return predictions
        if isinstance(predictions, str):
            with open(predictions, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                return payload
        raise TypeError(
            f"Unsupported localization predictions type: {type(predictions).__name__}. Expected dict."
        )

    @staticmethod
    def _extract_prediction_events(payload: dict) -> list[dict]:
        events = []
        for item in list(payload.get("data", []) or []):
            if not isinstance(item, dict):
                continue
            for event in list(item.get("events", []) or []):
                if isinstance(event, dict):
                    events.append(event)
        if events:
            return events

        for event in list(payload.get("predictions", []) or []):
            if isinstance(event, dict):
                events.append(event)
        return events

    @staticmethod
    def _event_position_ms(event: dict) -> int:
        raw_position = event.get("position_ms")
        if raw_position is None:
            raw_position = event.get("position")
        try:
            return int(float(raw_position or 0))
        except Exception:
            return 0

    def run(self):
        try:
            if not self.labels:
                raise ValueError("Localization inference requires at least one label in the selected head.")

            # Import library inside thread to avoid blocking main thread at startup
            from opensportslib import model

            original_cwd = _safe_current_working_directory()
            with tempfile.TemporaryDirectory() as tmp_dir:
                try:
                    os.chdir(tmp_dir)
                    tmp_input_json = os.path.join(tmp_dir, "temp_test.json")

                    clip_video_path, clip_offset_ms = self._clip_video_if_needed(tmp_dir)
                    tmp_config_yaml, runtime_labels = self._build_runtime_config(tmp_dir, tmp_input_json)

                    test_data = _build_temp_dataset(
                        clip_video_path,
                        self.input_fps,
                        self.target_head,
                        runtime_labels,
                    )
                    with open(tmp_input_json, "w", encoding="utf-8") as handle:
                        json.dump(test_data, handle)

                    loc_model = model.LocalizationModel(config=tmp_config_yaml)
                    output_data = self._normalize_prediction_payload(
                        loc_model.infer(
                            test_set=tmp_input_json,
                            weights=self.model_id,
                            use_wandb=False,
                        )
                    )
                    raw_evts = self._extract_prediction_events(output_data)
                    predicted_events = []
                    default_label = runtime_labels[0] if runtime_labels else "Unknown"
                    for evt in raw_evts:
                        p_ms = self._event_position_ms(evt)
                        if p_ms == 0 and evt.get("label") == default_label:
                            continue
                        absolute_ms = p_ms + clip_offset_ms
                        if self.end_ms > 0 and absolute_ms > self.end_ms:
                            continue

                        predicted_events.append(
                            {
                                "head": self.target_head,
                                "label": evt.get("label", "Unknown"),
                                "position_ms": absolute_ms,
                                "confidence_score": _runtime_confidence(evt),
                            }
                        )

                    self.finished_signal.emit(predicted_events)
                finally:
                    _restore_current_working_directory(original_cwd)
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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.base_dir = _base_dir()
        self.config_path = os.path.join(self.base_dir, "loc_config.yaml")

    def _attach_thread_cleanup(self, worker: QThread):
        worker.finished.connect(lambda worker_ref=worker: self._on_worker_thread_finished(worker_ref))

    def _on_worker_thread_finished(self, worker_ref: QThread):
        if self.worker is worker_ref:
            self.worker = None
        worker_ref.deleteLater()

    def has_running_threads(self) -> bool:
        return bool(self.worker is not None and self.worker.isRunning())

    def shutdown_threads(self, wait_ms: int = 2500) -> bool:
        worker = self.worker
        if worker is None:
            return True
        if worker.isRunning():
            worker.requestInterruption()
            if wait_ms <= 0 or not worker.wait(wait_ms):
                return False
        if self.worker is worker:
            self.worker = None
        worker.deleteLater()
        return True

    def cancel_inference(self, wait_ms: int = 700) -> bool:
        worker = self.worker
        if worker is None or not worker.isRunning():
            return False

        worker.requestInterruption()
        if wait_ms > 0 and worker.wait(wait_ms):
            return True

        # Last-resort stop for backends that do not cooperatively honor interruption.
        worker.terminate()
        worker.wait(2000)
        return True

    def start_inference(
        self,
        video_path: str,
        start_ms: int,
        end_ms: int,
        model_id: str,
        head_name: str,
        labels: list[str],
        input_fps: float,
    ):
        if self.worker and self.worker.isRunning():
            return
        worker = LocInferenceWorker(
            video_path,
            start_ms,
            end_ms,
            self.config_path,
            model_id,
            head_name,
            labels,
            input_fps,
        )
        worker.finished_signal.connect(self._on_finished)
        worker.error_signal.connect(self._on_error)
        self._attach_thread_cleanup(worker)
        self.worker = worker
        worker.start()

    def _on_finished(self, events):
        self.inference_finished.emit(events)

    def _on_error(self, err_msg):
        self.inference_error.emit(err_msg)
