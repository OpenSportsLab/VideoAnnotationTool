"""Canonical inference execution owner for all annotation modes."""

from __future__ import annotations

import copy
import os
import threading
import time
from collections import deque
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QSettings, QThread, pyqtSignal

from inference_providers import LocalInferenceProvider, RemoteInferenceProvider
from inference_settings import (
    DEFAULT_SERVER_URL,
    SERVER_URL_KEY,
    load_local_models,
    load_shared_mappings,
    normalize_server_url,
    remote_inference_enabled,
)
from inference_types import (
    INFERENCE_TASKS,
    InferenceError,
    InferenceLogEvent,
    InferenceModelChoice,
    InferenceQueueEntry,
    InferenceRequest,
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


class InferenceController(QObject):
    modelsDiscovered = pyqtSignal(str, str, object)
    discoveryFailed = pyqtSignal(str, str, str)
    modelCatalogDiscovered = pyqtSignal(str, object, str)
    modelCatalogFailed = pyqtSignal(str, str)
    remoteCatalogDiscovered = pyqtSignal(object)
    remoteCatalogFailed = pyqtSignal(str)
    inferenceStarted = pyqtSignal(str, str)
    inferenceProgress = pyqtSignal(str, str, int, int)
    inferenceCompleted = pyqtSignal(str, object)
    inferenceFailed = pyqtSignal(str, str, str, bool, object)
    inferenceCancelled = pyqtSignal(str)
    queueChanged = pyqtSignal(object)

    SETTINGS_ORG = "OpenSportsLab"
    SETTINGS_APP = "VideoAnnotationTool"
    MAX_LOG_EVENTS_PER_JOB = 200

    def __init__(self, settings=None, base_dir: str = "", parent=None):
        super().__init__(parent)
        self.settings = settings or QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self.base_dir = base_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self._queues = {"local": deque(), "remote": deque()}
        self._workers = {"local": None, "remote": None}
        self._active_records = {"local": None, "remote": None}
        self._records = {}
        self._seen_request_ids = set()
        self._history = deque(maxlen=20)
        self._shutting_down = False
        self.discovery_worker: QThread | None = None

    def configuration_snapshot(self) -> dict:
        return {
            "remote_enabled": remote_inference_enabled(self.settings),
            "server_url": normalize_server_url(str(self.settings.value(SERVER_URL_KEY, DEFAULT_SERVER_URL) or DEFAULT_SERVER_URL)),
            "shared_mappings": load_shared_mappings(self.settings),
            "local_models": load_local_models(self.settings),
        }

    def _provider(self, backend: str, config=None):
        config = dict(config or {})
        if backend == "local":
            models = config.get("local_models") if "local_models" in config else None
            return LocalInferenceProvider(self.settings, self.base_dir, local_models=models)
        url = normalize_server_url(str(config.get("server_url") or self.settings.value(SERVER_URL_KEY, DEFAULT_SERVER_URL) or DEFAULT_SERVER_URL))
        mappings = config.get("shared_mappings") if "shared_mappings" in config else None
        return RemoteInferenceProvider(url, self.settings, shared_mappings=mappings)

    def discover_models(self, task: str, backend: str | None = None, config=None):
        selected_backend = backend or "local"
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
        """Return runnable Local and enabled-Remote models for one task."""
        snapshot = self.configuration_snapshot() if config is None else dict(config)
        choices = []
        warnings = []
        local_provider = self._provider("local", snapshot)
        try:
            local_models = local_provider.list_models(task)
            for descriptor in local_models:
                if descriptor.available:
                    choices.append(InferenceModelChoice("local", descriptor))
            unavailable = sum(not descriptor.available for descriptor in local_models)
            if unavailable:
                warnings.append(f"{unavailable} unavailable Local model(s) omitted.")
        except Exception as exc:
            warnings.append(f"Local models: {exc}")
        finally:
            close = getattr(local_provider, "close", None)
            if callable(close):
                close()

        remote_enabled = snapshot.get("remote_enabled", False)
        if isinstance(remote_enabled, str):
            remote_enabled = remote_enabled.strip().lower() in {"1", "true", "yes", "on"}
        if bool(remote_enabled):
            remote_provider = self._provider("remote", snapshot)
            try:
                remote_models = remote_provider.list_models(task)
                for descriptor in remote_models:
                    if descriptor.available:
                        choices.append(InferenceModelChoice("remote", descriptor))
                unavailable = sum(not descriptor.available for descriptor in remote_models)
                if unavailable:
                    warnings.append(f"{unavailable} unavailable Remote model(s) omitted.")
            except Exception as exc:
                warnings.append(f"Remote models: {exc}")
            finally:
                close = getattr(remote_provider, "close", None)
                if callable(close):
                    close()
        return choices, " ".join(warnings)

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

    def discover_remote_catalog(self, config) -> list:
        snapshot = dict(config or {})
        provider = self._provider("remote", snapshot)
        try:
            models_by_key = {}
            for task in INFERENCE_TASKS:
                for descriptor in provider.list_models(task):
                    models_by_key[(descriptor.task, descriptor.id)] = descriptor
            return list(models_by_key.values())
        finally:
            provider.close()

    def request_remote_catalog(self, config) -> bool:
        if self.discovery_worker is not None and self.discovery_worker.isRunning():
            return False
        snapshot = dict(config or {})
        worker = _CatalogDiscoveryWorker(
            lambda c=snapshot: self.discover_remote_catalog(c)
        )
        worker.succeeded.connect(self.remoteCatalogDiscovered.emit)
        worker.failed.connect(self.remoteCatalogFailed.emit)
        worker.finished.connect(lambda ref=worker: self._cleanup_discovery_worker(ref))
        self.discovery_worker = worker
        worker.start()
        return True

    def test_connection(self, config=None) -> dict:
        provider = self._provider("remote", config)
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
        self._queues[request.backend].append(record)
        self._dispatch_next(request.backend)
        self._emit_queue_changed()
        return self._entry_for_record(record)

    def _dispatch_next(self, backend: str) -> None:
        if self._shutting_down or self._workers[backend] is not None:
            return
        queue = self._queues[backend]
        while queue and self._workers[backend] is None and not self._shutting_down:
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
            self._active_records[backend] = record
            try:
                provider = self._provider(backend, request.provider_config)
            except Exception as exc:
                self._active_records[backend] = None
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
                lambda message, current, total, b=backend, rid=request.request_id: self._on_worker_progress(
                    b, rid, message, current, total
                )
            )
            worker.succeeded.connect(
                lambda result, b=backend, rid=request.request_id: self._on_worker_succeeded(
                    b, rid, result
                )
            )
            worker.failed.connect(
                lambda message, code, retryable, details, b=backend, rid=request.request_id: self._on_worker_failed(
                    b, rid, message, code, retryable, details
                )
            )
            worker.finished.connect(
                lambda b=backend, ref=worker: self._cleanup_worker(b, ref)
            )
            self._workers[backend] = worker
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
        self._history.append(record)

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
        for backend in ("local", "remote"):
            active = self._active_records[backend]
            if active is not None and active.request.request_id == request_id:
                if active.state not in {"running", "cancelling"}:
                    return False
                active.state = "cancelling"
                active.message = "Cancelling inference"
                self._append_log(active, "cancelling", active.message)
                worker = self._workers[backend]
                if worker is not None:
                    worker.cancel()
                self._emit_queue_changed()
                return True
            queue = self._queues[backend]
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
        for backend in ("local", "remote"):
            for record in list(self._queues[backend]):
                if self.cancel_request(record.request.request_id):
                    cancelled += 1
            active = self._active_records[backend]
            if active is not None and self.cancel_request(active.request.request_id):
                cancelled += 1
        return cancelled

    def queue_snapshot(self) -> tuple[InferenceQueueEntry, ...]:
        entries = []
        for backend in ("local", "remote"):
            active = self._active_records[backend]
            if active is not None and active.state in {"running", "cancelling"}:
                entries.append(self._entry_for_record(active, queue_position=0))
            entries.extend(
                self._entry_for_record(record, queue_position=index)
                for index, record in enumerate(self._queues[backend], start=1)
            )
        entries.extend(
            self._entry_for_record(record, queue_position=-1)
            for record in reversed(self._history)
        )
        return tuple(entries)

    def _entry_for_record(self, record, queue_position=None):
        if queue_position is None:
            if record.state in {"running", "cancelling"}:
                queue_position = 0
            else:
                try:
                    queue_position = list(self._queues[record.request.backend]).index(record) + 1
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
        )

    def _emit_queue_changed(self):
        self.queueChanged.emit(self.queue_snapshot())

    def clear_queue_history(self) -> None:
        self._history.clear()
        self._emit_queue_changed()

    def has_running_inference(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in self._workers.values()
        )

    def shutdown(self, wait_ms: int = 3000) -> bool:
        self._shutting_down = True
        self.cancel_all()
        deadline = time.monotonic() + max(0, int(wait_ms)) / 1000.0
        if self.discovery_worker is not None and self.discovery_worker.isRunning():
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if not self.discovery_worker.wait(remaining):
                return False
        for worker in tuple(self._workers.values()):
            if worker is None or not worker.isRunning():
                continue
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            if not worker.wait(remaining):
                return False
        return True

    def _cleanup_discovery_worker(self, worker):
        if self.discovery_worker is worker:
            self.discovery_worker = None
        worker.deleteLater()

    def _cleanup_worker(self, backend, worker):
        if self._workers.get(backend) is worker:
            self._workers[backend] = None
            self._active_records[backend] = None
        worker.deleteLater()
        if not self._shutting_down:
            self._dispatch_next(backend)
        self._emit_queue_changed()
