"""Canonical inference execution owner for all annotation modes."""

from __future__ import annotations

import copy
import os
import threading
import time
from collections import deque
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QSettings, QThread, pyqtSignal

from inference_providers import (
    LocalInferenceProvider,
    RemoteInferenceProvider,
    RemoteVqaSessionCache,
)
from inference_history import InferenceHistoryStore
from inference_settings import (
    LOCAL_PROVIDER_ID,
    load_inference_providers,
    load_local_models,
    normalize_server_url,
    update_provider_catalog,
    update_provider_status,
)
from inference_types import (
    INFERENCE_TASKS,
    InferenceError,
    InferenceLogEvent,
    InferenceModelChoice,
    InferenceQueueEntry,
    InferenceRequest,
    ModelDescriptor,
)


@dataclass
class _QueueRecord:
    request: InferenceRequest
    state: str = "queued"
    message: str = "Queued"
    current: int = 0
    total: int = 0
    submitted_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    error_code: str = ""
    error_details: object = None
    retryable: bool = False
    log_events: list[InferenceLogEvent] | None = None


class _InferenceWorker(QThread):
    progress = pyqtSignal(str, int, int)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str, str, bool, object)

    def __init__(self, provider, request: InferenceRequest):
        super().__init__()
        self.provider = provider
        self.request = request
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            result = self.provider.run(self.request, self.progress.emit, self.cancel_event)
            if self.cancel_event.is_set():
                raise InferenceError("Inference cancelled.", code="cancelled")
            self.succeeded.emit(result)
        except InferenceError as exc:
            self.failed.emit(str(exc), exc.code, exc.retryable, exc.details)
        except Exception as exc:
            self.failed.emit(str(exc), "unexpected_error", False, None)
        finally:
            close = getattr(self.provider, "close", None)
            if callable(close):
                close()


class _ModelDiscoveryWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, provider, task: str):
        super().__init__()
        self.provider = provider
        self.task = task

    def run(self):
        try:
            self.succeeded.emit(self.provider.list_models(self.task))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            close = getattr(self.provider, "close", None)
            if callable(close):
                close()


class _CatalogDiscoveryWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation())
        except Exception as exc:
            self.failed.emit(str(exc))


class _RemoteRegistryWorker(QThread):
    succeeded = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)

    def __init__(self, action: str, operation):
        super().__init__()
        self.action = action
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.action, self.operation())
        except Exception as exc:
            self.failed.emit(self.action, str(exc))


class InferenceController(QObject):
    modelsDiscovered = pyqtSignal(str, str, object)
    discoveryFailed = pyqtSignal(str, str, str)
    modelCatalogDiscovered = pyqtSignal(str, object, str)
    modelCatalogFailed = pyqtSignal(str, str)
    providerCatalogDiscovered = pyqtSignal(str, object)
    providerCatalogFailed = pyqtSignal(str, str)
    providerModelOperationStarted = pyqtSignal(str)
    providerModelOperationSucceeded = pyqtSignal(str, object)
    providerModelOperationFailed = pyqtSignal(str, str)
    inferenceStarted = pyqtSignal(str, str)
    inferenceProgress = pyqtSignal(str, str, int, int)
    inferenceCompleted = pyqtSignal(str, object)
    inferenceFailed = pyqtSignal(str, str, str, bool, object)
    inferenceCancelled = pyqtSignal(str)
    queueChanged = pyqtSignal(object)
    historyErrorChanged = pyqtSignal(str)

    SETTINGS_ORG = "OpenSportsLab"
    SETTINGS_APP = "VideoAnnotationTool"
    MAX_LOG_EVENTS_PER_JOB = 200

    def __init__(self, settings=None, base_dir: str = "", parent=None, history_path=None):
        super().__init__(parent)
        self.settings = settings or QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self.base_dir = base_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self._queues = {}
        self._workers = {}
        self._active_records = {}
        self._records = {}
        self._seen_request_ids = set()
        self._history_store = InferenceHistoryStore(history_path)
        self._history = self._history_store.load()
        self.history_error = self._history_store.error
        self._remote_vqa_sessions = RemoteVqaSessionCache()
        self._shutting_down = False
        self.discovery_worker: QThread | None = None
        self.provider_registry_worker: QThread | None = None

    def configuration_snapshot(self) -> dict:
        providers = copy.deepcopy(load_inference_providers(self.settings))
        for provider in providers:
            provider.pop("admin_token", None)
        return {"providers": providers}

    def _provider(self, provider_id: str, config=None):
        config = dict(config or {})
        providers = list(config.get("providers") or [])
        provider_config = next(
            (item for item in providers if item.get("id") == provider_id), None
        )
        # Compatibility for older callers and requests created before migration.
        if provider_config is None and provider_id in {"local", "remote"}:
            if provider_id == "local":
                provider_config = {
                    "id": LOCAL_PROVIDER_ID,
                    "kind": "local",
                    "models": config.get("local_models", load_local_models(self.settings)),
                }
            else:
                provider_config = {
                    "id": "remote",
                    "kind": "remote",
                    "url": config.get("server_url", "http://127.0.0.1:8000"),
                }
        if provider_config is None:
            provider_config = next(
                (
                    item for item in load_inference_providers(self.settings)
                    if item.get("id") == provider_id
                ),
                None,
            )
        if provider_config is None:
            raise ValueError(f"Inference provider {provider_id!r} is unavailable.")
        if provider_config.get("kind") == "local":
            models = provider_config.get("models")
            return LocalInferenceProvider(self.settings, self.base_dir, local_models=models)
        url = normalize_server_url(str(provider_config.get("url") or ""))
        return RemoteInferenceProvider(
            url,
            self.settings,
            vqa_sessions=self._remote_vqa_sessions,
        )

    def clear_remote_sessions(self) -> None:
        self._remote_vqa_sessions.clear()

    def discover_models(self, task: str, backend: str | None = None, config=None):
        selected_backend = backend or LOCAL_PROVIDER_ID
        provider = self._provider(selected_backend, config)
        try:
            models = provider.list_models(task)
            self.modelsDiscovered.emit(selected_backend, task, models)
            return models
        except Exception as exc:
            self.discoveryFailed.emit(selected_backend, task, str(exc))
            return []
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

    def request_model_discovery(self, task: str, backend: str | None = None, config=None) -> bool:
        if self.discovery_worker is not None and self.discovery_worker.isRunning():
            return False
        selected_backend = backend or "local"
        worker = _ModelDiscoveryWorker(self._provider(selected_backend, config), task)
        worker.succeeded.connect(
            lambda models, b=selected_backend, t=task: self.modelsDiscovered.emit(b, t, models)
        )
        worker.failed.connect(
            lambda message, b=selected_backend, t=task: self.discoveryFailed.emit(b, t, message)
        )
        worker.finished.connect(lambda ref=worker: self._cleanup_discovery_worker(ref))
        self.discovery_worker = worker
        worker.start()
        return True

    def discover_model_catalog(self, task: str, config=None):
        """Return runnable models from Local and every enabled remote provider."""
        snapshot = self.configuration_snapshot() if config is None else dict(config)
        if "providers" not in snapshot:
            snapshot["providers"] = [{
                "id": "local", "kind": "local", "name": "Local",
                "enabled": True, "models": snapshot.get("local_models", []),
                "defaults": {},
            }]
            if snapshot.get("remote_enabled"):
                snapshot["providers"].append({
                    "id": "remote", "kind": "remote", "name": "Remote",
                    "enabled": True,
                    "url": snapshot.get("server_url", "http://127.0.0.1:8000"),
                    "models": [], "defaults": {},
                })
        choices = []
        warnings = []
        for provider_config in snapshot.get("providers", []):
            if provider_config.get("kind") == "remote" and not provider_config.get("enabled"):
                continue
            provider_id = str(provider_config.get("id") or "")
            provider_name = str(provider_config.get("name") or provider_id)
            kind = str(provider_config.get("kind") or "local")
            provider = self._provider(provider_id, snapshot)
            try:
                models = provider.list_models(task)
                if kind == "remote":
                    update_provider_catalog(
                        self.settings,
                        provider_id,
                        self._all_remote_models(provider),
                        status="Ready",
                    )
                default_id = str((provider_config.get("defaults") or {}).get(task) or "")
                models = sorted(
                    models,
                    key=lambda descriptor: not (
                        descriptor.is_default or descriptor.id == default_id
                    ),
                )
                for descriptor in models:
                    if descriptor.available:
                        choices.append(InferenceModelChoice(
                            kind, descriptor, provider_id, provider_name
                        ))
                unavailable = sum(not descriptor.available for descriptor in models)
                if unavailable:
                    warnings.append(
                        f"{unavailable} unavailable {provider_name} model(s) omitted."
                    )
            except Exception as exc:
                cached = []
                if kind == "remote":
                    for model in provider_config.get("models", []):
                        try:
                            descriptor = ModelDescriptor.from_dict(model)
                        except Exception:
                            continue
                        if descriptor.task == task and descriptor.available:
                            cached.append(descriptor)
                            choices.append(InferenceModelChoice(
                                kind, descriptor, provider_id, provider_name
                            ))
                suffix = " Using the cached catalog." if cached else ""
                warnings.append(f"{provider_name}: {exc}.{suffix}")
                if kind == "remote":
                    update_provider_status(
                        self.settings, provider_id,
                        f"Stale catalog; refresh failed: {exc}",
                    )
            finally:
                close = getattr(provider, "close", None)
                if callable(close):
                    close()
        return choices, " ".join(warnings)

    @staticmethod
    def _all_remote_models(provider):
        models_by_key = {}
        errors = []
        successful_tasks = 0
        for provider_task in INFERENCE_TASKS:
            try:
                descriptors = provider.list_models(provider_task)
                successful_tasks += 1
            except Exception as exc:
                errors.append(exc)
                continue
            for descriptor in descriptors:
                models_by_key[(descriptor.task, descriptor.id)] = descriptor
        if successful_tasks == 0 and errors:
            raise errors[0]
        return list(models_by_key.values())

    def request_model_catalog(self, task: str) -> bool:
        if self.discovery_worker is not None and self.discovery_worker.isRunning():
            return False
        snapshot = self.configuration_snapshot()
        worker = _CatalogDiscoveryWorker(
            lambda t=task, c=snapshot: self.discover_model_catalog(t, c)
        )
        worker.succeeded.connect(
            lambda result, t=task: self.modelCatalogDiscovered.emit(
                t, result[0], result[1]
            )
        )
        worker.failed.connect(lambda message, t=task: self.modelCatalogFailed.emit(t, message))
        worker.finished.connect(lambda ref=worker: self._cleanup_discovery_worker(ref))
        self.discovery_worker = worker
        worker.start()
        return True

    def discover_provider_catalog(self, config) -> list:
        snapshot = dict(config or {})
        provider_id = str(snapshot.get("provider_id") or "remote")
        provider = self._provider(provider_id, snapshot)
        try:
            models = self._all_remote_models(provider)
            update_provider_catalog(self.settings, provider_id, models, status="Ready")
            return models
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

    def request_provider_catalog(self, config) -> bool:
        if self.discovery_worker is not None and self.discovery_worker.isRunning():
            return False
        snapshot = dict(config or {})
        provider_id = str(snapshot.get("provider_id") or "remote")
        worker = _CatalogDiscoveryWorker(
            lambda c=snapshot: self.discover_provider_catalog(c)
        )
        worker.succeeded.connect(
            lambda models, pid=provider_id: self.providerCatalogDiscovered.emit(
                pid, models
            )
        )
        worker.failed.connect(
            lambda message, pid=provider_id: self.providerCatalogFailed.emit(
                pid, message
            )
        )
        worker.finished.connect(lambda ref=worker: self._cleanup_discovery_worker(ref))
        self.discovery_worker = worker
        worker.start()
        return True

    def request_all_remote_catalogs(self, config=None) -> bool:
        if self.discovery_worker is not None and self.discovery_worker.isRunning():
            return False
        snapshot = self.configuration_snapshot() if config is None else dict(config)

        def operation():
            results = []
            for provider_config in snapshot.get("providers", []):
                if provider_config.get("kind") != "remote" or not provider_config.get("enabled"):
                    continue
                provider_id = str(provider_config.get("id") or "")
                provider = self._provider(provider_id, snapshot)
                try:
                    models = self._all_remote_models(provider)
                    update_provider_catalog(self.settings, provider_id, models, status="Ready")
                    results.append((provider_id, models, ""))
                except Exception as exc:
                    update_provider_status(
                        self.settings, provider_id,
                        f"Stale catalog; refresh failed: {exc}",
                    )
                    results.append((provider_id, None, str(exc)))
                finally:
                    provider.close()
            return results

        worker = _CatalogDiscoveryWorker(operation)
        worker.succeeded.connect(self._on_all_catalogs_discovered)
        worker.failed.connect(lambda message: self.providerCatalogFailed.emit("", message))
        worker.finished.connect(lambda ref=worker: self._cleanup_discovery_worker(ref))
        self.discovery_worker = worker
        worker.start()
        return True

    def _on_all_catalogs_discovered(self, results):
        for provider_id, models, error in results:
            if error:
                self.providerCatalogFailed.emit(provider_id, error)
            else:
                self.providerCatalogDiscovered.emit(provider_id, models)

    def request_provider_model_operation(
        self, action: str, configuration: dict
    ) -> bool:
        if (
            self._shutting_down
            or (
                self.provider_registry_worker is not None
                and self.provider_registry_worker.isRunning()
            )
        ):
            return False
        action = str(action or "")
        payload = copy.deepcopy(configuration or {})
        provider_id = str(payload.pop("provider_id", "") or "")
        server_url = normalize_server_url(
            str(payload.pop("server_url", payload.pop("url", "")) or "")
        )
        admin_token = str(payload.pop("admin_token", "") or "")
        if not admin_token:
            raise ValueError("Enter the server administration token.")

        def operation():
            provider = RemoteInferenceProvider(
                server_url, self.settings, vqa_sessions=self._remote_vqa_sessions
            )
            try:
                result = provider.model_operation(
                    action, payload, admin_token=admin_token
                )
                return {"provider_id": provider_id, "result": result}
            finally:
                provider.close()

        worker = _RemoteRegistryWorker(action, operation)
        worker.succeeded.connect(self.providerModelOperationSucceeded.emit)
        worker.failed.connect(self.providerModelOperationFailed.emit)
        worker.finished.connect(
            lambda ref=worker: self._cleanup_provider_registry_worker(ref)
        )
        self.provider_registry_worker = worker
        self.providerModelOperationStarted.emit(action)
        worker.start()
        return True

    def test_connection(self, config=None) -> dict:
        snapshot = dict(config or {})
        provider = self._provider(str(snapshot.get("provider_id") or "remote"), snapshot)
        try:
            return provider.discover_capabilities()
        finally:
            provider.close()

    def enqueue_inference(
        self, request: InferenceRequest
    ) -> InferenceQueueEntry | None:
        if self._shutting_down or request.request_id in self._seen_request_ids:
            return None
        submitted_at = time.time()
        record = _QueueRecord(
            request=copy.deepcopy(request),
            submitted_at=submitted_at,
            log_events=[],
        )
        self._append_log(record, "queued", "Queued", timestamp=submitted_at)
        self._seen_request_ids.add(request.request_id)
        self._records[request.request_id] = record
        lane = request.provider_id
        self._queues.setdefault(lane, deque()).append(record)
        self._workers.setdefault(lane, None)
        self._active_records.setdefault(lane, None)
        self._dispatch_next(lane)
        self._emit_queue_changed()
        return self._entry_for_record(record)

    def _dispatch_next(self, lane: str) -> None:
        if self._shutting_down or self._workers.get(lane) is not None:
            return
        queue = self._queues.setdefault(lane, deque())
        while queue and self._workers.get(lane) is None and not self._shutting_down:
            record = queue.popleft()
            request = record.request
            record.state = "running"
            record.message = "Starting inference"
            record.started_at = time.time()
            self._append_log(
                record,
                "running",
                record.message,
                timestamp=record.started_at,
            )
            self._active_records[lane] = record
            try:
                provider = self._provider(request.provider_id, request.provider_config)
            except Exception as exc:
                self._active_records[lane] = None
                self._terminalize(
                    record,
                    "failed",
                    str(exc),
                    error_code="provider_initialization_failed",
                )
                self.inferenceFailed.emit(
                    request.request_id,
                    str(exc),
                    "provider_initialization_failed",
                    False,
                    None,
                )
                continue
            worker = _InferenceWorker(provider, request)
            worker.progress.connect(
                lambda message, current, total, b=lane, rid=request.request_id: self._on_worker_progress(
                    b, rid, message, current, total
                )
            )
            worker.succeeded.connect(
                lambda result, b=lane, rid=request.request_id: self._on_worker_succeeded(
                    b, rid, result
                )
            )
            worker.failed.connect(
                lambda message, code, retryable, details, b=lane, rid=request.request_id: self._on_worker_failed(
                    b, rid, message, code, retryable, details
                )
            )
            worker.finished.connect(
                lambda b=lane, ref=worker: self._cleanup_worker(b, ref)
            )
            self._workers[lane] = worker
            self.inferenceStarted.emit(request.request_id, request.task)
            worker.start()

    def _on_worker_progress(self, backend, request_id, message, current, total):
        record = self._active_records.get(backend)
        if record is None or record.request.request_id != request_id:
            return
        record.message = str(message or "")
        record.current = max(0, int(current or 0))
        record.total = max(0, int(total or 0))
        self._append_log(
            record,
            "running",
            record.message,
            current=record.current,
            total=record.total,
            coalesce_progress=True,
        )
        self.inferenceProgress.emit(
            request_id, record.message, record.current, record.total
        )
        self._emit_queue_changed()

    def _on_worker_succeeded(self, backend, request_id, result):
        record = self._active_records.get(backend)
        if record is None or record.request.request_id != request_id:
            return
        self._terminalize(record, "succeeded", "Succeeded")
        self.inferenceCompleted.emit(request_id, result)
        self._emit_queue_changed()

    def _on_worker_failed(self, backend, request_id, message, code, retryable, details):
        record = self._active_records.get(backend)
        if record is None or record.request.request_id != request_id:
            return
        state = "cancelled" if code == "cancelled" else "failed"
        self._terminalize(
            record,
            state,
            str(message or state.title()),
            error_code=str(code or ""),
            error_details=details,
            retryable=bool(retryable),
        )
        if state == "cancelled":
            self.inferenceCancelled.emit(request_id)
        else:
            self.inferenceFailed.emit(request_id, message, code, retryable, details)
        self._emit_queue_changed()

    def _terminalize(
        self,
        record,
        state,
        message,
        *,
        error_code="",
        error_details=None,
        retryable=False,
    ):
        record.state = state
        record.message = str(message or "")
        record.finished_at = time.time()
        record.error_code = str(error_code or "")
        record.error_details = error_details
        record.retryable = bool(retryable)
        level = "error" if state == "failed" else "info"
        self._append_log(
            record,
            state,
            record.message,
            level=level,
            timestamp=record.finished_at,
            current=record.current,
            total=record.total,
            details=error_details,
        )
        self._records.pop(record.request.request_id, None)
        entry = self._entry_for_record(record, queue_position=-1)
        self._history.append(entry)
        self._history_store.append(entry)
        if self._history_store.error and self._history_store.error != self.history_error:
            self.history_error = self._history_store.error
            self.historyErrorChanged.emit(self.history_error)

    def _append_log(
        self,
        record,
        state,
        message,
        *,
        level="info",
        timestamp=None,
        current=0,
        total=0,
        details=None,
        coalesce_progress=False,
    ):
        events = record.log_events
        if events is None:
            events = []
            record.log_events = events
        event = InferenceLogEvent(
            timestamp=float(timestamp if timestamp is not None else time.time()),
            state=str(state or ""),
            message=str(message or ""),
            level=str(level or "info"),
            current=max(0, int(current or 0)),
            total=max(0, int(total or 0)),
            details=copy.deepcopy(details),
        )
        if (
            coalesce_progress
            and events
            and events[-1].state == event.state
            and events[-1].message == event.message
        ):
            events[-1] = event
            return
        events.append(event)
        if len(events) > self.MAX_LOG_EVENTS_PER_JOB:
            del events[1 : len(events) - self.MAX_LOG_EVENTS_PER_JOB + 1]

    def cancel_request(self, request_id: str) -> bool:
        request_id = str(request_id or "")
        for lane in tuple(self._queues):
            active = self._active_records.get(lane)
            if active is not None and active.request.request_id == request_id:
                if active.state not in {"running", "cancelling"}:
                    return False
                active.state = "cancelling"
                active.message = "Cancelling inference"
                self._append_log(active, "cancelling", active.message)
                worker = self._workers.get(lane)
                if worker is not None:
                    worker.cancel()
                self._emit_queue_changed()
                return True
            queue = self._queues[lane]
            for record in list(queue):
                if record.request.request_id != request_id:
                    continue
                queue.remove(record)
                self._terminalize(
                    record,
                    "cancelled",
                    "Cancelled before execution",
                    error_code="cancelled",
                )
                self.inferenceCancelled.emit(request_id)
                self._emit_queue_changed()
                return True
        return False

    def cancel_all(self) -> int:
        cancelled = 0
        for lane in tuple(self._queues):
            for record in list(self._queues[lane]):
                if self.cancel_request(record.request.request_id):
                    cancelled += 1
            active = self._active_records.get(lane)
            if active is not None and self.cancel_request(active.request.request_id):
                cancelled += 1
        return cancelled

    def queue_snapshot(self) -> tuple[InferenceQueueEntry, ...]:
        entries = []
        for lane in self._queues:
            active = self._active_records.get(lane)
            if active is not None and active.state in {"running", "cancelling"}:
                entries.append(self._entry_for_record(active, queue_position=0))
            entries.extend(
                self._entry_for_record(record, queue_position=index)
                for index, record in enumerate(self._queues[lane], start=1)
            )
        entries.extend(reversed(self._history))
        return tuple(entries)

    def _entry_for_record(self, record, queue_position=None):
        if queue_position is None:
            if record.state in {"running", "cancelling"}:
                queue_position = 0
            else:
                try:
                    queue_position = list(self._queues[record.request.provider_id]).index(record) + 1
                except ValueError:
                    queue_position = -1
        request = record.request
        return InferenceQueueEntry(
            request_id=request.request_id,
            backend=request.backend,
            task=request.task,
            model_id=request.model_id,
            sample_ids=tuple(item.sample_id for item in request.items),
            state=record.state,
            message=record.message,
            current=record.current,
            total=record.total,
            queue_position=int(queue_position),
            submitted_at=record.submitted_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            error_code=record.error_code,
            error_details=record.error_details,
            retryable=record.retryable,
            log_events=tuple(record.log_events or ()),
            provider_id=request.provider_id,
            provider_name=request.provider_name,
        )

    def _emit_queue_changed(self):
        self.queueChanged.emit(self.queue_snapshot())

    def clear_queue_history(self) -> None:
        self._history.clear()
        self._history_store.clear()
        if self._history_store.error and self._history_store.error != self.history_error:
            self.history_error = self._history_store.error
            self.historyErrorChanged.emit(self.history_error)
        self._emit_queue_changed()

    def has_running_inference(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in self._workers.values()
        )

    def shutdown(self, wait_ms: int = 3000) -> bool:
        self._shutting_down = True
        self.clear_remote_sessions()
        self.cancel_all()
        deadline = time.monotonic() + max(0, int(wait_ms)) / 1000.0
        if self.discovery_worker is not None and self.discovery_worker.isRunning():
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if not self.discovery_worker.wait(remaining):
                return False
        if (
            self.provider_registry_worker is not None
            and self.provider_registry_worker.isRunning()
        ):
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if not self.provider_registry_worker.wait(remaining):
                return False
        workers = {
            worker
            for worker in self._workers.values()
            if worker is not None
        }
        for worker in workers:
            if worker is None or not worker.isRunning():
                continue
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if not worker.wait(remaining):
                return False
        self.clear_remote_sessions()
        self._queues.clear()
        self._workers.clear()
        self._active_records.clear()
        self._records.clear()
        self._seen_request_ids.clear()
        self.clear_queue_history()
        self._history_store.close()
        return True

    def _cleanup_discovery_worker(self, worker):
        if self.discovery_worker is worker:
            self.discovery_worker = None
        worker.deleteLater()

    def _cleanup_provider_registry_worker(self, worker):
        if self.provider_registry_worker is worker:
            self.provider_registry_worker = None
        worker.deleteLater()

    def _cleanup_worker(self, lane, worker):
        if self._workers.get(lane) is worker:
            self._workers[lane] = None
            self._active_records[lane] = None
        worker.deleteLater()
        if self._shutting_down:
            self.clear_remote_sessions()
        else:
            self._dispatch_next(lane)
        self._emit_queue_changed()
