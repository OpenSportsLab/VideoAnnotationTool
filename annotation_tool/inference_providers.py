"""Local OpenSportsLib and remote HTTP inference providers."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import httpx

from inference_settings import (
    load_local_models,
    load_shared_mappings,
    load_upload_manifests,
    save_upload_manifests,
)
from inference_types import (
    InferenceError,
    InferenceRequest,
    ModelDescriptor,
    validate_result_payload,
)


ProgressCallback = Callable[[str, int, int], None]


def _cancelled(cancel_event) -> bool:
    return bool(cancel_event is not None and cancel_event.is_set())


def _check_cancelled(cancel_event):
    if _cancelled(cancel_event):
        raise InferenceError("Inference cancelled.", code="cancelled")


class LocalInferenceProvider:
    """Task adapters around the public OpenSportsLib model API."""

    def __init__(self, settings=None, base_dir: str = "", *, local_models=None):
        self.settings = settings
        self.base_dir = base_dir or os.path.dirname(__file__)
        self.local_models = copy.deepcopy(local_models) if local_models is not None else None

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
                    descriptor.weights or descriptor.id,
                )
            else:
                runner = model_class(config=descriptor.config_path)
                output = runner.infer(test_set=dataset_path, weights=descriptor.weights or descriptor.id, use_wandb=False)
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
            captured, errors = [], []
            worker = LocInferenceWorker(
                item.inputs[0].path,
                int(request.parameters.get("start_ms", 0) or 0),
                int(request.parameters.get("end_ms", 0) or 0),
                descriptor.config_path,
                descriptor.weights or descriptor.id,
                str(request.parameters.get("head") or "ball_action"),
                list(request.parameters.get("labels") or []),
                float(item.inputs[0].metadata.get("fps", 25.0) or 25.0),
                trusted_legacy=descriptor.trusted_legacy,
            )
            worker.finished_signal.connect(captured.append)
            worker.error_signal.connect(errors.append)
            worker.run()
            if errors:
                raise InferenceError(errors[-1], code="local_inference_failed")
            results.append({"sample_id": item.sample_id, "events": captured[-1] if captured else []})
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
        for index, item in enumerate(request.items):
            _check_cancelled(cancel_event)
            if not item.inputs:
                raise InferenceError("Q/A input is missing.", code="invalid_request")
            runner = model.VQAModel(config=descriptor.config_path)
            output = runner.infer(
                video_path=item.inputs[0].path,
                question=question,
                weights=descriptor.weights or None,
                use_wandb=False,
            )
            answer = output.get("answer") if isinstance(output, dict) else output
            results.append({"sample_id": item.sample_id, "answer": answer})
            progress("Running local inference", index + 1, len(request.items))
        return {"items": results}


class RemoteInferenceProvider:
    """Versioned HTTP API client with shared-path and resumable multipart assets."""

    API_PREFIX = "/api/v1"

    def __init__(self, base_url: str, settings=None, *, client: httpx.Client | None = None, shared_mappings=None):
        self.base_url = str(base_url or "").rstrip("/")
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=60.0))
        self._owns_client = client is None
        self.capabilities: dict[str, Any] = {}
        self._progress_lock = threading.Lock()
        self.shared_mappings = copy.deepcopy(shared_mappings) if shared_mappings is not None else None

    def close(self):
        if self._owns_client:
            self.client.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{self.API_PREFIX}{path}"

    @staticmethod
    def _error_from_response(response: httpx.Response) -> InferenceError:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        return InferenceError(
            str(payload.get("message") or f"Server returned HTTP {response.status_code}."),
            code=str(payload.get("code") or f"http_{response.status_code}"),
            retryable=bool(payload.get("retryable", response.status_code >= 500)),
            details=payload.get("details"),
        )

    def _request(self, method: str, path_or_url: str, **kwargs) -> httpx.Response:
        url = path_or_url if path_or_url.startswith(("http://", "https://")) else self._url(path_or_url)
        try:
            response = self.client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise InferenceError(str(exc), code="network_error", retryable=True) from exc
        if response.status_code >= 400:
            raise self._error_from_response(response)
        return response

    def discover_capabilities(self) -> dict[str, Any]:
        payload = self._request("GET", "/capabilities").json()
        if not isinstance(payload, dict):
            raise InferenceError("Capabilities response must be an object.", code="invalid_response")
        self.capabilities = payload
        return copy.deepcopy(payload)

    def list_models(self, task: str) -> list[ModelDescriptor]:
        response = self._request("GET", "/models", params={"task": task})
        payload = response.json()
        raw_models = payload.get("models") if isinstance(payload, dict) else payload
        if not isinstance(raw_models, list):
            raise InferenceError("Models response must contain a models array.", code="invalid_response")
        models = []
        for raw in raw_models:
            descriptor = ModelDescriptor.from_dict(raw)
            if descriptor.task == task:
                models.append(descriptor)
        return models

    def run(self, request: InferenceRequest, progress: ProgressCallback, cancel_event=None):
        if not self.capabilities:
            self.discover_capabilities()
        wire_items = []
        time_offsets = {}
        all_inputs = sum(len(item.inputs) for item in request.items)
        prepared_count = 0
        for item in request.items:
            inputs = []
            for source in item.inputs:
                _check_cancelled(cancel_event)
                asset = self._shared_asset(source.path)
                if (
                    asset is None
                    and request.task == "localization"
                    and source.type == "video"
                    and (
                        int(request.parameters.get("start_ms", 0) or 0) > 0
                        or int(request.parameters.get("end_ms", 0) or 0) > 0
                    )
                ):
                    from controllers.localization.loc_inference import LocInferenceWorker

                    with tempfile.TemporaryDirectory(prefix="vat_remote_clip_") as tmp_dir:
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
                        clip_path, offset = clipper._clip_video_if_needed(tmp_dir)
                        asset = self._prepare_asset(clip_path, progress, cancel_event)
                        time_offsets[item.item_id] = int(offset)
                if asset is None:
                    asset = self._prepare_asset(source.path, progress, cancel_event)
                inputs.append(source.to_wire(asset))
                prepared_count += 1
                progress("Preparing inputs", prepared_count, max(1, all_inputs))
            wire_items.append({
                "item_id": item.item_id,
                "sample_id": item.sample_id,
                "inputs": inputs,
            })

        job_body = {
            "idempotency_key": request.request_id,
            "model_id": request.model_id,
            "task": request.task,
            "schema": copy.deepcopy(request.schema),
            "parameters": copy.deepcopy(request.parameters),
            "items": wire_items,
        }
        if time_offsets:
            job_body["parameters"]["input_time_offsets_ms"] = copy.deepcopy(time_offsets)
        progress("Submitting inference job", 0, 0)
        job = self._request(
            "POST", "/jobs", json=job_body, headers={"Idempotency-Key": request.request_id}
        ).json()
        job_id = str(job.get("id") or job.get("job_id") or "")
        if not job_id:
            raise InferenceError("Job response did not include an id.", code="invalid_response")

        poll_seconds = float(self.capabilities.get("poll_interval_seconds", 1.0) or 1.0)
        try:
            while True:
                if _cancelled(cancel_event):
                    try:
                        self._request("DELETE", f"/jobs/{quote(job_id, safe='')}")
                    finally:
                        raise InferenceError("Inference cancelled.", code="cancelled")
                response = self._request("GET", f"/jobs/{quote(job_id, safe='')}")
                state = response.json()
                status = str(state.get("status") or "").lower()
                progress(str(state.get("message") or status.title() or "Waiting for inference"), int(state.get("progress", 0) or 0), 100)
                if status == "succeeded":
                    result_payload = state.get("result")
                    if not isinstance(result_payload, dict):
                        result_payload = self._request("GET", f"/jobs/{quote(job_id, safe='')}/result").json()
                    if time_offsets:
                        raw_items = result_payload.get("items", []) if isinstance(result_payload, dict) else []
                        for index, raw_item in enumerate(raw_items if isinstance(raw_items, list) else []):
                            if not isinstance(raw_item, dict):
                                continue
                            item_id = str(raw_item.get("item_id") or (request.items[index].item_id if index < len(request.items) else ""))
                            offset = int(time_offsets.get(item_id, 0) or 0)
                            for event in list(raw_item.get("events") or []):
                                if isinstance(event, dict) and "position_ms" in event:
                                    event["position_ms"] = int(event.get("position_ms", 0) or 0) + offset
                    return validate_result_payload(request, result_payload)
                if status in {"failed", "cancelled"}:
                    error = state.get("error") if isinstance(state.get("error"), dict) else {}
                    raise InferenceError(
                        str(error.get("message") or state.get("message") or f"Job {status}."),
                        code=str(error.get("code") or status),
                        retryable=bool(error.get("retryable", False)),
                        details=error.get("details"),
                    )
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else poll_seconds
                except ValueError:
                    delay = poll_seconds
                cancel_event.wait(max(0.1, min(delay, 10.0))) if cancel_event is not None else time.sleep(max(0.1, min(delay, 10.0)))
        except Exception:
            raise

    def _shared_asset(self, path: str) -> dict[str, Any] | None:
        target = os.path.realpath(path)
        mappings = self.shared_mappings if self.shared_mappings is not None else load_shared_mappings(self.settings)
        for mapping in mappings:
            root = os.path.realpath(mapping["local_root"])
            try:
                if os.path.commonpath([target, root]) != root:
                    continue
            except ValueError:
                continue
            relative = os.path.relpath(target, root).replace(os.sep, "/")
            return {"kind": "shared", "uri": f"shared://{mapping['root_id']}/{quote(relative)}"}
        return None

    def _manifest_key(self, path: str) -> tuple[str, os.stat_result]:
        stat = os.stat(path)
        raw = f"{self.base_url}|{os.path.realpath(path)}|{stat.st_size}|{stat.st_mtime_ns}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest(), stat

    def _prepare_asset(self, path: str, progress, cancel_event):
        if not os.path.isfile(path):
            raise InferenceError(f"Input file does not exist: {path}", code="input_not_found")
        shared = self._shared_asset(path)
        if shared is not None:
            return shared

        key, stat = self._manifest_key(path)
        manifests = load_upload_manifests(self.settings)
        saved = manifests.get(key) if isinstance(manifests.get(key), dict) else {}
        if saved.get("asset_id"):
            return {"kind": "upload", "id": str(saved["asset_id"])}

        upload_id = str(saved.get("upload_id") or "")
        state = None
        if upload_id:
            try:
                state = self._request("GET", f"/uploads/{quote(upload_id, safe='')}").json()
            except InferenceError as exc:
                if exc.code not in {"http_404", "upload_not_found"}:
                    raise
        if not isinstance(state, dict):
            state = self._request("POST", "/uploads", json={
                "filename": os.path.basename(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }).json()
            upload_id = str(state.get("id") or state.get("upload_id") or "")
            if not upload_id:
                raise InferenceError("Upload response did not include an id.", code="invalid_response")
            manifests[key] = {
                "upload_id": upload_id,
                "path": os.path.realpath(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
            save_upload_manifests(self.settings, manifests)

        part_size = int(state.get("part_size") or self.capabilities.get("multipart_part_size") or 64 * 1024 * 1024)
        if part_size <= 0:
            raise InferenceError("Server returned an invalid multipart part size.", code="invalid_response")
        completed = {int(part.get("number")) for part in state.get("completed_parts", []) if isinstance(part, dict) and part.get("number")}
        total_parts = int(math.ceil(stat.st_size / part_size))
        pending = [number for number in range(1, total_parts + 1) if number not in completed]
        manifests = load_upload_manifests(self.settings)
        manifest_entry = manifests.setdefault(key, {"upload_id": upload_id})
        manifest_parts = manifest_entry.setdefault("parts", {})
        for part in state.get("completed_parts", []) or []:
            if not isinstance(part, dict) or not part.get("number"):
                continue
            manifest_parts[str(int(part["number"]))] = {
                field: str(part.get(field) or "") for field in ("etag", "sha256")
            }
        save_upload_manifests(self.settings, manifests)
        uploaded_bytes = min(stat.st_size, len(completed) * part_size)
        progress("Uploading inputs", uploaded_bytes, stat.st_size)

        max_workers = min(3, int(self.capabilities.get("max_parallel_parts", 3) or 3), max(1, len(pending)))
        if pending:
            try:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                    executor.submit(
                        self._upload_part_with_retry,
                        path,
                        upload_id,
                        number,
                        part_size,
                        stat.st_size,
                        state,
                        cancel_event,
                    ): number
                    for number in pending
                    }
                    for future in as_completed(futures):
                        _check_cancelled(cancel_event)
                        number, length, etag, checksum = future.result()
                        uploaded_bytes += length
                        progress("Uploading inputs", min(uploaded_bytes, stat.st_size), stat.st_size)
                        manifests = load_upload_manifests(self.settings)
                        entry = manifests.setdefault(key, {"upload_id": upload_id})
                        parts = entry.setdefault("parts", {})
                        parts[str(number)] = {"etag": etag, "sha256": checksum}
                        save_upload_manifests(self.settings, manifests)
            except InferenceError as exc:
                if exc.code == "cancelled":
                    try:
                        self.abort_upload(upload_id)
                    except InferenceError:
                        pass
                raise

        manifests = load_upload_manifests(self.settings)
        part_records = manifests.get(key, {}).get("parts", {})
        complete = self._request("POST", f"/uploads/{quote(upload_id, safe='')}/complete", json={
            "parts": [
                {"number": number, **dict(part_records.get(str(number), {}))}
                for number in range(1, total_parts + 1)
            ]
        }).json()
        asset_id = str(complete.get("asset_id") or complete.get("id") or upload_id)
        manifests.setdefault(key, {})["asset_id"] = asset_id
        save_upload_manifests(self.settings, manifests)
        return {"kind": "upload", "id": asset_id}

    def _part_spec(self, state: dict, upload_id: str, number: int) -> dict[str, Any]:
        for part in state.get("parts", []) or []:
            if isinstance(part, dict) and int(part.get("number", 0) or 0) == number:
                return part
        template = state.get("part_url_template")
        if template:
            return {"number": number, "url": str(template).replace("{part_number}", str(number))}
        return {"number": number, "url": self._url(f"/uploads/{quote(upload_id, safe='')}/parts/{number}")}

    @staticmethod
    def _part_checksum(path: str, offset: int, length: int, cancel_event) -> str:
        digest = hashlib.sha256()
        remaining = length
        with open(path, "rb") as handle:
            handle.seek(offset)
            while remaining:
                _check_cancelled(cancel_event)
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise InferenceError("Input file changed during upload.", code="input_changed")
                digest.update(chunk)
                remaining -= len(chunk)
        return digest.hexdigest()

    @staticmethod
    def _part_stream(path: str, offset: int, length: int, cancel_event):
        remaining = length
        with open(path, "rb") as handle:
            handle.seek(offset)
            while remaining:
                _check_cancelled(cancel_event)
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise InferenceError("Input file changed during upload.", code="input_changed")
                remaining -= len(chunk)
                yield chunk

    def _upload_part_with_retry(self, path, upload_id, number, part_size, file_size, state, cancel_event):
        offset = (number - 1) * part_size
        length = min(part_size, file_size - offset)
        checksum = self._part_checksum(path, offset, length, cancel_event)
        last_error = None
        current_state = state
        for attempt in range(5):
            _check_cancelled(cancel_event)
            spec = self._part_spec(current_state, upload_id, number)
            headers = {str(k): str(v) for k, v in dict(spec.get("headers") or {}).items()}
            headers.setdefault("Content-Length", str(length))
            checksum_header = str(spec.get("checksum_header") or "")
            if not checksum_header and str(spec.get("url") or "").startswith(self.base_url):
                checksum_header = "X-Content-SHA256"
            if checksum_header:
                headers.setdefault(checksum_header, checksum)
            try:
                response = self._request(
                    str(spec.get("method") or "PUT").upper(),
                    str(spec["url"]),
                    headers=headers,
                    content=self._part_stream(path, offset, length, cancel_event),
                    timeout=httpx.Timeout(30.0, read=300.0, write=300.0),
                )
                returned_checksum = str(
                    response.headers.get("X-Content-SHA256")
                    or response.headers.get("X-Checksum-SHA256")
                    or ""
                ).strip()
                if returned_checksum and returned_checksum != checksum:
                    raise InferenceError(
                        f"Checksum mismatch for upload part {number}.",
                        code="checksum_mismatch",
                        retryable=True,
                    )
                return number, length, response.headers.get("ETag", "").strip('"'), checksum
            except InferenceError as exc:
                last_error = exc
                if not exc.retryable and exc.code not in {"http_401", "http_403", "http_408", "http_429"}:
                    break
                if exc.code in {"http_401", "http_403"}:
                    current_state = self._request("GET", f"/uploads/{quote(upload_id, safe='')}").json()
                delay = min(8.0, (2**attempt) * 0.25 + random.random() * 0.25)
                cancel_event.wait(delay) if cancel_event is not None else time.sleep(delay)
        raise last_error or InferenceError("Part upload failed.", code="upload_failed", retryable=True)

    def abort_upload(self, upload_id: str):
        self._request("DELETE", f"/uploads/{quote(str(upload_id), safe='')}")
