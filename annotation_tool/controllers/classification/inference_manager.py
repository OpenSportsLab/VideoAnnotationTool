import copy
import json
import os
import re
import ssl
import sys
import uuid

import yaml
from PyQt6.QtCore import QObject, QSettings, QThread, pyqtSignal
from PyQt6.QtWidgets import QInputDialog, QMessageBox

from controllers.command_types import CmdType
from utils import natural_sort_key

os.environ["WANDB_MODE"] = "disabled"
ssl._create_default_https_context = ssl._create_unverified_context

from opensportslib import model


def _run_opensportslib_inference(base_config_path: str, temp_data: dict, prefix: str, pretrained_model: str):
    """
    Shared helper to run OpenSportsLib classification inference against a temporary
    dataset payload.
    """
    writable_dir = os.path.join(os.path.expanduser("~"), ".soccernet_workspace")
    os.makedirs(writable_dir, exist_ok=True)

    writable_dir_fwd = writable_dir.replace("\\", "/")
    logs_dir_fwd = os.path.join(writable_dir, "logs").replace("\\", "/")

    unique_id = uuid.uuid4().hex[:8]
    temp_json_path = os.path.join(writable_dir, f"temp_{prefix}_{unique_id}.json")
    temp_config_path = os.path.join(writable_dir, f"temp_config_{prefix}_{unique_id}.yaml")

    try:
        with open(temp_json_path, "w", encoding="utf-8") as handle:
            json.dump(temp_data, handle, indent=2)

        with open(base_config_path, "r", encoding="utf-8") as handle:
            config_text = handle.read()

        config_text = config_text.replace("./temp_workspace", writable_dir_fwd)
        config_text = config_text.replace("./logs", logs_dir_fwd)

        with open(temp_config_path, "w", encoding="utf-8") as handle:
            handle.write(config_text)

        runner = model.ClassificationModel(config=temp_config_path)
        pred_data = runner.infer(
            test_set=temp_json_path,
            weights=pretrained_model,
            use_wandb=False,
        )
        if isinstance(pred_data, str):
            with open(pred_data, "r", encoding="utf-8") as handle:
                pred_data = json.load(handle)
        if not isinstance(pred_data, dict):
            raise TypeError(
                f"Unsupported classification predictions type: {type(pred_data).__name__}. Expected dict."
            )

        return {}, pred_data
    finally:
        if os.path.exists(temp_json_path):
            try:
                os.remove(temp_json_path)
            except Exception:
                pass
        if os.path.exists(temp_config_path):
            try:
                os.remove(temp_config_path)
            except Exception:
                pass


class InferenceWorker(QThread):
    finished_signal = pyqtSignal(str, str, dict)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        config_path: str,
        base_dir: str,
        action_id: str,
        json_path: str,
        video_path: str,
        label_map: dict,
        target_head: str,
        pretrained_model: str,
    ):
        super().__init__()
        self.config_path = config_path
        self.base_dir = base_dir
        self.action_id = str(action_id)
        self.json_path = json_path
        self.video_path = video_path
        self.label_map = label_map or {}
        self.target_head = str(target_head or "action")
        self.pretrained_model = str(pretrained_model or "jeetv/snpro-classification-mvit")

    def _map_label(self, raw_label: str) -> str:
        raw_label = str(raw_label or "").strip()
        valid_class_names = list(self.label_map.values())
        if raw_label in valid_class_names:
            return raw_label
        if raw_label in self.label_map:
            return self.label_map[raw_label]
        if raw_label.endswith(".0"):
            clean_idx = raw_label.replace(".0", "")
            if clean_idx in self.label_map:
                return self.label_map[clean_idx]
        return raw_label or "Unknown"

    def run(self):
        try:
            video_abs_path = self.video_path
            if not os.path.isabs(video_abs_path):
                if self.json_path and os.path.exists(self.json_path):
                    video_abs_path = os.path.join(os.path.dirname(self.json_path), self.video_path)
                else:
                    video_abs_path = os.path.abspath(self.video_path)
            video_abs_path = os.path.normpath(video_abs_path).replace("\\", "/")

            if not os.path.exists(video_abs_path):
                raise FileNotFoundError(
                    f"Cannot find video file at absolute path:\n{video_abs_path}\nPlease ensure the file exists."
                )

            original_data = {}
            target_item = None

            if self.json_path and os.path.exists(self.json_path):
                with open(self.json_path, "r", encoding="utf-8") as handle:
                    original_data = json.load(handle)

                for item in original_data.get("data", []):
                    if str(item.get("id")) == self.action_id:
                        target_item = copy.deepcopy(item)
                        break

            default_label = list(self.label_map.values())[0] if self.label_map else "Unknown"

            if not target_item:
                target_item = {
                    "id": self.action_id,
                    "inputs": [{"type": "video", "path": video_abs_path}],
                    "labels": {"action": {"label": default_label, "confidence": 1.0}},
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
                    "labels": list(self.label_map.values()),
                }

            temp_data = {
                "version": original_data.get("version", "2.0"),
                "task": "classification",
                "labels": global_labels,
                "data": [target_item],
            }

            _metrics, pred_data = _run_opensportslib_inference(
                self.config_path,
                temp_data,
                "infer",
                self.pretrained_model,
            )

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
                clean_action_id = re.sub(r"_view\d+", "", self.action_id)
                for item in pred_items:
                    out_id = str(item.get("id"))
                    if out_id == self.action_id or out_id == clean_action_id:
                        raw_action_data = item.get("labels", {}).get("action", {})
                        if "label" in raw_action_data:
                            predicted_label_idx = str(raw_action_data["label"]).strip()
                            confidence = float(raw_action_data.get("confidence", 0.0))
                        break

            if predicted_label_idx is None:
                raise ValueError(f"Prediction missing for ID '{self.action_id}'.")

            final_label = self._map_label(predicted_label_idx)

            conf_dict = {}
            if "confidences" in raw_action_data and isinstance(raw_action_data["confidences"], dict):
                for key, value in raw_action_data["confidences"].items():
                    conf_name = self.label_map.get(str(key), str(key))
                    conf_dict[conf_name] = float(value)
            else:
                conf_dict[final_label] = confidence
                remaining = max(0.0, 1.0 - confidence)
                if remaining > 0.001:
                    conf_dict["Other Uncertainties"] = remaining

            self.finished_signal.emit(self.target_head, final_label, conf_dict)
        except Exception as exc:
            self.error_signal.emit(str(exc))


class BatchInferenceWorker(QThread):
    finished_signal = pyqtSignal(dict, list)
    error_signal = pyqtSignal(str)

    def __init__(self, config_path, base_dir, json_path, target_clips, label_map, pretrained_model):
        super().__init__()
        self.config_path = config_path
        self.base_dir = base_dir
        self.json_path = json_path
        self.target_clips = list(target_clips or [])
        self.label_map = dict(label_map or {})
        self.pretrained_model = str(pretrained_model or "jeetv/snpro-classification-mvit")

    def _map_label(self, raw_label):
        raw_label = str(raw_label or "").strip()
        valid_class_names = list(self.label_map.values())
        if raw_label in valid_class_names:
            return raw_label
        if raw_label in self.label_map:
            return self.label_map[raw_label]
        if raw_label.endswith(".0"):
            clean_idx = raw_label.replace(".0", "")
            if clean_idx in self.label_map:
                return self.label_map[clean_idx]
        return raw_label or "Unknown"

    def run(self):
        try:
            data_items = []
            default_label = list(self.label_map.values())[0] if self.label_map else "Unknown"

            for clip in self.target_clips:
                inputs = []
                for path in clip["paths"]:
                    video_abs_path = path
                    if not os.path.isabs(video_abs_path):
                        if self.json_path and os.path.exists(self.json_path):
                            video_abs_path = os.path.join(os.path.dirname(self.json_path), video_abs_path)
                        else:
                            video_abs_path = os.path.abspath(video_abs_path)
                    video_abs_path = os.path.normpath(video_abs_path).replace("\\", "/")
                    inputs.append({"type": "video", "path": video_abs_path})

                safe_gt = clip["gt"] if clip["gt"] else default_label
                data_items.append(
                    {
                        "id": clip["id"],
                        "inputs": inputs,
                        "labels": {"action": {"label": safe_gt, "confidence": 1.0}},
                    }
                )

            global_labels = {
                "action": {
                    "type": "single_label",
                    "labels": list(self.label_map.values()),
                }
            }

            temp_data = {
                "version": "2.0",
                "task": "classification",
                "labels": global_labels,
                "data": data_items,
            }

            metrics, pred_data = _run_opensportslib_inference(
                self.config_path,
                temp_data,
                "batch_infer",
                self.pretrained_model,
            )

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
                aid = clip["id"]
                clean_id = os.path.splitext(aid)[0]
                pred_label, conf = out_dict.get(aid, (None, 0.0))
                if pred_label is None:
                    pred_label, conf = out_dict.get(clean_id, ("Unknown", 0.0))
                results.append(
                    {
                        "id": aid,
                        "gt": clip["gt"],
                        "pred": pred_label,
                        "conf": conf,
                        "original_items": clip["original_items"],
                    }
                )

            self.finished_signal.emit(metrics if metrics else {}, results)
        except Exception as exc:
            self.error_signal.emit(str(exc))


class InferenceManager(QObject):
    SETTINGS_ORG = "OpenSportsLab"
    SETTINGS_APP = "VideoAnnotationTool"
    SETTINGS_MODEL_KEY = "classification/last_inference_model"
    DEFAULT_MODEL = "jeetv/snpro-classification-mvit"

    def __init__(self, classification_controller):
        super().__init__()
        self.controller = classification_controller
        self.model = None
        self.panel = classification_controller.classification_panel

        if hasattr(sys, "_MEIPASS"):
            self.base_dir = sys._MEIPASS
        else:
            self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        self.config_path = os.path.join(self.base_dir, "config.yaml")
        self.worker = None
        self.batch_worker = None
        # Preserve manual baseline so clear-smart can restore it.
        self._pre_smart_label_state = {}
        self.settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

    def _attach_thread_cleanup(self, thread: QThread, attr_name: str):
        thread.finished.connect(
            lambda attr=attr_name, worker_ref=thread: self._on_worker_thread_finished(attr, worker_ref)
        )

    def _on_worker_thread_finished(self, attr_name: str, worker_ref: QThread):
        current = getattr(self, attr_name, None)
        if current is worker_ref:
            setattr(self, attr_name, None)
        worker_ref.deleteLater()

    def _shutdown_thread(self, attr_name: str, wait_ms: int = 0) -> bool:
        worker = getattr(self, attr_name, None)
        if worker is None:
            return True
        if worker.isRunning():
            worker.requestInterruption()
            if wait_ms <= 0 or not worker.wait(wait_ms):
                return False
        if getattr(self, attr_name, None) is worker:
            setattr(self, attr_name, None)
        worker.deleteLater()
        return True

    def has_running_threads(self) -> bool:
        return bool(
            (self.worker is not None and self.worker.isRunning())
            or (self.batch_worker is not None and self.batch_worker.isRunning())
        )

    def shutdown_threads(self, wait_ms: int = 2500) -> bool:
        ok_single = self._shutdown_thread("worker", wait_ms=wait_ms)
        ok_batch = self._shutdown_thread("batch_worker", wait_ms=wait_ms)
        return bool(ok_single and ok_batch)

    def _cancel_thread(self, attr_name: str, wait_ms: int = 700) -> bool:
        worker = getattr(self, attr_name, None)
        if worker is None or not worker.isRunning():
            return False
        worker.requestInterruption()
        if wait_ms > 0 and worker.wait(wait_ms):
            return True

        # Last-resort stop for backend calls that do not check interruptions.
        worker.terminate()
        worker.wait(2000)
        return True

    def cancel_active_inference(self) -> bool:
        cancelled = False
        cancelled = self._cancel_thread("worker") or cancelled
        cancelled = self._cancel_thread("batch_worker") or cancelled
        if cancelled:
            self.panel.show_inference_loading(False)
        return cancelled

    def set_dataset_model(self, model_obj):
        self.model = model_obj

    @staticmethod
    def _normalize_score(value) -> float:
        try:
            score = float(value or 0.0)
        except Exception:
            score = 0.0
        return max(0.0, min(1.0, score))

    def _chart_conf_dict(self, label: str, score: float) -> dict:
        score = self._normalize_score(score)
        out = {str(label): score}
        remaining = max(0.0, 1.0 - score)
        if remaining > 0.001:
            out["Other Uncertainties"] = remaining
        return out

    def _remember_pre_smart_state(self, path: str, head: str, old_payload):
        key = (path, head)
        if key in self._pre_smart_label_state:
            return
        if isinstance(old_payload, dict) and "confidence_score" in old_payload:
            self._pre_smart_label_state[key] = None
            return
        self._pre_smart_label_state[key] = copy.deepcopy(old_payload)

    def _sample_labels(self, sample: dict) -> dict:
        labels = sample.get("labels")
        if not isinstance(labels, dict):
            labels = {}
            sample["labels"] = labels
        return labels

    def _set_sample_head_payload(self, sample: dict, head: str, payload):
        labels = self._sample_labels(sample)
        if payload is None:
            labels.pop(head, None)
        else:
            labels[head] = copy.deepcopy(payload)
        if not labels:
            sample.pop("labels", None)

    @staticmethod
    def _find_smart_heads(sample: dict):
        labels = sample.get("labels")
        if not isinstance(labels, dict):
            return []
        out = []
        for head, payload in labels.items():
            if isinstance(payload, dict) and "confidence_score" in payload:
                out.append(head)
        return out

    def _current_path(self) -> str:
        if self.model is None:
            return ""
        sample_id = self.controller.get_current_sample_id()
        if not sample_id:
            return ""
        return str(self.model.get_path_by_id(sample_id) or "")

    def _current_sample(self):
        path = self._current_path()
        if not path or self.model is None:
            return None, ""
        sample = self.model.get_sample_by_path(path)
        if not isinstance(sample, dict):
            return None, ""
        return sample, path

    def _get_label_map_from_config(self) -> dict:
        label_map = {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as handle:
                config_data = yaml.safe_load(handle)
            classes = (config_data or {}).get("DATA", {}).get("classes", [])
            for idx, class_name in enumerate(classes):
                label_map[str(idx)] = class_name
        except Exception:
            label_map = {}

        if not label_map:
            label_map = {
                "0": "Challenge",
                "1": "Dive",
                "2": "Elbowing",
                "3": "High leg",
                "4": "Holding",
                "5": "Pushing",
                "6": "Standing tackling",
                "7": "Tackling",
            }
        return label_map

    def _prompt_model_id(self):
        current = str(self.settings.value(self.SETTINGS_MODEL_KEY, self.DEFAULT_MODEL) or self.DEFAULT_MODEL)
        model_id, ok = QInputDialog.getText(
            self.panel,
            "Classification Inference Model",
            "Model id:",
            text=current,
        )
        if not ok:
            return None
        clean = str(model_id or "").strip()
        if not clean:
            QMessageBox.warning(self.panel, "Inference", "Model id cannot be empty.")
            return None
        self.settings.setValue(self.SETTINGS_MODEL_KEY, clean)
        self.settings.sync()
        return clean

    def _resolve_unknown_prediction_label(self, head: str, predicted_label: str):
        labels = []
        if self.model is not None:
            definition = self.model.label_definitions.get(head, {})
            labels = list(definition.get("labels", [])) if isinstance(definition, dict) else []

        clean_pred = str(predicted_label or "").strip()
        if not labels or clean_pred in labels:
            return clean_pred

        options = [*labels, "<Skip Prediction>"]
        mapped, ok = QInputDialog.getItem(
            self.panel,
            "Map Predicted Label",
            f"Map '{clean_pred}' to:",
            options,
            0,
            False,
        )
        if not ok or mapped == "<Skip Prediction>":
            return None
        return str(mapped)

    def start_inference(self):
        self.start_head_inference("action")

    def start_head_inference(self, target_head: str):
        if self.model is None:
            return
        if self.worker is not None and self.worker.isRunning():
            self.controller._emit_status("Inference", "Inference already running for this mode.", 1200)
            return
        if not os.path.exists(self.config_path):
            QMessageBox.critical(self.panel, "Error", f"config.yaml not found at:\n{self.config_path}")
            return

        sample, current_video_path = self._current_sample()
        if not isinstance(sample, dict) or not current_video_path:
            QMessageBox.warning(self.panel, "Warning", "Please select a sample first.")
            return

        pretrained_model = self._prompt_model_id()
        if not pretrained_model:
            return

        action_id = self.controller.get_current_sample_id() or os.path.basename(current_video_path)
        current_json_path = self.model.current_json_path
        self.panel.show_inference_loading(True)

        label_map = self._get_label_map_from_config()
        worker = InferenceWorker(
            self.config_path,
            self.base_dir,
            action_id,
            current_json_path,
            current_video_path,
            label_map,
            target_head,
            pretrained_model,
        )
        worker.finished_signal.connect(self._on_inference_success)
        worker.error_signal.connect(self._on_inference_error)
        self._attach_thread_cleanup(worker, "worker")
        self.worker = worker
        worker.start()

    def _on_inference_success(self, target_head, label, conf_dict):
        self.panel.show_inference_loading(False)

        if self.model is None:
            return

        sample, current_video_path = self._current_sample()
        if not isinstance(sample, dict) or not current_video_path:
            return

        mapped_label = self._resolve_unknown_prediction_label(target_head, label)
        if not mapped_label:
            self.controller._emit_status("Inference", "Prediction skipped.", 1200)
            return

        if target_head not in self.model.label_definitions:
            self.model.label_definitions[target_head] = {
                "type": "single_label",
                "labels": [mapped_label],
            }
            self.controller.on_schema_context_changed(copy.deepcopy(self.model.label_definitions))

        score = 1.0
        if isinstance(conf_dict, dict):
            if label in conf_dict:
                score = self._normalize_score(conf_dict.get(label))
            elif mapped_label in conf_dict:
                score = self._normalize_score(conf_dict.get(mapped_label))
            elif conf_dict:
                try:
                    score = max(self._normalize_score(v) for v in conf_dict.values())
                except Exception:
                    score = 1.0

        labels = self._sample_labels(sample)
        old_payload = copy.deepcopy(labels.get(target_head))
        new_payload = {"label": mapped_label, "confidence_score": score}

        if old_payload == new_payload:
            self.panel.display_inference_result(target_head, mapped_label, self._chart_conf_dict(mapped_label, score))
            return

        self._remember_pre_smart_state(current_video_path, target_head, old_payload)
        self.model.push_undo(
            CmdType.SMART_ANNOTATION_RUN,
            path=current_video_path,
            head=target_head,
            old_data=copy.deepcopy(old_payload),
            new_data=copy.deepcopy(new_payload),
        )

        self._set_sample_head_payload(sample, target_head, new_payload)
        self.controller.set_current_smart_annotation_snapshot(current_video_path, {target_head: new_payload})
        self.controller.itemStatusRefreshRequested.emit(current_video_path)
        self.controller.saveStateRefreshRequested.emit()

        self.panel.display_inference_result(target_head, mapped_label, self._chart_conf_dict(mapped_label, score))

    def _on_inference_error(self, error_msg):
        self.panel.show_inference_loading(False)
        QMessageBox.critical(self.panel, "Inference Error", f"An error occurred during inference:\n\n{error_msg}")

    def _confirm_paths_as_manual(self, paths, only_head=None):
        old_batch_data = {}
        new_batch_data = {}
        touched_paths = set()

        for path in list(paths or []):
            sample = self.model.get_sample_by_path(path)
            if not isinstance(sample, dict):
                continue

            for head in self._find_smart_heads(sample):
                if only_head and head != only_head:
                    continue
                labels = self._sample_labels(sample)
                old_payload = copy.deepcopy(labels.get(head))
                new_payload = copy.deepcopy(old_payload) if isinstance(old_payload, dict) else None
                if isinstance(new_payload, dict):
                    new_payload.pop("confidence_score", None)
                    if not new_payload:
                        new_payload = None
                if old_payload == new_payload:
                    continue
                old_batch_data.setdefault(path, {})[head] = copy.deepcopy(old_payload)
                new_batch_data.setdefault(path, {})[head] = copy.deepcopy(new_payload)
                self._set_sample_head_payload(sample, head, new_payload)
                touched_paths.add(path)
                self._pre_smart_label_state.pop((path, head), None)

        return old_batch_data, new_batch_data, touched_paths

    def _restore_paths_from_pre_smart(self, paths, only_head=None):
        old_batch_data = {}
        new_batch_data = {}
        touched_paths = set()

        for path in list(paths or []):
            sample = self.model.get_sample_by_path(path)
            if not isinstance(sample, dict):
                continue

            for head in self._find_smart_heads(sample):
                if only_head and head != only_head:
                    continue
                labels = self._sample_labels(sample)
                old_payload = copy.deepcopy(labels.get(head))
                restored_payload = copy.deepcopy(self._pre_smart_label_state.pop((path, head), None))
                if isinstance(restored_payload, dict) and not restored_payload:
                    restored_payload = None
                if old_payload == restored_payload:
                    continue
                old_batch_data.setdefault(path, {})[head] = copy.deepcopy(old_payload)
                new_batch_data.setdefault(path, {})[head] = copy.deepcopy(restored_payload)
                self._set_sample_head_payload(sample, head, restored_payload)
                touched_paths.add(path)

        return old_batch_data, new_batch_data, touched_paths

    def confirm_smart_annotation_for_head(self, head: str):
        if self.model is None:
            return
        sample, path = self._current_sample()
        if not isinstance(sample, dict) or not path or not head:
            return

        old_batch_data, new_batch_data, _touched_paths = self._confirm_paths_as_manual([path], only_head=head)
        if not old_batch_data:
            self.controller._emit_status("Notice", "No smart annotation available to confirm.")
            return

        path_heads = old_batch_data.get(path, {})
        if len(path_heads) == 1:
            confirmed_head = next(iter(path_heads.keys()))
            self.model.push_undo(
                CmdType.SMART_ANNOTATION_RUN,
                path=path,
                head=confirmed_head,
                old_data=copy.deepcopy(path_heads[confirmed_head]),
                new_data=copy.deepcopy(new_batch_data[path][confirmed_head]),
            )
        else:
            self.model.push_undo(
                CmdType.BATCH_SMART_ANNOTATION_RUN,
                old_data=copy.deepcopy(old_batch_data),
                new_data=copy.deepcopy(new_batch_data),
            )

        self.controller.set_current_smart_annotation_snapshot(path, new_batch_data.get(path, {}))
        self.controller.itemStatusRefreshRequested.emit(path)
        self.controller.saveStateRefreshRequested.emit()
        self.controller.display_manual_annotation()

    def reject_smart_annotation_for_head(self, head: str):
        if self.model is None:
            return
        sample, path = self._current_sample()
        if not isinstance(sample, dict) or not path or not head:
            return

        old_batch_data, new_batch_data, _touched_paths = self._restore_paths_from_pre_smart([path], only_head=head)
        if not old_batch_data:
            self.controller._emit_status("Notice", "No smart annotation available to reject.")
            return

        path_heads = old_batch_data.get(path, {})
        if len(path_heads) == 1:
            rejected_head = next(iter(path_heads.keys()))
            self.model.push_undo(
                CmdType.SMART_ANNOTATION_RUN,
                path=path,
                head=rejected_head,
                old_data=copy.deepcopy(path_heads[rejected_head]),
                new_data=copy.deepcopy(new_batch_data[path][rejected_head]),
            )
        else:
            self.model.push_undo(
                CmdType.BATCH_SMART_ANNOTATION_RUN,
                old_data=copy.deepcopy(old_batch_data),
                new_data=copy.deepcopy(new_batch_data),
            )

        self.controller.set_current_smart_annotation_snapshot(path, new_batch_data.get(path, {}))
        self.controller.itemStatusRefreshRequested.emit(path)
        self.controller.saveStateRefreshRequested.emit()
        self.controller.display_manual_annotation()

    def confirm_smart_annotation_as_manual(self):
        if self.model is None:
            return

        sample, path = self._current_sample()
        if not isinstance(sample, dict) or not path:
            return

        old_batch_data, new_batch_data, _touched_paths = self._confirm_paths_as_manual([path])
        if not old_batch_data:
            self.controller._emit_status("Notice", "No smart annotation available to confirm.")
            return

        path_heads = old_batch_data.get(path, {})
        if len(path_heads) == 1:
            head = next(iter(path_heads.keys()))
            self.model.push_undo(
                CmdType.SMART_ANNOTATION_RUN,
                path=path,
                head=head,
                old_data=copy.deepcopy(path_heads[head]),
                new_data=copy.deepcopy(new_batch_data[path][head]),
            )
        else:
            self.model.push_undo(
                CmdType.BATCH_SMART_ANNOTATION_RUN,
                old_data=copy.deepcopy(old_batch_data),
                new_data=copy.deepcopy(new_batch_data),
            )

        self.controller.set_current_smart_annotation_snapshot(path, new_batch_data.get(path, {}))
        self.controller.itemStatusRefreshRequested.emit(path)
        self.controller.saveStateRefreshRequested.emit()
        self.controller.display_manual_annotation()

    def clear_current_smart_annotation(self):
        if self.model is None:
            return

        sample, path = self._current_sample()
        if not isinstance(sample, dict) or not path:
            return

        smart_heads = self._find_smart_heads(sample)
        if not smart_heads:
            return

        old_batch_data, new_batch_data, _touched_paths = self._restore_paths_from_pre_smart([path])

        if not old_batch_data:
            return

        if len(old_batch_data.get(path, {})) == 1:
            head = next(iter(old_batch_data[path].keys()))
            self.model.push_undo(
                CmdType.SMART_ANNOTATION_RUN,
                path=path,
                head=head,
                old_data=copy.deepcopy(old_batch_data[path][head]),
                new_data=copy.deepcopy(new_batch_data[path][head]),
            )
        else:
            self.model.push_undo(
                CmdType.BATCH_SMART_ANNOTATION_RUN,
                old_data=copy.deepcopy(old_batch_data),
                new_data=copy.deepcopy(new_batch_data),
            )

        self.controller.set_current_smart_annotation_snapshot(path, new_batch_data.get(path, {}))
        self.controller.itemStatusRefreshRequested.emit(path)
        self.controller.saveStateRefreshRequested.emit()
        self.controller.display_manual_annotation()

    def confirm_batch_inference(self, results: dict):
        """
        Hidden compatibility API: confirm smart annotations for arbitrary paths.
        """
        if self.model is None:
            return
        paths = list((results or {}).keys())
        if not paths:
            self.controller._emit_status("Batch Annotation", "No smart annotations to confirm.")
            return

        old_batch_data, new_batch_data, touched_paths = self._confirm_paths_as_manual(paths)
        if not old_batch_data:
            self.controller._emit_status("Batch Annotation", "No smart annotations to confirm.")
            return

        self.model.push_undo(
            CmdType.BATCH_SMART_ANNOTATION_RUN,
            old_data=copy.deepcopy(old_batch_data),
            new_data=copy.deepcopy(new_batch_data),
        )
        for path in touched_paths:
            self.controller.itemStatusRefreshRequested.emit(path)
        self.controller.saveStateRefreshRequested.emit()

    def start_batch_inference(self, start_idx: int, end_idx: int):
        """
        Hidden compatibility API retained for older callers. Not exposed in UI.
        """
        if self.model is None:
            return
        if self.batch_worker is not None and self.batch_worker.isRunning():
            self.controller._emit_status("Batch Annotation", "Batch inference already running.", 1200)
            return
        if not os.path.exists(self.config_path):
            QMessageBox.critical(self.panel, "Error", f"config.yaml not found at:\n{self.config_path}")
            return

        pretrained_model = self._prompt_model_id()
        if not pretrained_model:
            return

        sorted_items = sorted(self.model.action_item_data, key=lambda x: natural_sort_key(x.get("name", "")))
        max_idx = len(sorted_items) - 1
        if start_idx < 0 or end_idx > max_idx or start_idx > end_idx:
            QMessageBox.warning(self.panel, "Invalid Range", f"Please enter a valid range between 0 and {max_idx}.")
            return

        target_clips = []
        for item in sorted_items[start_idx : end_idx + 1]:
            manual_annotation = self.model.manual_annotations.get(item["path"], {})
            target_clips.append(
                {
                    "id": item.get("data_id") or item.get("name"),
                    "paths": item.get("source_files", [item["path"]]),
                    "gt": manual_annotation.get("action", ""),
                    "original_items": [item],
                }
            )

        label_map = self._get_label_map_from_config()
        self.panel.show_inference_loading(True)
        worker = BatchInferenceWorker(
            self.config_path,
            self.base_dir,
            self.model.current_json_path,
            target_clips,
            label_map,
            pretrained_model,
        )
        worker.finished_signal.connect(self._on_batch_inference_success)
        worker.error_signal.connect(self._on_batch_inference_error)
        self._attach_thread_cleanup(worker, "batch_worker")
        self.batch_worker = worker
        worker.start()

    def _on_batch_inference_success(self, _metrics: dict, results_list: list):
        self.panel.show_inference_loading(False)
        if self.model is None:
            return

        old_batch_data = {}
        new_batch_data = {}
        touched_paths = set()

        for result in list(results_list or []):
            predicted_label = str(result.get("pred") or "")
            score = self._normalize_score(result.get("conf"))
            for item in result.get("original_items", []):
                path = str(item.get("path") or "")
                sample = self.model.get_sample_by_path(path)
                if not isinstance(sample, dict):
                    continue

                head = "action"
                mapped_label = self._resolve_unknown_prediction_label(head, predicted_label)
                if not mapped_label:
                    continue

                labels = self._sample_labels(sample)
                old_payload = copy.deepcopy(labels.get(head))
                new_payload = {"label": mapped_label, "confidence_score": score}
                if old_payload == new_payload:
                    continue

                self._remember_pre_smart_state(path, head, old_payload)
                old_batch_data.setdefault(path, {})[head] = copy.deepcopy(old_payload)
                new_batch_data.setdefault(path, {})[head] = copy.deepcopy(new_payload)
                self._set_sample_head_payload(sample, head, new_payload)
                touched_paths.add(path)

        if old_batch_data:
            self.model.push_undo(
                CmdType.BATCH_SMART_ANNOTATION_RUN,
                old_data=copy.deepcopy(old_batch_data),
                new_data=copy.deepcopy(new_batch_data),
            )
            for path in touched_paths:
                self.controller.itemStatusRefreshRequested.emit(path)
            self.controller.saveStateRefreshRequested.emit()

    def _on_batch_inference_error(self, error_msg):
        self.panel.show_inference_loading(False)
        QMessageBox.critical(self.panel, "Batch Inference Error", f"An error occurred during batch inference:\n\n{error_msg}")

    def clear_smart_annotations_for_path(self, path: str):
        if not path or self.model is None:
            return
        sample = self.model.get_sample_by_path(path)
        if not isinstance(sample, dict):
            return
        for head in self._find_smart_heads(sample):
            old_payload = copy.deepcopy(sample.get("labels", {}).get(head))
            restored = copy.deepcopy(self._pre_smart_label_state.pop((path, head), None))
            if old_payload == restored:
                continue
            self.model.push_undo(
                CmdType.SMART_ANNOTATION_RUN,
                path=path,
                head=head,
                old_data=copy.deepcopy(old_payload),
                new_data=copy.deepcopy(restored),
            )
            self._set_sample_head_payload(sample, head, restored)
        self.controller.itemStatusRefreshRequested.emit(path)
        self.controller.saveStateRefreshRequested.emit()
