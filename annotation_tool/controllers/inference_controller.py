"""Canonical inference execution owner for all annotation modes."""

from __future__ import annotations

import os
import threading

from PyQt6.QtCore import QObject, QSettings, QThread, pyqtSignal

from inference_providers import LocalInferenceProvider, RemoteInferenceProvider
from inference_settings import BACKEND_KEY, DEFAULT_BACKEND, DEFAULT_SERVER_URL, SERVER_URL_KEY, normalize_server_url
from inference_types import InferenceError, InferenceRequest


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


class InferenceController(QObject):
    modelsDiscovered = pyqtSignal(str, str, object)
    discoveryFailed = pyqtSignal(str, str, str)
    inferenceStarted = pyqtSignal(str, str)
    inferenceProgress = pyqtSignal(str, str, int, int)
    inferenceCompleted = pyqtSignal(str, object)
    inferenceFailed = pyqtSignal(str, str, str, bool, object)
    inferenceCancelled = pyqtSignal(str)

    SETTINGS_ORG = "OpenSportsLab"
    SETTINGS_APP = "VideoAnnotationTool"

    def __init__(self, settings=None, base_dir: str = "", parent=None):
        super().__init__(parent)
        self.settings = settings or QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)
        self.base_dir = base_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.worker: _InferenceWorker | None = None
        self.discovery_worker: _ModelDiscoveryWorker | None = None
        self._active_request_id = ""

    def default_backend(self) -> str:
        backend = str(self.settings.value(BACKEND_KEY, DEFAULT_BACKEND) or DEFAULT_BACKEND)
        return backend if backend in {"local", "remote"} else DEFAULT_BACKEND

    def configuration_snapshot(self) -> dict:
        from inference_settings import load_local_models, load_shared_mappings
        return {
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
        selected_backend = backend or self.default_backend()
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
        selected_backend = backend or self.default_backend()
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

    def test_connection(self, config=None) -> dict:
        provider = self._provider("remote", config)
        try:
            return provider.discover_capabilities()
        finally:
            provider.close()

    def start_inference(self, request: InferenceRequest) -> bool:
        if self.worker is not None and self.worker.isRunning():
            return False
        provider = self._provider(request.backend, request.provider_config)
        worker = _InferenceWorker(provider, request)
        worker.progress.connect(
            lambda message, current, total, rid=request.request_id: self.inferenceProgress.emit(
                rid, message, current, total
            )
        )
        worker.succeeded.connect(
            lambda result, rid=request.request_id: self.inferenceCompleted.emit(rid, result)
        )
        worker.failed.connect(
            lambda message, code, retryable, details, rid=request.request_id: self._on_failed(
                rid, message, code, retryable, details
            )
        )
        worker.finished.connect(lambda ref=worker: self._cleanup_worker(ref))
        self.worker = worker
        self._active_request_id = request.request_id
        self.inferenceStarted.emit(request.request_id, request.task)
        worker.start()
        return True

    def _on_failed(self, request_id, message, code, retryable, details):
        if code == "cancelled":
            self.inferenceCancelled.emit(request_id)
            return
        self.inferenceFailed.emit(request_id, message, code, retryable, details)

    def cancel_inference(self) -> bool:
        if self.worker is None or not self.worker.isRunning():
            return False
        self.worker.cancel()
        return True

    def has_running_inference(self) -> bool:
        return bool(self.worker is not None and self.worker.isRunning())

    def shutdown(self, wait_ms: int = 3000) -> bool:
        if self.discovery_worker is not None and self.discovery_worker.isRunning():
            if not self.discovery_worker.wait(wait_ms):
                return False
        if self.worker is None:
            return True
        if self.worker.isRunning():
            self.worker.cancel()
            if not self.worker.wait(wait_ms):
                return False
        return True

    def _cleanup_discovery_worker(self, worker):
        if self.discovery_worker is worker:
            self.discovery_worker = None
        worker.deleteLater()

    def _cleanup_worker(self, worker):
        if self.worker is worker:
            self.worker = None
            self._active_request_id = ""
        worker.deleteLater()
