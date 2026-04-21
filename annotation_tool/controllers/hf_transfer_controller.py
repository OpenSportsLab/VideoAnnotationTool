from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from controllers.hf_transfer_service import (
    HfTransferCancelled,
    download_dataset_from_hf,
    upload_dataset_as_parquet_to_hf,
    upload_dataset_inputs_from_json_to_hf,
)


class _HfDownloadWorker(QThread):
    progress = pyqtSignal(str)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._config = dict(config)

    def run(self) -> None:
        try:
            result = download_dataset_from_hf(
                self._config.get("url", ""),
                self._config.get("output_dir", ""),
                dry_run=bool(self._config.get("dry_run", False)),
                types_arg=str(self._config.get("types", "video")),
                token=self._config.get("token"),
                progress_cb=self.progress.emit,
                is_cancelled=self.isInterruptionRequested,
            )
            self.completed.emit(result)
        except HfTransferCancelled as exc:
            self.cancelled.emit(str(exc))
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
                    commit_message=self._config.get("commit_message"),
                    samples_per_shard=int(self._config.get("samples_per_shard", 100) or 100),
                    token=self._config.get("token"),
                    progress_cb=self.progress.emit,
                    is_cancelled=self.isInterruptionRequested,
                )
            self.completed.emit(result)
        except HfTransferCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))


class HfTransferController(QObject):
    downloadStarted = pyqtSignal(str)
    downloadProgress = pyqtSignal(str)
    downloadCompleted = pyqtSignal(dict)
    downloadFailed = pyqtSignal(str)
    downloadCancelled = pyqtSignal(str)

    uploadStarted = pyqtSignal(str)
    uploadProgress = pyqtSignal(str)
    uploadCompleted = pyqtSignal(dict)
    uploadFailed = pyqtSignal(str)
    uploadCancelled = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._download_worker: _HfDownloadWorker | None = None
        self._upload_worker: _HfUploadWorker | None = None

    def start_download(self, config: dict[str, Any]) -> bool:
        if self._download_worker and self._download_worker.isRunning():
            self.downloadFailed.emit("A Hugging Face download is already running.")
            return False

        worker = _HfDownloadWorker(config)
        self._download_worker = worker
        worker.progress.connect(self.downloadProgress)
        worker.completed.connect(self.downloadCompleted)
        worker.failed.connect(self.downloadFailed)
        worker.cancelled.connect(self.downloadCancelled)
        worker.finished.connect(lambda: self._cleanup_download_worker(worker))

        self.downloadStarted.emit("Starting Hugging Face download...")
        worker.start()
        return True

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

    def _cleanup_download_worker(self, worker: _HfDownloadWorker) -> None:
        if self._download_worker is worker:
            self._download_worker = None
        worker.deleteLater()

    def _cleanup_upload_worker(self, worker: _HfUploadWorker) -> None:
        if self._upload_worker is worker:
            self._upload_worker = None
        worker.deleteLater()
