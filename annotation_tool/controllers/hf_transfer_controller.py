import inspect
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from opensportslib.tools.hf_transfer import (
    HfTransferCancelled,
    download_dataset_split_from_hf,
    download_dataset_splits_from_hf,
    list_dataset_branches_on_hf,
    list_dataset_splits_on_hf,
    upload_dataset_as_parquet_to_hf,
    upload_dataset_inputs_from_json_to_hf,
)
try:
    from opensportslib.tools.hf_transfer import download_dataset_sample_inputs_from_hf
except ImportError:
    download_dataset_sample_inputs_from_hf = None
try:
    from opensportslib.tools.hf_transfer import (
        download_dataset_missing_inputs_from_hf,
        find_missing_dataset_inputs,
    )
except ImportError:
    download_dataset_missing_inputs_from_hf = None
    find_missing_dataset_inputs = None

from hf_model_import import HfModelImportCancelled, resolve_hf_local_model


def _supports_keyword(callable_object, keyword: str) -> bool:
    """Return whether a runtime dependency accepts an optional keyword."""
    try:
        parameters = inspect.signature(callable_object).parameters
    except (TypeError, ValueError):
        return False
    return keyword in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


class _HfDownloadWorker(QThread):
    progress = pyqtSignal(str)
    byteProgress = pyqtSignal(str, object, object)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._config = dict(config)

    def run(self) -> None:
        try:
            operation = self._config.get("operation")
            if operation == "missing_assets":
                if download_dataset_missing_inputs_from_hf is None:
                    raise RuntimeError(
                        "Downloading all missing Hugging Face inputs requires the "
                        "newer local OpenSportsLib checkout."
                    )
                missing_kwargs = {
                    "token": self._config.get("token"),
                    "progress_cb": self.progress.emit,
                    "is_cancelled": self.isInterruptionRequested,
                }
                if _supports_keyword(
                    download_dataset_missing_inputs_from_hf, "byte_progress_cb"
                ):
                    missing_kwargs["byte_progress_cb"] = self.byteProgress.emit
                result = download_dataset_missing_inputs_from_hf(
                    self._config.get("dataset_json_path", ""),
                    **missing_kwargs,
                )
                result["project_generation"] = int(
                    self._config.get("project_generation", -1)
                )
                self.completed.emit(result)
                return
            if operation == "assets":
                if download_dataset_sample_inputs_from_hf is None:
                    raise RuntimeError(
                        "Selective Hugging Face downloads require the newer local "
                        "OpenSportsLib checkout."
                    )
                selective_kwargs = {
                    "input_path": self._config.get("input_path") or None,
                    "overwrite": bool(self._config.get("overwrite", False)),
                    "token": self._config.get("token"),
                    "progress_cb": self.progress.emit,
                    "is_cancelled": self.isInterruptionRequested,
                }
                if _supports_keyword(
                    download_dataset_sample_inputs_from_hf, "byte_progress_cb"
                ):
                    selective_kwargs["byte_progress_cb"] = self.byteProgress.emit
                result = download_dataset_sample_inputs_from_hf(
                    self._config.get("dataset_json_path", ""),
                    self._config.get("sample_id", ""),
                    **selective_kwargs,
                )
                result["project_generation"] = int(
                    self._config.get("project_generation", -1)
                )
                self.completed.emit(result)
                return
            download_kwargs = {
                "download_format": str(
                    self._config.get("download_format", "parquet") or "parquet"
                ),
                "dry_run": bool(self._config.get("dry_run", False)),
                "token": self._config.get("token"),
                "progress_cb": self.progress.emit,
                "is_cancelled": self.isInterruptionRequested,
            }
            if download_dataset_sample_inputs_from_hf is not None:
                download_kwargs["annotations_only"] = bool(
                    self._config.get("annotations_only", False)
                )
            elif self._config.get("annotations_only", False):
                raise RuntimeError(
                    "JSON-only Hugging Face downloads require the newer local "
                    "OpenSportsLib checkout."
                )
            if _supports_keyword(
                download_dataset_splits_from_hf, "byte_progress_cb"
            ):
                download_kwargs["byte_progress_cb"] = self.byteProgress.emit
            results = download_dataset_splits_from_hf(
                self._config.get("repo_id", ""),
                self._config.get("revision", "main"),
                list(self._config.get("splits", []) or []),
                self._config.get("output_dir", ""),
                **download_kwargs,
            )
            self.completed.emit(
                {
                    "results": results,
                    "dry_run": bool(self._config.get("dry_run", False)),
                    "output_dir": self._config.get("output_dir", ""),
                }
            )
        except HfTransferCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class _HfListBranchesWorker(QThread):
    succeeded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, repo_id: str, token: str | None = None) -> None:
        super().__init__()
        self._repo_id = repo_id
        self._token = token

    def run(self) -> None:
        try:
            branches = list_dataset_branches_on_hf(self._repo_id, token=self._token)
            self.succeeded.emit(branches)
        except Exception as exc:
            self.failed.emit(str(exc))


class _HfListSplitsWorker(QThread):
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, repo_id: str, revision: str, token: str | None = None) -> None:
        super().__init__()
        self._repo_id = repo_id
        self._revision = revision
        self._token = token

    def run(self) -> None:
        try:
            result = list_dataset_splits_on_hf(self._repo_id, self._revision, token=self._token)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class _HfUploadWorker(QThread):
    progress = pyqtSignal(str)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._config = dict(config)

    def run(self) -> None:
        try:
            if self._config.get("upload_as_json", True):
                result = upload_dataset_inputs_from_json_to_hf(
                    repo_id=self._config.get("repo_id", ""),
                    json_path=self._config.get("json_path", ""),
                    revision=self._config.get("revision", "main"),
                    split=self._config.get("split"),
                    commit_message=self._config.get("commit_message"),
                    token=self._config.get("token"),
                    progress_cb=self.progress.emit,
                    is_cancelled=self.isInterruptionRequested,
                )
            else:
                result = upload_dataset_as_parquet_to_hf(
                    repo_id=self._config.get("repo_id", ""),
                    json_path=self._config.get("json_path", ""),
                    revision=self._config.get("revision", "main"),
                    split=self._config.get("split"),
                    commit_message=self._config.get("commit_message"),
                    shard_mode=str(self._config.get("shard_mode", "size") or "size"),
                    shard_size=int(self._config.get("shard_size", 1_000_000_000) or 1_000_000_000),
                    token=self._config.get("token"),
                    progress_cb=self.progress.emit,
                    is_cancelled=self.isInterruptionRequested,
                )
            self.completed.emit(result)
        except HfTransferCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class _HfModelWorker(QThread):
    progress = pyqtSignal(str, int, int)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._config = dict(config)

    def run(self) -> None:
        try:
            result = resolve_hf_local_model(
                self._config,
                progress_cb=self.progress.emit,
                is_cancelled=self.isInterruptionRequested,
            )
            if self.isInterruptionRequested():
                raise HfModelImportCancelled("Model download cancelled.")
            self.completed.emit(result)
        except HfModelImportCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class HfTransferController(QObject):
    downloadStarted = pyqtSignal(str)
    downloadProgress = pyqtSignal(str)
    downloadBytesProgress = pyqtSignal(str, object, object)
    downloadCompleted = pyqtSignal(dict)
    downloadFailed = pyqtSignal(str)
    downloadCancelled = pyqtSignal(str)

    uploadStarted = pyqtSignal(str)
    uploadProgress = pyqtSignal(str)
    uploadCompleted = pyqtSignal(dict)
    uploadFailed = pyqtSignal(str)
    uploadCancelled = pyqtSignal(str)

    modelImportStarted = pyqtSignal(str)
    modelImportProgress = pyqtSignal(str, int, int)
    modelImportCompleted = pyqtSignal(dict)
    modelImportFailed = pyqtSignal(str)
    modelImportCancelled = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._download_worker: _HfDownloadWorker | None = None
        self._upload_worker: _HfUploadWorker | None = None
        self._model_worker: _HfModelWorker | None = None

    @staticmethod
    def supports_selective_downloads() -> bool:
        return download_dataset_sample_inputs_from_hf is not None

    @staticmethod
    def supports_safe_parquet_uploads() -> bool:
        return bool(
            find_missing_dataset_inputs is not None
            and download_dataset_missing_inputs_from_hf is not None
        )

    @staticmethod
    def find_missing_inputs(dataset_json_path: str) -> list[dict[str, str]]:
        if find_missing_dataset_inputs is None:
            raise RuntimeError(
                "Safe Parquet upload preflight requires the newer local "
                "OpenSportsLib checkout."
            )
        return list(find_missing_dataset_inputs(dataset_json_path))

    def is_download_running(self) -> bool:
        return bool(self._download_worker and self._download_worker.isRunning())

    def start_download(self, config: dict[str, Any]) -> bool:
        if self.is_download_running():
            self.downloadFailed.emit("A Hugging Face download is already running.")
            return False

        worker = _HfDownloadWorker(config)
        self._download_worker = worker
        worker.progress.connect(self.downloadProgress)
        worker.byteProgress.connect(self.downloadBytesProgress)
        worker.completed.connect(self.downloadCompleted)
        worker.failed.connect(self.downloadFailed)
        worker.cancelled.connect(self.downloadCancelled)
        worker.finished.connect(lambda: self._cleanup_download_worker(worker))

        self.downloadStarted.emit("Starting Hugging Face download...")
        worker.start()
        return True

    def start_asset_download(self, config: dict[str, Any]) -> bool:
        payload = dict(config or {})
        payload["operation"] = "assets"
        return self.start_download(payload)

    def start_missing_inputs_download(self, config: dict[str, Any]) -> bool:
        payload = dict(config or {})
        payload["operation"] = "missing_assets"
        return self.start_download(payload)

    def start_upload(self, config: dict[str, Any]) -> bool:
        if self._upload_worker and self._upload_worker.isRunning():
            self.uploadFailed.emit("A Hugging Face upload is already running.")
            return False

        worker = _HfUploadWorker(config)
        self._upload_worker = worker
        worker.progress.connect(self.uploadProgress)
        worker.completed.connect(self.uploadCompleted)
        worker.failed.connect(self.uploadFailed)
        worker.cancelled.connect(self.uploadCancelled)
        worker.finished.connect(lambda: self._cleanup_upload_worker(worker))

        self.uploadStarted.emit("Starting Hugging Face upload...")
        worker.start()
        return True

    def start_model_import(self, config: dict[str, Any]) -> bool:
        if self._model_worker and self._model_worker.isRunning():
            self.modelImportFailed.emit("A Hugging Face model download is already running.")
            return False

        worker = _HfModelWorker(config)
        self._model_worker = worker
        worker.progress.connect(self.modelImportProgress)
        worker.completed.connect(self.modelImportCompleted)
        worker.failed.connect(self.modelImportFailed)
        worker.cancelled.connect(self.modelImportCancelled)
        worker.finished.connect(lambda: self._cleanup_model_worker(worker))

        self.modelImportStarted.emit("Inspecting Hugging Face model repository…")
        worker.start()
        return True

    def cancel_download(self) -> bool:
        if not self._download_worker or not self._download_worker.isRunning():
            return False
        self.downloadProgress.emit("Cancellation requested for Hugging Face download...")
        self._download_worker.requestInterruption()
        return True

    def cancel_upload(self) -> bool:
        if not self._upload_worker or not self._upload_worker.isRunning():
            return False
        self.uploadProgress.emit("Cancellation requested for Hugging Face upload...")
        self._upload_worker.requestInterruption()
        return True

    def cancel_model_import(self) -> bool:
        if not self._model_worker or not self._model_worker.isRunning():
            return False
        self.modelImportProgress.emit(
            "Cancellation requested for model download…", 0, 0
        )
        self._model_worker.requestInterruption()
        return True

    def shutdown(self, wait_ms: int = 3000) -> bool:
        workers = [
            worker
            for worker in (
                self._download_worker,
                self._upload_worker,
                self._model_worker,
            )
            if worker is not None and worker.isRunning()
        ]
        for worker in workers:
            worker.requestInterruption()
        for worker in workers:
            if not worker.wait(max(0, int(wait_ms))):
                return False
        return True

    def _cleanup_download_worker(self, worker: _HfDownloadWorker) -> None:
        if self._download_worker is worker:
            self._download_worker = None
        worker.deleteLater()

    def _cleanup_upload_worker(self, worker: _HfUploadWorker) -> None:
        if self._upload_worker is worker:
            self._upload_worker = None
        worker.deleteLater()

    def _cleanup_model_worker(self, worker: _HfModelWorker) -> None:
        if self._model_worker is worker:
            self._model_worker = None
        worker.deleteLater()
