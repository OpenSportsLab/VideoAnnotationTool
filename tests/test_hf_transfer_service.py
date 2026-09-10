import os

import pytest

import opensportslib.tools.hf_transfer as hf_transfer
from controllers import hf_transfer_controller
from controllers.hf_transfer_controller import (
    HfTransferController,
    _HfDownloadWorker,
    _HfModelWorker,
    _HfUploadWorker,
)
from hf_model_import import HfModelImportCancelled


def test_controller_module_uses_opensportslib_transfer_functions():
    assert hf_transfer_controller.HfTransferCancelled is hf_transfer.HfTransferCancelled
    assert hf_transfer_controller.download_dataset_splits_from_hf is hf_transfer.download_dataset_splits_from_hf
    assert hf_transfer_controller.find_missing_dataset_inputs is hf_transfer.find_missing_dataset_inputs
    assert (
        hf_transfer_controller.download_dataset_missing_inputs_from_hf
        is hf_transfer.download_dataset_missing_inputs_from_hf
    )
    assert hf_transfer_controller.list_dataset_branches_on_hf is hf_transfer.list_dataset_branches_on_hf
    assert hf_transfer_controller.list_dataset_splits_on_hf is hf_transfer.list_dataset_splits_on_hf
    assert hf_transfer_controller.upload_dataset_inputs_from_json_to_hf is hf_transfer.upload_dataset_inputs_from_json_to_hf
    assert hf_transfer_controller.upload_dataset_as_parquet_to_hf is hf_transfer.upload_dataset_as_parquet_to_hf


def test_download_running_reports_shared_full_and_selective_worker_slot():
    controller = HfTransferController()
    assert controller.is_download_running() is False

    controller._download_worker = type(
        "_Worker", (), {"isRunning": lambda self: True}
    )()

    assert controller.is_download_running() is True


def test_selective_downloads_queue_behind_active_selective_download():
    controller = HfTransferController()
    worker = type(
        "_Worker",
        (),
        {
            "isRunning": lambda self: True,
            "requestInterruption": lambda self: None,
        },
    )()
    controller._download_worker = worker
    controller._active_download_config = {"operation": "assets", "sample_id": "one"}
    queued = []
    controller.downloadQueued.connect(
        lambda payload, position: queued.append((payload, position))
    )

    assert controller.start_asset_download(
        {"sample_id": "two", "requested_local_paths": ["/data/two.mp4"]}
    ) is True
    assert controller.start_asset_download(
        {"sample_id": "three", "requested_local_paths": ["/data/three.mp4"]}
    ) is True

    assert controller.queued_download_count() == 2
    assert [entry[0]["sample_id"] for entry in queued] == ["two", "three"]
    assert [entry[1] for entry in queued] == [1, 2]
    assert controller.queued_requested_local_paths() == (
        "/data/two.mp4",
        "/data/three.mp4",
    )

    assert controller.cancel_download() is True
    assert controller.queued_download_count() == 0


def test_full_download_does_not_accept_selective_queue_item():
    controller = HfTransferController()
    controller._download_worker = type(
        "_Worker", (), {"isRunning": lambda self: True}
    )()
    controller._active_download_config = {"operation": "dataset"}

    assert controller.start_asset_download({"sample_id": "two"}) is False
    assert controller.queued_download_count() == 0


def test_next_selective_download_starts_after_worker_cleanup(monkeypatch):
    controller = HfTransferController()
    worker = type(
        "_Worker",
        (),
        {
            "isRunning": lambda self: True,
            "deleteLater": lambda self: None,
        },
    )()
    controller._download_worker = worker
    controller._active_download_config = {"operation": "assets", "sample_id": "one"}
    assert controller.start_asset_download({"sample_id": "two"}) is True
    started = []
    monkeypatch.setattr(
        controller,
        "_start_download_now",
        lambda payload: started.append(payload) or True,
    )

    controller._cleanup_download_worker(worker)

    assert [payload["sample_id"] for payload in started] == ["two"]
    assert controller.queued_download_count() == 0


def test_pause_preserves_active_and_queued_downloads_until_resume(monkeypatch):
    interruptions = []
    controller = HfTransferController()
    worker = type(
        "_Worker",
        (),
        {
            "isRunning": lambda self: True,
            "requestInterruption": lambda self: interruptions.append(True),
            "deleteLater": lambda self: None,
        },
    )()
    controller._download_worker = worker
    controller._active_download_config = {"operation": "assets", "sample_id": "one"}
    controller.queue_download({"operation": "assets", "sample_id": "two"})

    assert controller.pause_download_queue() is True
    assert controller.is_download_queue_paused() is True
    assert interruptions == [True]
    assert [item["sample_id"] for item in controller._queued_asset_downloads] == [
        "one",
        "two",
    ]

    controller._cleanup_download_worker(worker)
    started = []
    monkeypatch.setattr(
        controller,
        "_start_download_now",
        lambda payload: started.append(payload) or True,
    )

    assert controller.resume_download_queue() is True
    assert controller.is_download_queue_paused() is False
    assert [item["sample_id"] for item in started] == ["one"]
    assert [item["sample_id"] for item in controller._queued_asset_downloads] == ["two"]


def test_controller_owns_ordered_file_queue_and_stop_requeues_current():
    interruptions = []
    controller = HfTransferController()
    first = {
        "operation": "assets",
        "sample_id": "one",
        "requested_paths": ["clips/one.mp4"],
    }
    controller._ensure_config_entries(first)
    controller._active_download_config = first
    controller._mark_config_active(first)
    controller._download_worker = type(
        "_Worker",
        (),
        {
            "isRunning": lambda self: True,
            "requestInterruption": lambda self: interruptions.append(True),
        },
    )()

    assert controller.start_asset_download(
        {
            "sample_id": "two",
            "requested_paths": ["clips/two.mp4"],
        }
    ) is True
    assert controller.start_asset_download(
        {
            "sample_id": "three",
            "requested_paths": ["clips/three.mp4"],
        }
    ) is True
    assert [entry["path"] for entry in controller.download_queue_snapshot()] == [
        "clips/one.mp4",
        "clips/two.mp4",
        "clips/three.mp4",
    ]
    assert [entry["status"] for entry in controller.download_queue_snapshot()] == [
        "active",
        "queued",
        "queued",
    ]

    assert controller.pause_download_queue() is True
    assert interruptions == [True]
    assert [entry["status"] for entry in controller.download_queue_snapshot()] == [
        "queued",
        "queued",
        "queued",
    ]
    assert [job["sample_id"] for job in controller._queued_asset_downloads] == [
        "one",
        "two",
        "three",
    ]


def test_clear_removes_completed_and_queued_entries_but_keeps_active():
    controller = HfTransferController()
    controller._download_entries = [
        {"id": 1, "path": "done", "status": "completed"},
        {"id": 2, "path": "active", "status": "active"},
        {"id": 3, "path": "waiting", "status": "queued"},
        {"id": 4, "path": "failed", "status": "failed"},
    ]
    controller._queued_asset_downloads.append({"sample_id": "waiting"})
    controller._download_worker = type(
        "_Worker", (), {"isRunning": lambda self: True}
    )()

    assert controller.clear_queued_downloads() == 1
    snapshot = controller.download_queue_snapshot()
    assert len(snapshot) == 1
    assert snapshot[0]["id"] == 2
    assert snapshot[0]["path"] == "active"
    assert snapshot[0]["status"] == "active"


def test_only_first_file_in_each_queue_job_is_active():
    controller = HfTransferController()
    payload = {
        "operation": "assets",
        "requested_paths": ["clips/one.mp4", "clips/two.mp4"],
    }
    controller._ensure_config_entries(payload)
    controller._active_download_config = payload
    controller._mark_config_active(payload)

    assert [entry["status"] for entry in controller.download_queue_snapshot()] == [
        "active",
        "queued",
    ]

    controller._on_worker_byte_progress("clips/one.mp4", 10, 10)
    controller._on_worker_byte_progress("clips/two.mp4", 1, 10)

    assert [entry["status"] for entry in controller.download_queue_snapshot()] == [
        "completed",
        "active",
    ]


def test_clear_discards_waiting_jobs_and_next_sample_auto_starts(monkeypatch):
    controller = HfTransferController()
    controller._download_queue_paused = True
    controller._queued_asset_downloads.extend(
        [
            {"operation": "assets", "sample_id": "old-1"},
            {"operation": "assets", "sample_id": "old-2"},
        ]
    )

    assert controller.clear_queued_downloads() == 2
    assert controller.queued_download_count() == 0
    assert controller.is_download_queue_paused() is False

    started = []
    monkeypatch.setattr(
        controller,
        "_start_download_now",
        lambda payload: started.append(payload) or True,
    )

    assert controller.start_asset_download({"sample_id": "new"}) is True
    assert [payload["sample_id"] for payload in started] == ["new"]


def test_download_worker_routes_to_library_api(monkeypatch):
    calls = {}

    def _fake_download_dataset_splits_from_hf(repo_id, revision, splits, output_dir, **kwargs):
        calls["repo_id"] = repo_id
        calls["revision"] = revision
        calls["splits"] = splits
        calls["output_dir"] = output_dir
        calls.update(kwargs)
        return [{"ok": True}]

    monkeypatch.setattr(hf_transfer_controller, "download_dataset_splits_from_hf", _fake_download_dataset_splits_from_hf)

    worker = _HfDownloadWorker(
        {
            "repo_id": "OpenSportsLab/repo",
            "revision": "main",
            "splits": ["test"],
            "download_format": "json",
            "output_dir": "/tmp/output",
            "dry_run": True,
            "token": "hf_test",
        }
    )

    completed_payloads = []
    worker.completed.connect(lambda payload: completed_payloads.append(payload))
    worker.run()

    assert calls["repo_id"] == "OpenSportsLab/repo"
    assert calls["revision"] == "main"
    assert calls["splits"] == ["test"]
    assert calls["download_format"] == "json"
    assert calls["output_dir"] == "/tmp/output"
    assert calls["dry_run"] is True
    assert calls["token"] == "hf_test"
    assert callable(calls["progress_cb"])
    assert callable(calls["byte_progress_cb"])
    assert callable(calls["is_cancelled"])
    assert completed_payloads == [{"results": [{"ok": True}], "dry_run": True, "output_dir": "/tmp/output"}]


def test_download_worker_can_disable_xet_for_only_that_transfer(monkeypatch):
    from huggingface_hub import constants

    observed = []
    previous_environment = os.environ.get("HF_HUB_DISABLE_XET")
    previous_constant = constants.HF_HUB_DISABLE_XET

    def _fake_download(*args, **kwargs):
        del args, kwargs
        observed.append(
            (os.environ.get("HF_HUB_DISABLE_XET"), constants.HF_HUB_DISABLE_XET)
        )
        return []

    monkeypatch.setattr(
        hf_transfer_controller,
        "download_dataset_splits_from_hf",
        _fake_download,
    )

    _HfDownloadWorker(
        {
            "repo_id": "OpenSportsLab/repo",
            "revision": "main",
            "splits": ["test"],
            "output_dir": "/tmp/output",
            "use_xet": False,
        }
    ).run()

    assert observed == [("1", True)]
    assert os.environ.get("HF_HUB_DISABLE_XET") == previous_environment
    assert constants.HF_HUB_DISABLE_XET is previous_constant


def test_download_worker_explicitly_enables_xet_when_option_is_checked(
    monkeypatch,
):
    from huggingface_hub import constants

    observed = []
    monkeypatch.setenv("HF_HUB_DISABLE_XET", "1")
    monkeypatch.setattr(constants, "HF_HUB_DISABLE_XET", True)

    def _fake_download(*args, **kwargs):
        del args, kwargs
        observed.append(
            (os.environ.get("HF_HUB_DISABLE_XET"), constants.HF_HUB_DISABLE_XET)
        )
        return []

    monkeypatch.setattr(
        hf_transfer_controller,
        "download_dataset_splits_from_hf",
        _fake_download,
    )

    _HfDownloadWorker(
        {
            "repo_id": "OpenSportsLab/repo",
            "revision": "main",
            "splits": ["test"],
            "output_dir": "/tmp/output",
            "use_xet": True,
        }
    ).run()

    assert observed == [("0", False)]
    assert os.environ["HF_HUB_DISABLE_XET"] == "1"
    assert constants.HF_HUB_DISABLE_XET is True


def test_download_worker_routes_selective_asset_request(monkeypatch):
    calls = {}

    def _fake_selective(dataset_json_path, sample_id, **kwargs):
        calls["dataset_json_path"] = dataset_json_path
        calls["sample_id"] = sample_id
        calls.update(kwargs)
        return {"operation": "assets", "requested_downloaded_count": 1}

    monkeypatch.setattr(
        hf_transfer_controller,
        "download_dataset_sample_inputs_from_hf",
        _fake_selective,
    )
    worker = _HfDownloadWorker(
        {
            "operation": "assets",
            "dataset_json_path": "/tmp/test.json",
            "sample_id": "sample-1",
            "input_path": "clips/one.mp4",
            "overwrite": True,
            "token": "hf_test",
            "project_generation": 7,
            "use_xet": False,
            "progress_mode": "bytes",
        }
    )
    completed = []
    worker.completed.connect(completed.append)

    worker.run()

    assert calls["dataset_json_path"] == "/tmp/test.json"
    assert calls["sample_id"] == "sample-1"
    assert calls["input_path"] == "clips/one.mp4"
    assert calls["overwrite"] is True
    assert calls["token"] == "hf_test"
    assert callable(calls["progress_cb"])
    assert callable(calls["byte_progress_cb"])
    assert callable(calls["is_cancelled"])
    assert completed[0]["operation"] == "assets"
    assert completed[0]["project_generation"] == 7


def test_download_worker_routes_missing_input_hydration(monkeypatch):
    calls = {}

    def _fake_hydrate(dataset_json_path, **kwargs):
        calls["dataset_json_path"] = dataset_json_path
        calls.update(kwargs)
        return {"operation": "missing_assets", "remaining_missing_count": 0}

    monkeypatch.setattr(
        hf_transfer_controller,
        "download_dataset_missing_inputs_from_hf",
        _fake_hydrate,
    )
    worker = _HfDownloadWorker(
        {
            "operation": "missing_assets",
            "dataset_json_path": "/tmp/test.json",
            "token": "hf_test",
            "project_generation": 9,
            "use_xet": False,
            "progress_mode": "bytes",
        }
    )
    completed = []
    worker.completed.connect(completed.append)

    worker.run()

    assert calls["dataset_json_path"] == "/tmp/test.json"
    assert calls["token"] == "hf_test"
    assert callable(calls["progress_cb"])
    assert callable(calls["byte_progress_cb"])
    assert callable(calls["is_cancelled"])
    assert completed == [
        {
            "operation": "missing_assets",
            "remaining_missing_count": 0,
            "project_generation": 9,
        }
    ]


def test_download_worker_forwards_file_byte_progress(monkeypatch):
    def _fake_download(
        repo_id,
        revision,
        splits,
        output_dir,
        *,
        byte_progress_cb=None,
        **kwargs,
    ):
        del repo_id, revision, splits, output_dir
        kwargs["file_plan_cb"](["test.json", "test/shards/large.tar"])
        byte_progress_cb("test/shards/large.tar", 384 * 1024**2, 2 * 1024**3)
        kwargs["file_completed_cb"](
            "test/shards/large.tar", "/tmp/output/test/shards/large.tar"
        )
        kwargs["json_ready_cb"]("test", "/tmp/output/test.json")
        return [{"ok": True}]

    monkeypatch.setattr(
        hf_transfer_controller, "download_dataset_splits_from_hf", _fake_download
    )
    worker = _HfDownloadWorker(
        {
            "repo_id": "OpenSportsLab/repo",
            "revision": "main",
            "splits": ["test"],
            "output_dir": "/tmp/output",
            "use_xet": True,
            "progress_mode": "bytes",
        }
    )
    byte_updates = []
    plans = []
    completed_files = []
    ready_json = []
    worker.byteProgress.connect(
        lambda filename, downloaded, total: byte_updates.append(
            (filename, downloaded, total)
        )
    )
    worker.filePlan.connect(plans.append)
    worker.fileCompleted.connect(
        lambda filename, path: completed_files.append((filename, path))
    )
    worker.jsonReady.connect(
        lambda split, path: ready_json.append((split, path))
    )

    worker.run()

    assert byte_updates == [
        ("test/shards/large.tar", 384 * 1024**2, 2 * 1024**3)
    ]
    assert plans == [["test.json", "test/shards/large.tar"]]
    assert completed_files == [
        ("test/shards/large.tar", "/tmp/output/test/shards/large.tar")
    ]
    assert ready_json == [("test", "/tmp/output/test.json")]


def test_download_worker_does_not_pass_byte_callback_to_older_api(monkeypatch):
    calls = []

    def _legacy_download(
        repo_id,
        revision,
        splits,
        output_dir,
        *,
        download_format,
        dry_run,
        token,
        progress_cb,
        is_cancelled,
    ):
        del repo_id, revision, splits, output_dir, download_format, dry_run
        del token, progress_cb, is_cancelled
        calls.append(True)
        return [{"ok": True}]

    monkeypatch.setattr(
        hf_transfer_controller, "download_dataset_splits_from_hf", _legacy_download
    )

    _HfDownloadWorker(
        {
            "repo_id": "OpenSportsLab/repo",
            "revision": "main",
            "splits": ["test"],
            "output_dir": "/tmp/output",
        }
    ).run()

    assert calls == [True]


def test_older_opensportslib_keeps_full_download_and_rejects_json_only(monkeypatch):
    calls = []

    def _legacy_download(*args, **kwargs):
        calls.append(kwargs)
        return [{"ok": True}]

    monkeypatch.setattr(
        hf_transfer_controller, "download_dataset_sample_inputs_from_hf", None
    )
    monkeypatch.setattr(
        hf_transfer_controller, "download_dataset_splits_from_hf", _legacy_download
    )
    full_worker = _HfDownloadWorker(
        {
            "repo_id": "OpenSportsLab/repo",
            "revision": "main",
            "splits": ["test"],
            "output_dir": "/tmp/output",
            "annotations_only": False,
        }
    )
    full_completed = []
    full_worker.completed.connect(full_completed.append)
    full_worker.run()

    assert full_completed
    assert "annotations_only" not in calls[0]

    metadata_worker = _HfDownloadWorker(
        {
            "repo_id": "OpenSportsLab/repo",
            "revision": "main",
            "splits": ["test"],
            "output_dir": "/tmp/output",
            "annotations_only": True,
        }
    )
    failures = []
    metadata_worker.failed.connect(failures.append)
    metadata_worker.run()

    assert "newer local OpenSportsLib" in failures[0]


def test_upload_worker_routes_json_mode_to_library_api(monkeypatch, tmp_path):
    calls = {}

    def _fake_upload_dataset_inputs_from_json_to_hf(**kwargs):
        calls.update(kwargs)
        return {"upload_kind": "json"}

    monkeypatch.setattr(
        hf_transfer_controller,
        "upload_dataset_inputs_from_json_to_hf",
        _fake_upload_dataset_inputs_from_json_to_hf,
    )

    json_path = tmp_path / "annotations.json"
    json_path.write_text('{"data": []}', encoding="utf-8")

    worker = _HfUploadWorker(
        {
            "upload_as_json": True,
            "repo_id": "OpenSportsLab/repo",
            "json_path": str(json_path),
            "revision": "main",
            "split": "test",
            "commit_message": "msg",
            "token": "hf_test",
        }
    )

    completed_payloads = []
    worker.completed.connect(lambda payload: completed_payloads.append(payload))
    worker.run()

    assert calls["repo_id"] == "OpenSportsLab/repo"
    assert calls["json_path"] == str(json_path)
    assert calls["revision"] == "main"
    assert calls["split"] == "test"
    assert calls["commit_message"] == "msg"
    assert calls["token"] == "hf_test"
    assert callable(calls["progress_cb"])
    assert callable(calls["is_cancelled"])
    assert completed_payloads == [{"upload_kind": "json"}]


def test_upload_worker_can_disable_xet_for_only_that_transfer(monkeypatch):
    from huggingface_hub import constants

    observed = []
    previous_environment = os.environ.get("HF_HUB_DISABLE_XET")
    previous_constant = constants.HF_HUB_DISABLE_XET

    def _fake_upload(**kwargs):
        del kwargs
        observed.append(
            (os.environ.get("HF_HUB_DISABLE_XET"), constants.HF_HUB_DISABLE_XET)
        )
        return {"ok": True}

    monkeypatch.setattr(
        hf_transfer_controller,
        "upload_dataset_inputs_from_json_to_hf",
        _fake_upload,
    )

    _HfUploadWorker(
        {"upload_as_json": True, "use_xet": False}
    ).run()

    assert observed == [("1", True)]
    assert os.environ.get("HF_HUB_DISABLE_XET") == previous_environment
    assert constants.HF_HUB_DISABLE_XET is previous_constant


def test_upload_worker_routes_parquet_mode_to_library_api(monkeypatch, tmp_path):
    calls = {}

    def _fake_upload_dataset_as_parquet_to_hf(**kwargs):
        calls.update(kwargs)
        return {"upload_kind": "parquet"}

    monkeypatch.setattr(
        hf_transfer_controller,
        "upload_dataset_as_parquet_to_hf",
        _fake_upload_dataset_as_parquet_to_hf,
    )

    json_path = tmp_path / "annotations.json"
    json_path.write_text('{"data": []}', encoding="utf-8")

    worker = _HfUploadWorker(
        {
            "upload_as_json": False,
            "repo_id": "OpenSportsLab/repo",
            "json_path": str(json_path),
            "revision": "dev",
            "split": "test",
            "commit_message": "msg",
            "shard_size": 250_000_000,
            "token": "hf_test",
        }
    )

    completed_payloads = []
    worker.completed.connect(lambda payload: completed_payloads.append(payload))
    worker.run()

    assert calls["repo_id"] == "OpenSportsLab/repo"
    assert calls["json_path"] == str(json_path)
    assert calls["revision"] == "dev"
    assert calls["split"] == "test"
    assert calls["shard_mode"] == "size"
    assert calls["shard_size"] == 250_000_000
    assert calls["token"] == "hf_test"
    assert callable(calls["progress_cb"])
    assert callable(calls["is_cancelled"])
    assert completed_payloads == [{"upload_kind": "parquet"}]


def test_download_worker_emits_cancelled_for_transfer_cancel(monkeypatch):
    def _raise_cancel(*args, **kwargs):
        raise hf_transfer.HfTransferCancelled("Transfer cancelled by user.")

    monkeypatch.setattr(hf_transfer_controller, "download_dataset_splits_from_hf", _raise_cancel)

    worker = _HfDownloadWorker({"repo_id": "r", "revision": "main", "splits": ["s"], "output_dir": "o"})
    cancelled_messages = []
    worker.cancelled.connect(lambda msg: cancelled_messages.append(msg))
    worker.run()

    assert cancelled_messages == ["Transfer cancelled by user."]


def test_selective_download_worker_uses_same_cancellation_signal(monkeypatch):
    def _raise_cancel(*args, **kwargs):
        raise hf_transfer_controller.HfTransferCancelled(
            "Transfer cancelled by user."
        )

    monkeypatch.setattr(
        hf_transfer_controller,
        "download_dataset_sample_inputs_from_hf",
        _raise_cancel,
    )
    worker = _HfDownloadWorker(
        {
            "operation": "assets",
            "dataset_json_path": "/tmp/test.json",
            "sample_id": "sample-1",
        }
    )
    cancelled_messages = []
    worker.cancelled.connect(cancelled_messages.append)

    worker.run()

    assert cancelled_messages == ["Transfer cancelled by user."]


def test_upload_worker_emits_failed_for_generic_error(monkeypatch):
    def _raise_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(hf_transfer_controller, "upload_dataset_inputs_from_json_to_hf", _raise_error)

    worker = _HfUploadWorker({"upload_as_json": True})
    failed_messages = []
    worker.failed.connect(lambda msg: failed_messages.append(msg))
    worker.run()

    assert failed_messages == ["boom"]


def test_model_worker_routes_progress_and_completion(monkeypatch):
    calls = {}

    def fake_resolve(config, *, progress_cb, is_cancelled):
        calls["config"] = config
        calls["is_cancelled"] = is_cancelled
        progress_cb("Downloading model…", 2, 3)
        return {"id": "owner/model", "task": "classification"}

    monkeypatch.setattr(hf_transfer_controller, "resolve_hf_local_model", fake_resolve)
    worker = _HfModelWorker(
        {"repo_id": "owner/model", "revision": "v1", "token": "hf_test"}
    )
    progress = []
    completed = []
    worker.progress.connect(lambda *args: progress.append(args))
    worker.completed.connect(completed.append)
    worker.run()
    assert calls["config"]["revision"] == "v1"
    assert callable(calls["is_cancelled"])
    assert progress == [("Downloading model…", 2, 3)]
    assert completed == [{"id": "owner/model", "task": "classification"}]


def test_model_worker_suppresses_cancelled_completion(monkeypatch):
    monkeypatch.setattr(
        hf_transfer_controller,
        "resolve_hf_local_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HfModelImportCancelled("Model download cancelled.")
        ),
    )
    worker = _HfModelWorker({"repo_id": "owner/model"})
    cancelled = []
    completed = []
    worker.cancelled.connect(cancelled.append)
    worker.completed.connect(completed.append)
    worker.run()
    assert cancelled == ["Model download cancelled."]
    assert completed == []
