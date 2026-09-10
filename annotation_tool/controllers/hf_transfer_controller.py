import inspect
import os
from collections import deque
from time import monotonic
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
from hf_xet_settings import temporary_hf_xet_disabled


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
    filePlan = pyqtSignal(object)
    fileCompleted = pyqtSignal(str, str)
    jsonReady = pyqtSignal(str, str)
    completed = pyqtSignal(dict)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._config = dict(config)

    def run(self) -> None:
        with temporary_hf_xet_disabled(
            not bool(self._config.get("use_xet", True))
        ):
            self._run_transfer()

    def _run_transfer(self) -> None:
        try:
            report_bytes = self._config.get("progress_mode", "bytes") == "bytes"
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
                if report_bytes and _supports_keyword(
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
                if report_bytes and _supports_keyword(
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
            if report_bytes and _supports_keyword(
                download_dataset_splits_from_hf, "byte_progress_cb"
            ):
                download_kwargs["byte_progress_cb"] = self.byteProgress.emit
            if _supports_keyword(
                download_dataset_splits_from_hf, "file_plan_cb"
            ):
                download_kwargs["file_plan_cb"] = self.filePlan.emit
            if _supports_keyword(
                download_dataset_splits_from_hf, "file_completed_cb"
            ):
                download_kwargs["file_completed_cb"] = self.fileCompleted.emit
            if _supports_keyword(
                download_dataset_splits_from_hf, "json_ready_cb"
            ):
                download_kwargs["json_ready_cb"] = self.jsonReady.emit
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
        with temporary_hf_xet_disabled(
            not bool(self._config.get("use_xet", True))
        ):
            self._run_transfer()

    def _run_transfer(self) -> None:
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
    downloadStarted = pyqtSignal(str, dict)
    downloadQueued = pyqtSignal(dict, int)
    downloadProgress = pyqtSignal(str)
    downloadBytesProgress = pyqtSignal(str, object, object)
    downloadFilePlan = pyqtSignal(object)
    downloadFileCompleted = pyqtSignal(str, str)
    downloadJsonReady = pyqtSignal(str, str)
    downloadCompleted = pyqtSignal(dict)
    downloadFailed = pyqtSignal(str)
    downloadCancelled = pyqtSignal(str)
    downloadQueueChanged = pyqtSignal(object)

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
        self._active_download_config: dict[str, Any] | None = None
        self._queued_asset_downloads: deque[dict[str, Any]] = deque()
        self._download_queue_paused = False
        self._download_entries: list[dict[str, Any]] = []
        self._next_download_entry_id = 1
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

    def queued_download_count(self) -> int:
        return len(self._queued_asset_downloads)

    def is_download_queue_paused(self) -> bool:
        return self._download_queue_paused

    def queued_requested_local_paths(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                str(path)
                for payload in self._queued_asset_downloads
                for path in (payload.get("requested_local_paths", ()) or ())
                if path
            )
        )

    def download_queue_snapshot(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self._download_entries]

    def _emit_download_queue(self) -> None:
        self.downloadQueueChanged.emit(self.download_queue_snapshot())

    def _ensure_config_entries(self, payload: dict[str, Any]) -> list[int]:
        existing_ids = [int(value) for value in payload.get("_queue_entry_ids", ())]
        if existing_ids:
            return existing_ids
        display_paths = list(payload.get("requested_paths", ()) or ())
        local_paths = list(payload.get("requested_local_paths", ()) or ())
        if not display_paths:
            display_paths = list(local_paths)
        entry_ids = []
        for index, display_path in enumerate(display_paths):
            path = str(display_path or "").strip()
            if not path:
                continue
            local_path = str(local_paths[index] if index < len(local_paths) else "")
            completed = bool(
                local_path
                and os.path.isfile(local_path)
                and not bool(payload.get("overwrite", False))
            )
            entry_id = self._next_download_entry_id
            self._next_download_entry_id += 1
            self._download_entries.append(
                {
                    "id": entry_id,
                    "path": path,
                    "local_path": local_path,
                    "status": "completed" if completed else "queued",
                    "downloaded_bytes": 0,
                    "total_bytes": 0,
                    "average_speed": 0.0,
                    "_start_time": None,
                    "_start_bytes": 0,
                }
            )
            entry_ids.append(entry_id)
        payload["_queue_entry_ids"] = entry_ids
        if entry_ids:
            self._emit_download_queue()
        return entry_ids

    def _entries_for_ids(self, entry_ids: list[int]) -> list[dict[str, Any]]:
        wanted = set(entry_ids)
        return [entry for entry in self._download_entries if entry["id"] in wanted]

    def _mark_config_active(self, payload: dict[str, Any]) -> None:
        for entry in self._entries_for_ids(self._ensure_config_entries(payload)):
            if entry["status"] == "completed":
                continue
            entry["status"] = "active"
            entry["_start_time"] = None
            entry["_start_bytes"] = int(entry["downloaded_bytes"])
        self._emit_download_queue()

    def _matching_active_entry(self, filename: str) -> dict[str, Any] | None:
        normalized = str(filename or "").replace("\\", "/")
        active_ids = set(
            int(value)
            for value in (self._active_download_config or {}).get(
                "_queue_entry_ids", ()
            )
        )
        for entry in self._download_entries:
            if entry["id"] not in active_ids:
                continue
            planned = str(entry["path"]).replace("\\", "/")
            if normalized == planned or normalized.endswith(f"/{planned}"):
                return entry
        return None

    def _add_active_file_entry(self, filename: str) -> dict[str, Any]:
        payload = self._active_download_config or {}
        entry_id = self._next_download_entry_id
        self._next_download_entry_id += 1
        entry = {
            "id": entry_id,
            "path": str(filename),
            "local_path": "",
            "status": "active",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "average_speed": 0.0,
            "_start_time": None,
            "_start_bytes": 0,
        }
        self._download_entries.append(entry)
        payload.setdefault("_queue_entry_ids", []).append(entry_id)
        return entry

    def clear_queued_downloads(self) -> int:
        """Discard completed/waiting entries without interrupting active work."""
        cleared = len(self._queued_asset_downloads)
        self._queued_asset_downloads.clear()
        self._download_entries = [
            entry for entry in self._download_entries if entry["status"] == "active"
        ]
        if not self.is_download_running():
            self._download_queue_paused = False
        self._emit_download_queue()
        return cleared

    def start_download(self, config: dict[str, Any]) -> bool:
        if self.is_download_running():
            self.downloadFailed.emit("A Hugging Face download is already running.")
            return False

        return self._start_download_now(config)

    def _start_download_now(self, config: dict[str, Any]) -> bool:
        payload = dict(config or {})
        self._ensure_config_entries(payload)
        self._mark_config_active(payload)

        worker = _HfDownloadWorker(payload)
        self._download_worker = worker
        self._active_download_config = payload
        worker.progress.connect(self.downloadProgress)
        worker.byteProgress.connect(self._on_worker_byte_progress)
        worker.filePlan.connect(self._on_worker_file_plan)
        worker.fileCompleted.connect(self._on_worker_file_completed)
        worker.jsonReady.connect(self.downloadJsonReady)
        worker.completed.connect(self._on_worker_download_completed)
        worker.failed.connect(self._on_worker_download_failed)
        worker.cancelled.connect(self._on_worker_download_cancelled)
        worker.finished.connect(lambda: self._cleanup_download_worker(worker))

        self.downloadStarted.emit("Starting Hugging Face download...", dict(payload))
        worker.start()
        return True

    def start_asset_download(self, config: dict[str, Any]) -> bool:
        payload = dict(config or {})
        payload["operation"] = "assets"
        self._ensure_config_entries(payload)
        if self._download_queue_paused and not self.is_download_running():
            self._download_queue_paused = False
            if self._queued_asset_downloads:
                self._queued_asset_downloads.append(payload)
                self.downloadQueued.emit(
                    dict(payload), len(self._queued_asset_downloads)
                )
                return self._start_download_now(
                    self._queued_asset_downloads.popleft()
                )
            return self._start_download_now(payload)
        if self._download_queue_paused:
            self._queued_asset_downloads.append(payload)
            self.downloadQueued.emit(dict(payload), len(self._queued_asset_downloads))
            return True
        if self.is_download_running():
            active_operation = str(
                (self._active_download_config or {}).get("operation") or "dataset"
            )
            if active_operation != "assets":
                return False
            self._queued_asset_downloads.append(payload)
            self.downloadQueued.emit(dict(payload), len(self._queued_asset_downloads))
            return True
        return self._start_download_now(payload)

    def queue_download(self, config: dict[str, Any]) -> bool:
        payload = dict(config or {})
        self._ensure_config_entries(payload)
        if self._download_queue_paused and not self.is_download_running():
            self._download_queue_paused = False
            if self._queued_asset_downloads:
                self._queued_asset_downloads.append(payload)
                self.downloadQueued.emit(
                    dict(payload), len(self._queued_asset_downloads)
                )
                return self._start_download_now(
                    self._queued_asset_downloads.popleft()
                )
            return self._start_download_now(payload)
        if self.is_download_running() or self._download_queue_paused:
            self._queued_asset_downloads.append(payload)
            self.downloadQueued.emit(dict(payload), len(self._queued_asset_downloads))
            return True
        return self._start_download_now(payload)

    def start_missing_inputs_download(self, config: dict[str, Any]) -> bool:
        payload = dict(config or {})
        payload["operation"] = "missing_assets"
        return self.start_download(payload)

    def queue_missing_inputs_download(self, config: dict[str, Any]) -> bool:
        payload = dict(config or {})
        payload["operation"] = "missing_assets"
        return self.queue_download(payload)

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
        self._queued_asset_downloads.clear()
        self._download_queue_paused = False
        self.downloadProgress.emit("Cancellation requested for Hugging Face download...")
        self._download_worker.requestInterruption()
        return True

    def pause_download_queue(self) -> bool:
        if not self._download_worker or not self._download_worker.isRunning():
            return False
        if self._active_download_config:
            self._queued_asset_downloads.appendleft(
                dict(self._active_download_config)
            )
            for entry in self._entries_for_ids(
                list(self._active_download_config.get("_queue_entry_ids", ()))
            ):
                if entry["status"] == "active":
                    entry["status"] = "queued"
            self._emit_download_queue()
        self._download_queue_paused = True
        self.downloadProgress.emit("Stopping after the current safe point...")
        self._download_worker.requestInterruption()
        return True

    def resume_download_queue(self) -> bool:
        if not self._download_queue_paused:
            return False
        self._download_queue_paused = False
        if self.is_download_running():
            return True
        if not self._queued_asset_downloads:
            return False
        return self._start_download_now(self._queued_asset_downloads.popleft())

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
        self._queued_asset_downloads.clear()
        self._download_queue_paused = False
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
            self._active_download_config = None
        worker.deleteLater()
        if (
            self._download_worker is None
            and self._queued_asset_downloads
            and not self._download_queue_paused
        ):
            self._start_download_now(self._queued_asset_downloads.popleft())

    def _on_worker_file_plan(self, filenames: object) -> None:
        planned = [str(filename) for filename in list(filenames or [])]
        payload = self._active_download_config or {}
        if payload.get("json_first"):
            splits = [
                str(split).strip().removesuffix(".json")
                for split in payload.get("splits", ()) or ()
                if str(split).strip()
            ]
            if str(payload.get("download_format") or "").lower() == "json":
                allowed = {f"{split}.json" for split in splits}
            else:
                allowed = {f"{split}/metadata.parquet" for split in splits}
            planned = [
                filename
                for filename in planned
                if filename.replace("\\", "/") in allowed
            ]
        for filename in planned:
            if self._matching_active_entry(filename) is None:
                self._add_active_file_entry(filename)
        if planned:
            self._emit_download_queue()
        self.downloadFilePlan.emit(planned)

    def _on_worker_byte_progress(
        self, filename: str, downloaded_bytes: object, total_bytes: object
    ) -> None:
        entry = self._matching_active_entry(filename)
        if entry is None:
            entry = self._add_active_file_entry(filename)
        downloaded = max(0, int(downloaded_bytes or 0))
        total = max(0, int(total_bytes or 0))
        now = monotonic()
        if entry["_start_time"] is None:
            entry["_start_time"] = now
            entry["_start_bytes"] = downloaded
        elapsed = now - float(entry["_start_time"])
        transferred = max(0, downloaded - int(entry["_start_bytes"]))
        if elapsed > 0 and transferred > 0:
            entry["average_speed"] = transferred / elapsed
        entry["downloaded_bytes"] = downloaded
        entry["total_bytes"] = total
        entry["status"] = "completed" if total and downloaded >= total else "active"
        self._emit_download_queue()
        self.downloadBytesProgress.emit(filename, downloaded, total)

    def _on_worker_file_completed(self, filename: str, local_path: str) -> None:
        entry = self._matching_active_entry(filename)
        if entry is None:
            entry = self._add_active_file_entry(filename)
        entry["status"] = "completed"
        entry["local_path"] = str(local_path or entry["local_path"])
        self._emit_download_queue()
        self.downloadFileCompleted.emit(filename, local_path)

    def _on_worker_download_completed(self, payload: dict) -> None:
        completed_paths = set()
        results = [payload]
        results.extend(payload.get("results", ()) or ())
        results.extend(payload.get("sample_results", ()) or ())
        for result in results:
            for key in (
                "requested_downloaded_paths",
                "requested_overwritten_paths",
                "requested_skipped_paths",
                "opportunistic_downloaded_paths",
            ):
                completed_paths.update(str(path) for path in result.get(key, ()) or ())
        active_ids = set(
            int(value)
            for value in (self._active_download_config or {}).get(
                "_queue_entry_ids", ()
            )
        )
        normalized_completed = {
            str(path).replace("\\", "/") for path in completed_paths
        }
        for entry in self._download_entries:
            if entry["id"] not in active_ids:
                continue
            normalized = str(entry["path"]).replace("\\", "/")
            local_exists = bool(
                entry["local_path"] and os.path.isfile(entry["local_path"])
            )
            reported_complete = any(
                normalized == path
                or path.endswith(f"/{normalized}")
                or normalized.endswith(f"/{path}")
                for path in normalized_completed
            )
            if reported_complete or local_exists:
                entry["status"] = "completed"
            elif entry["status"] == "active":
                entry["status"] = "failed"
        self._emit_download_queue()
        self.downloadCompleted.emit(payload)

    def _on_worker_download_failed(self, error: str) -> None:
        active_ids = list(
            (self._active_download_config or {}).get("_queue_entry_ids", ())
        )
        for entry in self._entries_for_ids(active_ids):
            if entry["status"] == "active":
                entry["status"] = "failed"
        self._emit_download_queue()
        self.downloadFailed.emit(error)

    def _on_worker_download_cancelled(self, message: str) -> None:
        if not self._download_queue_paused:
            active_ids = list(
                (self._active_download_config or {}).get("_queue_entry_ids", ())
            )
            for entry in self._entries_for_ids(active_ids):
                if entry["status"] == "active":
                    entry["status"] = "queued"
            self._emit_download_queue()
        self.downloadCancelled.emit(message)

    def _cleanup_upload_worker(self, worker: _HfUploadWorker) -> None:
        if self._upload_worker is worker:
            self._upload_worker = None
        worker.deleteLater()

    def _cleanup_model_worker(self, worker: _HfModelWorker) -> None:
        if self._model_worker is worker:
            self._model_worker = None
        worker.deleteLater()
