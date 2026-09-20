"""Local OpenSportsLib and remote HTTP inference providers."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx
import yaml

from controllers.inference_runtime import configure_compute_device
from inference_settings import load_local_models, normalize_server_url, save_local_models
from inference_types import (
    InferenceError,
    InferenceRequest,
    ModelDescriptor,
    validate_result_payload,
)


ProgressCallback = Callable[[str, int, int], None]


class InferenceProvider(Protocol):
    """Common runtime contract implemented by Local and remote adapters."""

    def discover_capabilities(self) -> dict[str, Any]: ...
    def list_models(self, task: str) -> list[ModelDescriptor]: ...
    def model_operation(self, action: str, payload: dict, *, admin_token: str = ""): ...
    def run(self, request: InferenceRequest, progress: ProgressCallback, cancel_event): ...
    def close(self) -> None: ...


def _cancelled(cancel_event) -> bool:
    return bool(cancel_event is not None and cancel_event.is_set())


def _check_cancelled(cancel_event):
    if _cancelled(cancel_event):
        raise InferenceError("Inference cancelled.", code="cancelled")


def _effective_weights(descriptor) -> str | None:
    """Weights to hand OpenSportsLib: None for checkpoint-free (rule-based) models.

    Rule-based models build straight from their config and have no checkpoint
    to load, so falling back to ``descriptor.id`` here would make OpenSportsLib
    try (and fail) to download a checkpoint from that Hugging Face repo.
    """
    if descriptor.checkpoint_free:
        return None
    return descriptor.weights or descriptor.id


def _project_localization_events(events, timeline_offset_ms: int) -> None:
    """Move input-relative predictions onto the whole-sample timeline."""
    offset = max(0, int(timeline_offset_ms or 0))
    if not offset:
        return
    for event in list(events or []):
        if isinstance(event, dict) and "position_ms" in event:
            event["position_ms"] = int(event.get("position_ms", 0) or 0) + offset


def _find_h5_tracking_inputs(inputs) -> list[dict[str, Any]]:
    """Collect every ticked player-tracking H5 input (with its paired ball H5).

    Rule-based models like OpenSportsLab/skeleton-header-max-recall run
    directly on joint/ball tracking H5 files rather than a video clip, and
    their spotters already iterate every matching-type manifest input (e.g.
    to combine several tracking sources for one sample) -- so every ticked
    H5 input must reach the manifest, not just the first one found. Each is
    copied verbatim (type, resolved path, and every other field it carries,
    ball_path included) rather than hand-picked, so nothing the dataset
    loader expects is silently dropped.
    """
    tracking_inputs = []
    for source in inputs:
        if _is_h5_tracking_input(source):
            tracking_inputs.append(
                {"type": source.type, "path": source.path, **copy.deepcopy(source.metadata)}
            )
    return tracking_inputs


def _is_h5_tracking_input(source) -> bool:
    return (
        source.type in {"player_joints_h5", "player_centroids_h5"}
        and bool(str(source.metadata.get("ball_path") or "").strip())
    )


def _effective_localization_timeline_offset(item, uses_tracking_inputs: bool) -> int:
    offsets = tuple(item.input_timeline_offsets_ms or ())
    if len(offsets) != len(item.inputs):
        return max(0, int(item.timeline_offset_ms or 0))
    if uses_tracking_inputs:
        effective_offsets = [
            offset
            for source, offset in zip(item.inputs, offsets)
            if _is_h5_tracking_input(source)
        ]
    else:
        effective_offsets = list(offsets[:1])
    if not effective_offsets:
        return max(0, int(item.timeline_offset_ms or 0))
    return max(0, min(int(offset or 0) for offset in effective_offsets))


class LocalInferenceProvider:
    """Task adapters around the public OpenSportsLib model API."""

    def __init__(self, settings=None, base_dir: str = "", *, local_models=None):
        self.settings = settings
        self.base_dir = base_dir or os.path.dirname(__file__)
        self.local_models = copy.deepcopy(local_models) if local_models is not None else None

    def close(self):
        pass

    def discover_capabilities(self) -> dict[str, Any]:
        import opensportslib
        return {
            "status": "ok", "provider": "local",
            "version": str(getattr(opensportslib, "__version__", "installed")),
        }

    def model_operation(self, action: str, payload: dict, *, admin_token: str = ""):
        models = copy.deepcopy(
            self.local_models if self.local_models is not None
            else load_local_models(self.settings)
        )
        task = str(payload.get("task") or "")
        model_id = str(payload.get("model_id") or "")
        if action == "add":
            model = dict(payload.get("model") or {})
            key = (model.get("task"), model.get("id"))
            models = [item for item in models if (item.get("task"), item.get("id")) != key]
            models.append(model)
        elif action == "remove":
            models = [item for item in models if (item.get("task"), item.get("id")) != (task, model_id)]
        else:
            raise ValueError(f"Unknown Local model operation: {action}")
        save_local_models(self.settings, models)
        self.local_models = models
        return {"model_id": model_id or str((payload.get("model") or {}).get("id") or "")}

    @staticmethod
    def validate_model(model_definition: dict) -> dict:
        """Construct a manually configured model and return its registry state."""
        model_definition = copy.deepcopy(model_definition or {})
        task = str(model_definition.get("task") or "")
        config_path = os.path.abspath(
            os.path.expanduser(str(model_definition.get("config_path") or ""))
        )
        weights = str(model_definition.get("weights") or "").strip()
        if weights:
            weights = os.path.abspath(os.path.expanduser(weights))
        model_definition.update(
            config_path=config_path,
            weights=weights,
            checkpoint_free=not bool(weights),
            trusted_legacy=False,
        )
        try:
            if task not in {
                "classification", "localization", "description",
                "dense_description", "question_answer",
            }:
                raise ValueError(f"Unsupported inference task: {task!r}")
            if not os.path.isfile(config_path):
                raise ValueError(f"Config file does not exist: {config_path}")
            if weights and not os.path.isfile(weights):
                raise ValueError(f"Weights file does not exist: {weights}")
            from opensportslib import model

            class_name = {
                "classification": "ClassificationModel",
                "localization": "LocalizationModel",
                "description": "DescriptionModel",
                "dense_description": "DenseDescriptionModel",
                "question_answer": "VQAModel",
            }[task]
            model_class = getattr(model, class_name, None)
            if model_class is None:
                raise ValueError(
                    f"Installed OpenSportsLib has no {class_name} API."
                )
            runner = model_class(config=config_path)
            configured_task = str(
                getattr(getattr(runner, "config", None), "TASK", "") or ""
            ).strip().lower()
            if configured_task == "vqa":
                configured_task = "question_answer"
            if configured_task and configured_task != task:
                raise ValueError(
                    f"The config declares task {configured_task!r}, not {task!r}."
                )
        except Exception as exc:
            model_definition.update(
                available=False,
                status="failed",
                unavailable_reason=str(exc),
            )
        else:
            model_definition.update(
                available=True,
                status="ready",
                unavailable_reason="",
            )
        return model_definition

    def list_models(self, task: str) -> list[ModelDescriptor]:
        from opensportslib import model

        defaults = {
            "description": ModelDescriptor(
                id="opensportslib-description",
                display_name="OpenSportsLib Description",
                task="description",
                available=False,
                unavailable_reason=(
                    "Add a Description local-model entry with a config YAML."
                    if hasattr(model, "DescriptionModel")
                    else "Installed OpenSportsLib has no DescriptionModel API."
                ),
                accepted_input_types=("video",),
            ),
            "dense_description": ModelDescriptor(
                id="opensportslib-dense-description",
                display_name="OpenSportsLib Dense Description",
                task="dense_description",
                available=False,
                unavailable_reason=(
                    "Add a Dense Description local-model entry with a config YAML."
                    if hasattr(model, "DenseDescriptionModel")
                    else "Installed OpenSportsLib has no DenseDescriptionModel API."
                ),
                accepted_input_types=("video",),
                supports_time_range=True,
            ),
        }
        descriptors_by_id = {}
        if task in defaults:
            descriptor = defaults[task]
            descriptors_by_id[descriptor.id] = descriptor
        configured_models = self.local_models if self.local_models is not None else load_local_models(self.settings)
        for raw in configured_models:
            if raw.get("task") != task:
                continue
            try:
                descriptor = ModelDescriptor.from_dict(raw)
            except (TypeError, ValueError):
                continue
            class_name = {
                "classification": "ClassificationModel",
                "localization": "LocalizationModel",
                "description": "DescriptionModel",
                "dense_description": "DenseDescriptionModel",
                "question_answer": "VQAModel",
            }[task]
            if not hasattr(model, class_name):
                data = descriptor.to_dict()
                data.update(available=False, unavailable_reason=f"Installed OpenSportsLib has no {class_name} API.")
                descriptor = ModelDescriptor.from_dict(data)
            descriptors_by_id[descriptor.id] = descriptor
        return list(descriptors_by_id.values())

    def run(self, request: InferenceRequest, progress: ProgressCallback, cancel_event=None):
        descriptors = {model.id: model for model in self.list_models(request.task)}
        descriptor = descriptors.get(request.model_id)
        if descriptor is None:
            raise InferenceError(f"Unknown local model: {request.model_id}", code="model_not_found")
        if not descriptor.available:
            raise InferenceError(descriptor.unavailable_reason or "Local model is unavailable.", code="model_unavailable")
        _check_cancelled(cancel_event)
        progress("Running local inference", 0, len(request.items))

        if request.task == "localization":
            payload = self._run_localization(request, descriptor, progress, cancel_event)
        elif request.task == "question_answer":
            payload = self._run_vqa(request, descriptor, progress, cancel_event)
        else:
            payload = self._run_dataset_model(request, descriptor, progress, cancel_event)
        return validate_result_payload(request, payload)

    def _run_dataset_model(self, request, descriptor, progress, cancel_event):
        from opensportslib import model

        class_name = {
            "classification": "ClassificationModel",
            "description": "DescriptionModel",
            "dense_description": "DenseDescriptionModel",
        }[request.task]
        model_class = getattr(model, class_name)
        if not descriptor.config_path:
            raise InferenceError("Local model requires a config path.", code="invalid_model_config")

        data_items = []
        for item in request.items:
            sample = copy.deepcopy(item.sample)
            sample["id"] = item.sample_id
            sample["inputs"] = [source.to_wire() for source in item.inputs]
            data_items.append(sample)
        dataset = {
            "version": "2.0",
            "task": request.task,
            "labels": copy.deepcopy(request.schema),
            "data": data_items,
        }
        with tempfile.TemporaryDirectory(prefix="vat_inference_") as tmp_dir:
            dataset_path = os.path.join(tmp_dir, "input.json")
            with open(dataset_path, "w", encoding="utf-8") as handle:
                json.dump(dataset, handle)
            if request.task == "classification":
                from controllers.classification.inference_manager import _run_opensportslib_inference

                _metrics, output = _run_opensportslib_inference(
                    descriptor.config_path,
                    dataset,
                    "shared_infer",
                    _effective_weights(descriptor),
                )
            else:
                runner = model_class(config=descriptor.config_path)
                output = runner.infer(test_set=dataset_path, weights=_effective_weights(descriptor), use_wandb=False)
            if isinstance(output, str):
                with open(output, "r", encoding="utf-8") as handle:
                    output = json.load(handle)
        _check_cancelled(cancel_event)
        raw_items = list((output or {}).get("data") or [])
        if request.task == "classification":
            target_head = str(request.parameters.get("head") or "action")
            for raw in raw_items:
                labels = raw.get("labels") if isinstance(raw.get("labels"), dict) else {}
                if target_head not in labels and "action" in labels:
                    labels[target_head] = labels.pop("action")
                raw["labels"] = labels
        progress("Local inference complete", len(request.items), len(request.items))
        return {"items": raw_items}

    def _run_localization(self, request, descriptor, progress, cancel_event):
        from controllers.localization.loc_inference import LocInferenceWorker

        results = []
        for index, item in enumerate(request.items):
            _check_cancelled(cancel_event)
            if not item.inputs:
                raise InferenceError("Localization input is missing.", code="invalid_request")
            tracking_inputs = _find_h5_tracking_inputs(item.inputs)
            primary_input = item.inputs[0]
            print(
                f"[LocalInferenceProvider] sample={item.sample_id!r} "
                f"inputs={[(src.type, src.path, dict(src.metadata)) for src in item.inputs]} "
                f"tracking_inputs_found={tracking_inputs!r}",
                flush=True,
            )
            captured, errors = [], []
            worker = LocInferenceWorker(
                primary_input.path,
                int(request.parameters.get("start_ms", 0) or 0),
                int(request.parameters.get("end_ms", 0) or 0),
                descriptor.config_path,
                _effective_weights(descriptor),
                str(request.parameters.get("head") or "ball_action"),
                list(request.parameters.get("labels") or []),
                float(primary_input.metadata.get("fps", 25.0) or 25.0),
                trusted_legacy=descriptor.trusted_legacy,
                checkpoint_free=descriptor.checkpoint_free,
                tracking_inputs=tracking_inputs,
                dataset_root=request.dataset_root,
            )
            worker.finished_signal.connect(captured.append)
            worker.error_signal.connect(errors.append)
            worker.run()
            if errors:
                raise InferenceError(errors[-1], code="local_inference_failed")
            events = copy.deepcopy(captured[-1] if captured else [])
            effective_offset_ms = _effective_localization_timeline_offset(
                item,
                uses_tracking_inputs=bool(tracking_inputs),
            )
            _project_localization_events(events, effective_offset_ms)
            results.append({"sample_id": item.sample_id, "events": events})
            progress("Running local inference", index + 1, len(request.items))
        return {"items": results}

    def _run_vqa(self, request, descriptor, progress, cancel_event):
        from opensportslib import model

        if not descriptor.config_path:
            raise InferenceError("Local VQA model requires a config path.", code="invalid_model_config")
        question = str(request.parameters.get("question") or "").strip()
        if not question:
            raise InferenceError("Q/A inference requires a question.", code="invalid_request")
        results = []
        with tempfile.TemporaryDirectory(prefix="vat_vqa_") as tmp_dir:
            runtime_config = self._build_vqa_runtime_config(
                descriptor.config_path, tmp_dir
            )
            runner = model.VQAModel(config=runtime_config)
            for index, item in enumerate(request.items):
                _check_cancelled(cancel_event)
                if not item.inputs:
                    raise InferenceError("Q/A input is missing.", code="invalid_request")
                output = runner.infer(
                    video_path=item.inputs[0].path,
                    question=question,
                    weights=descriptor.weights or None,
                    use_wandb=False,
                )
                answer = self._normalize_vqa_answer(output)
                if not answer:
                    raise InferenceError(
                        "OpenSportsLib returned no VQA answer text.",
                        code="invalid_result",
                    )
                results.append({"sample_id": item.sample_id, "answer": answer})
                progress("Running local inference", index + 1, len(request.items))
        return {"items": results}

    @staticmethod
    def _normalize_vqa_answer(output) -> str:
        if not isinstance(output, dict):
            return str(output or "").strip()
        for key in ("answer", "answer_text", "text"):
            value = output.get(key)
            if value is not None:
                return str(value).strip()
        rows = output.get("data")
        if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict):
            for key in ("answer", "answer_text", "text"):
                value = rows[0].get(key)
                if value is not None:
                    return str(value).strip()
        return ""

    @staticmethod
    def _build_vqa_runtime_config(config_path: str, tmp_dir: str) -> str:
        with open(config_path, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
        if not isinstance(config, dict):
            raise InferenceError(
                "Local VQA model config must contain a YAML object.",
                code="invalid_model_config",
            )

        use_cuda = configure_compute_device(config)
        system = config.setdefault("SYSTEM", {})
        paths = system.setdefault("paths", {})
        paths["save_dir"] = os.path.join(tmp_dir, "checkpoints")
        paths["work_dir"] = os.path.join(tmp_dir, "checkpoints")
        paths["log_dir"] = os.path.join(tmp_dir, "logs")
        # Also cover legacy OpenSportsLib system paths.
        system["save_dir"] = paths["save_dir"]
        system["work_dir"] = paths["work_dir"]
        system["log_dir"] = paths["log_dir"]

        model_cfg = config.setdefault("MODEL", {})
        runtime = model_cfg.setdefault("runtime", {})
        runtime["device"] = system["device"]
        if not use_cuda:
            runtime["dtype"] = "float32"
        execution = config.setdefault("TRAIN", {}).setdefault("execution", {})
        hf_cfg = execution.setdefault("hf", {})
        hf_cfg["prefer_cuda"] = use_cuda
        offload_folder = hf_cfg.get("offload_folder")
        if offload_folder:
            hf_cfg["offload_folder"] = os.path.join(tmp_dir, "hf_offload")

        LocalInferenceProvider._resolve_vqa_local_dependencies(
            config, os.path.dirname(os.path.abspath(config_path))
        )
        runtime_path = os.path.join(tmp_dir, "runtime_config.yaml")
        with open(runtime_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(config, handle, sort_keys=False)
        return runtime_path

    @staticmethod
    def _resolve_vqa_local_dependencies(config: dict, config_dir: str) -> None:
        """Resolve adjacent X-VARS artifacts or report stale absolute paths."""
        components = config.get("MODEL", {}).get("components", {})
        execution = config.get("TRAIN", {}).get("execution", {})
        candidates = []

        for component in components.values() if isinstance(components, dict) else ():
            if not isinstance(component, dict):
                continue
            kind = str(component.get("kind") or "").lower()
            if kind == "encoder":
                load_cfg = component.get("load")
                if isinstance(load_cfg, dict) and load_cfg.get("weights_path"):
                    candidates.append((load_cfg, "weights_path", "X-VARS visual encoder checkpoint"))
            elif kind == "decoder":
                params = component.get("params")
                if isinstance(params, dict) and params.get("repo_id"):
                    candidates.append((params, "repo_id", "X-VARS base model bundle"))

        hf_cfg = execution.get("hf") if isinstance(execution, dict) else None
        if isinstance(hf_cfg, dict) and hf_cfg.get("tokenizer_id"):
            candidates.append((hf_cfg, "tokenizer_id", "X-VARS tokenizer bundle"))

        missing = []
        for owner, key, label in candidates:
            value = str(owner.get(key) or "")
            expanded = os.path.abspath(os.path.expanduser(value)) if os.path.isabs(os.path.expanduser(value)) else ""
            if not expanded or os.path.exists(expanded):
                continue
            adjacent = os.path.join(config_dir, os.path.basename(os.path.normpath(expanded)))
            if os.path.exists(adjacent):
                owner[key] = adjacent
            else:
                missing.append({"field": key, "description": label, "path": value})

        if missing:
            descriptions = ", ".join(sorted({item["description"] for item in missing}))
            raise InferenceError(
                "The VQA adapter config references unavailable files from its publisher's "
                f"machine: {descriptions}. Download the required X-VARS artifacts and "
                "update a local copy of config.yaml, or place them beside config.yaml.",
                code="local_model_dependency_missing",
                details={"missing": missing},
            )


@dataclass(frozen=True)
class _RemoteVqaSession:
    session_id: str
    touched_at: float


class RemoteVqaSessionCache:
    """Process-local cache for short-lived server-side VQA video sessions."""

    TTL_SECONDS = 25 * 60

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[tuple, _RemoteVqaSession] = {}

    def get(self, key: tuple) -> str | None:
        now = self._clock()
        with self._lock:
            record = self._sessions.get(key)
            if record is None:
                return None
            if now - record.touched_at >= self.TTL_SECONDS:
                self._sessions.pop(key, None)
                return None
            return record.session_id

    def put(self, key: tuple, session_id: str) -> None:
        with self._lock:
            self._sessions[key] = _RemoteVqaSession(str(session_id), self._clock())

    def discard(self, key: tuple) -> None:
        with self._lock:
            self._sessions.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


class RemoteInferenceProvider:
    """Adapter around the official OpenSportsLib remote inference client."""

    _SERVER_TASKS = {
        "classification": "classification",
        "localization": "localization",
        "question_answer": "vqa",
    }
    _VAT_TASKS = {server: vat for vat, server in _SERVER_TASKS.items()}

    def __init__(
        self,
        base_url: str,
        settings=None,
        *,
        client: httpx.Client | None = None,
        vqa_sessions: RemoteVqaSessionCache | None = None,
    ):
        self.base_url = normalize_server_url(base_url)
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=60.0))
        self._owns_client = client is None
        self._vqa_sessions = vqa_sessions or RemoteVqaSessionCache()
        self.capabilities: dict[str, Any] = {}
        self._catalog: list[ModelDescriptor] | None = None

    def close(self):
        if self._owns_client:
            self.client.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    @staticmethod
    def _error_from_response(response: httpx.Response) -> InferenceError:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, (list, dict)):
            detail = json.dumps(detail)
        message = str(detail or f"Server returned HTTP {response.status_code}.")
        return InferenceError(
            message,
            code=f"http_{response.status_code}",
            retryable=response.status_code >= 500 or response.status_code in {408, 429},
            details=payload or None,
        )

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self.client.request(method, self._url(path), **kwargs)
        except httpx.HTTPError as exc:
            raise InferenceError(str(exc), code="network_error", retryable=True) from exc
        if response.status_code >= 400:
            raise self._error_from_response(response)
        return response

    def discover_capabilities(self) -> dict[str, Any]:
        payload = self._request("GET", "/health").json()
        if not isinstance(payload, dict):
            raise InferenceError("Health response must be an object.", code="invalid_response")
        self.capabilities = payload
        return copy.deepcopy(payload)

    def model_operation(self, action: str, payload: dict, *, admin_token: str = ""):
        if not admin_token:
            raise ValueError("Enter the server administration token.")
        from opensportslib import RemoteModelRegistry

        registry = RemoteModelRegistry(self.base_url, admin_token=admin_token)
        task = {"question_answer": "vqa"}.get(
            str(payload.get("task") or ""), str(payload.get("task") or "")
        )
        if task not in {"classification", "localization", "vqa"}:
            raise ValueError(f"Unsupported remote model task: {payload.get('task')}")
        if action == "register_huggingface":
            return registry.register_model(
                task_type=task,
                huggingface_model_id=str(payload.get("repository_id") or ""),
            )
        if action == "register_local":
            return registry.register_model(
                task_type=task,
                model_id=str(payload.get("model_id") or "") or None,
                weights_path=str(payload.get("weights_path") or ""),
                config_path=str(payload.get("config_path") or "") or None,
            )
        if action == "unregister":
            return registry.unregister_model(str(payload.get("model_id") or ""))
        raise ValueError(f"Unknown remote model operation: {action}")

    def _discover_catalog(self) -> list[ModelDescriptor]:
        if self._catalog is not None:
            return self._catalog
        health = self.discover_capabilities()
        registry = self._request("GET", "/models").json()
        if not isinstance(registry, dict) or not isinstance(
            registry.get("models"), list
        ):
            raise InferenceError(
                "Model registry response must contain a models list.",
                code="invalid_response",
            )
        server_available = bool(
            health.get("status") == "ok"
            and health.get("redis_reachable")
            and health.get("worker_alive")
        )
        catalog = []
        for record in registry["models"]:
            if not isinstance(record, dict):
                raise InferenceError(
                    "Every model registry entry must be an object.",
                    code="invalid_response",
                )
            model_id = str(record.get("model_id") or "").strip()
            server_task = str(record.get("task_type") or "").strip()
            status = str(record.get("status") or "").strip().lower()
            if not model_id or not server_task or not status:
                raise InferenceError(
                    "A model registry entry is missing model_id, task_type, or status.",
                    code="invalid_response",
                )
            vat_task = self._VAT_TASKS.get(server_task)
            if vat_task is None:
                continue
            available = server_available and status == "ready"
            if not server_available:
                reason = "The server worker or Redis is unavailable."
            elif status == "registering":
                reason = "Model registration is still in progress."
            elif status == "unregistering":
                reason = "Model removal is still in progress."
            elif status == "failed":
                reason = str(record.get("error") or "Model registration failed.")
            elif status != "ready":
                reason = f"The server reports model status {status!r}."
            else:
                reason = ""
            generation = record.get("generation")
            catalog.append(
                ModelDescriptor(
                    id=model_id,
                    display_name=model_id,
                    task=vat_task,
                    version=(
                        f"generation-{generation}"
                        if generation not in (None, "")
                        else ""
                    ),
                    available=available,
                    unavailable_reason=reason,
                    accepted_input_types=("video",),
                    min_inputs=1,
                    max_inputs=1 if vat_task == "question_answer" else None,
                    supports_time_range=vat_task == "localization",
                    status=status,
                )
            )
        self._catalog = catalog
        return catalog

    def list_models(self, task: str) -> list[ModelDescriptor]:
        if task not in self._SERVER_TASKS:
            return []
        return [model for model in self._discover_catalog() if model.task == task]

    def run(self, request: InferenceRequest, progress: ProgressCallback, cancel_event=None):
        if request.task not in self._SERVER_TASKS:
            raise InferenceError(
                f"The OpenSportsLib server does not support {request.task} inference.",
                code="unsupported_task",
            )
        descriptor = next(
            (model for model in self.list_models(request.task) if model.id == request.model_id),
            None,
        )
        if descriptor is None:
            raise InferenceError(
                f"Unknown remote model: {request.model_id}", code="model_not_found"
            )
        if not descriptor.available:
            server_degraded = descriptor.status == "ready"
            raise InferenceError(
                descriptor.unavailable_reason,
                code=(
                    "server_unavailable" if server_degraded else "model_unavailable"
                ),
                retryable=server_degraded,
            )

        for item in request.items:
            if not item.inputs or any(source.type != "video" for source in item.inputs):
                raise InferenceError(
                    "Official remote inference requires video inputs.",
                    code="invalid_request",
                )
            if request.task == "question_answer" and len(item.inputs) != 1:
                raise InferenceError(
                    "Remote VQA requires exactly one video input per sample.",
                    code="invalid_request",
                )
            if descriptor.max_inputs is not None and len(item.inputs) > descriptor.max_inputs:
                raise InferenceError(
                    f"This remote model accepts at most {descriptor.max_inputs} video input(s) per sample.",
                    code="invalid_request",
                )
            for source in item.inputs:
                if not os.path.isfile(source.path):
                    raise InferenceError(
                        f"Input file does not exist: {source.path}",
                        code="input_not_found",
                    )

        runner = self._build_runner(request)
        results = []
        total = len(request.items)
        progress("Starting remote inference", 0, total)
        for index, item in enumerate(request.items, start=1):
            _check_cancelled(cancel_event)
            progress(f"Running remote inference ({index}/{total})", index - 1, total)
            try:
                raw = self._run_item(runner, request, item)
            except InferenceError:
                raise
            except Exception as exc:
                raise self._inference_error(exc) from exc
            _check_cancelled(cancel_event)
            results.append(self._normalize_item(request, item, raw))
            progress(f"Completed remote inference ({index}/{total})", index, total)
        return validate_result_payload(request, {"items": results})

    def _build_runner(self, request: InferenceRequest):
        from opensportslib.apis import ClassificationModel, LocalizationModel, VQAModel

        model_class = {
            "classification": ClassificationModel,
            "localization": LocalizationModel,
            "question_answer": VQAModel,
        }[request.task]
        try:
            return model_class(
                remote=self.base_url,
                remote_model_id=request.model_id,
            )
        except Exception as exc:
            mapped = self._inference_error(exc)
            if mapped.retryable:
                raise mapped from exc
            raise InferenceError(
                f"Could not load the remote model configuration for {request.model_id}: {exc}",
                code="model_config_unavailable",
            ) from exc

    def _run_item(self, runner, request, item):
        sources = item.inputs
        if request.task == "localization" and (
            int(request.parameters.get("start_ms", 0) or 0) > 0
            or int(request.parameters.get("end_ms", 0) or 0) > 0
        ):
            from controllers.localization.loc_inference import LocInferenceWorker

            with tempfile.TemporaryDirectory(prefix="vat_remote_clip_") as tmp_dir:
                prepared_sources = []
                clip_offsets = []
                for index, source in enumerate(sources):
                    clip_dir = os.path.join(tmp_dir, str(index))
                    os.makedirs(clip_dir, exist_ok=True)
                    clipper = LocInferenceWorker(
                        source.path,
                        int(request.parameters.get("start_ms", 0) or 0),
                        int(request.parameters.get("end_ms", 0) or 0),
                        "",
                        "",
                        "",
                        [],
                        float(source.metadata.get("fps", 25.0) or 25.0),
                    )
                    video_path, clip_offset = clipper._clip_video_if_needed(clip_dir)
                    prepared = copy.deepcopy(source)
                    prepared.path = video_path
                    prepared_sources.append(prepared)
                    clip_offsets.append(int(clip_offset or 0))
                prediction = self._infer_inputs(
                    runner, request, item, prepared_sources
                )
            offset = int(item.timeline_offset_ms or 0) + min(clip_offsets, default=0)
        else:
            prediction = self._infer_inputs(runner, request, item, sources)
            offset = int(item.timeline_offset_ms or 0)
        if request.task == "localization":
            data = prediction.get("data") if isinstance(prediction, dict) else None
            if isinstance(data, list):
                for raw_item in data:
                    if isinstance(raw_item, dict):
                        _project_localization_events(raw_item.get("events"), offset)
        return prediction

    def _infer_inputs(self, runner, request, item, sources):
        options = self._task_options(request, item)
        if request.task == "question_answer":
            return self._infer_vqa(
                runner, request, item, sources[0].path, options
            )
        if len(sources) > 1:
            return self._infer_manifest(runner, request, item, sources, options)
        return runner.infer(
            video_path=sources[0].path,
            use_wandb=False,
            remote_task_options=options,
        )

    @staticmethod
    def _infer_manifest(runner, request, item, sources, options):
        sample = {
            "id": item.sample_id,
            "inputs": [source.to_wire() for source in sources],
            "metadata": copy.deepcopy(options.get("sample_metadata") or {}),
        }
        if request.task == "localization":
            sample["events"] = []
        manifest = {
            "version": "2.0",
            "task": request.task,
            "labels": copy.deepcopy(options.get("label_schema") or {}),
            "data": [sample],
        }
        with tempfile.TemporaryDirectory(prefix="vat_remote_manifest_") as tmp_dir:
            manifest_path = os.path.join(tmp_dir, "request.json")
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            return runner.infer(
                test_set=manifest_path,
                remote_mode="full_test_set",
                use_wandb=False,
                remote_task_options=options,
            )

    def _infer_vqa(self, runner, request, item, video_path, options):
        question = str(request.parameters.get("question") or "").strip()
        if not question:
            raise InferenceError("VQA inference requires a question.", code="invalid_request")
        key = self._vqa_session_key(request, item)
        session_id = self._vqa_sessions.get(key)
        if session_id:
            try:
                prediction = runner.infer(
                    question=question,
                    session_id=session_id,
                )
                self._vqa_sessions.put(key, session_id)
                return prediction
            except Exception as exc:
                if not self._stale_session_error(exc):
                    raise
                self._vqa_sessions.discard(key)

        prediction = runner.infer(
            video_path=video_path,
            question=question,
            use_wandb=False,
            remote_task_options=options,
        )
        session_id = str(getattr(runner, "last_remote_session_id", None) or "")
        if session_id:
            self._vqa_sessions.put(key, session_id)
        return prediction

    def _task_options(self, request, item) -> dict[str, Any]:
        source = item.inputs[0]
        options = {
            "sample_id": item.sample_id,
            "sample_metadata": copy.deepcopy(item.sample.get("metadata") or {}),
            "fps": float(source.metadata.get("fps", 25.0) or 25.0),
        }
        if request.task in {"classification", "localization"}:
            head = str(request.parameters.get("head") or "action")
            head_schema = request.schema.get(head) or request.schema.get("action")
            if isinstance(head_schema, dict):
                options["label_schema"] = {"action": copy.deepcopy(head_schema)}
            elif request.parameters.get("labels"):
                options["label_schema"] = {
                    "action": {
                        "type": "single_label",
                        "labels": list(request.parameters["labels"]),
                    }
                }
        return options

    def _vqa_session_key(self, request, item) -> tuple:
        source_path = os.path.realpath(item.inputs[0].path)
        stat = os.stat(source_path)
        return (
            self.base_url,
            request.model_id,
            item.sample_id,
            source_path,
            stat.st_size,
            stat.st_mtime_ns,
        )

    @staticmethod
    def _stale_session_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "http 404" in message or "http 410" in message

    @staticmethod
    def _inference_error(exc: Exception) -> InferenceError:
        if isinstance(
            exc,
            (ConnectionError, TimeoutError, httpx.TransportError, httpx.TimeoutException),
        ):
            return InferenceError(str(exc), code="network_error", retryable=True)
        message = str(exc)
        lower = message.lower()
        if "timed out" in lower or "timeout" in lower or "could not reach" in lower:
            return InferenceError(message, code="network_error", retryable=True)
        if "http 404" in lower:
            return InferenceError(message, code="model_not_found")
        if "http 4" in lower:
            return InferenceError(message, code="invalid_request")
        return InferenceError(message, code="inference_error")

    @staticmethod
    def _normalize_item(request, request_item, prediction):
        raw_items = prediction.get("data") if isinstance(prediction, dict) else None
        if not isinstance(raw_items, list) or len(raw_items) != 1:
            raise InferenceError(
                "Direct remote inference must return one OSL data item.",
                code="invalid_result",
            )
        item = copy.deepcopy(raw_items[0])
        if not isinstance(item, dict):
            raise InferenceError("Remote prediction item must be an object.", code="invalid_result")
        item["item_id"] = request_item.item_id
        item["sample_id"] = request_item.sample_id
        if request.task == "classification":
            target_head = str(request.parameters.get("head") or "action")
            labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
            if target_head not in labels and "action" in labels:
                labels[target_head] = labels.pop("action")
            item["labels"] = labels
        elif request.task == "localization":
            target_head = str(request.parameters.get("head") or "action")
            events = item.get("events") if isinstance(item.get("events"), list) else []
            for event in events:
                if isinstance(event, dict) and event.get("head") == "action":
                    event["head"] = target_head
            item["events"] = events
        elif request.task == "question_answer" and "answer" not in item:
            if item.get("answer_text") is not None:
                item["answer"] = str(item.get("answer_text") or "")
            elif isinstance(item.get("answers"), list) and item["answers"]:
                first = copy.deepcopy(item["answers"][0])
                if isinstance(first, dict) and first.get("answer_text") is not None:
                    first["text"] = str(first.pop("answer_text") or "")
                item["answer"] = first
        return item
