import pytest

import opensportslib.tools.hf_transfer as hf_transfer
from controllers import hf_transfer_controller
from controllers.hf_transfer_controller import _HfDownloadWorker, _HfUploadWorker


def test_controller_module_uses_opensportslib_transfer_functions():
    assert hf_transfer_controller.HfTransferCancelled is hf_transfer.HfTransferCancelled
    assert hf_transfer_controller.download_dataset_from_hf is hf_transfer.download_dataset_from_hf
    assert hf_transfer_controller.upload_dataset_inputs_from_json_to_hf is hf_transfer.upload_dataset_inputs_from_json_to_hf
    assert hf_transfer_controller.upload_dataset_as_parquet_to_hf is hf_transfer.upload_dataset_as_parquet_to_hf


def test_download_worker_routes_to_library_api(monkeypatch):
    calls = {}

    def _fake_download_dataset_from_hf(url, output_dir, **kwargs):
        calls["url"] = url
        calls["output_dir"] = output_dir
        calls.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(hf_transfer_controller, "download_dataset_from_hf", _fake_download_dataset_from_hf)

    worker = _HfDownloadWorker(
        {
            "url": "https://huggingface.co/datasets/OpenSportsLab/repo/blob/main/annotations.json",
            "output_dir": "/tmp/output",
            "dry_run": True,
            "types": "video",
            "token": "hf_test",
        }
    )

    completed_payloads = []
    worker.completed.connect(lambda payload: completed_payloads.append(payload))
    worker.run()

    assert calls["url"].endswith("annotations.json")
    assert calls["output_dir"] == "/tmp/output"
    assert calls["dry_run"] is True
    assert calls["types_arg"] == "video"
    assert calls["token"] == "hf_test"
    assert callable(calls["progress_cb"])
    assert callable(calls["is_cancelled"])
    assert completed_payloads == [{"ok": True}]


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
    assert calls["commit_message"] == "msg"
    assert calls["token"] == "hf_test"
    assert callable(calls["progress_cb"])
    assert callable(calls["is_cancelled"])
    assert completed_payloads == [{"upload_kind": "json"}]


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
            "commit_message": "msg",
            "samples_per_shard": 17,
            "token": "hf_test",
        }
    )

    completed_payloads = []
    worker.completed.connect(lambda payload: completed_payloads.append(payload))
    worker.run()

    assert calls["repo_id"] == "OpenSportsLab/repo"
    assert calls["json_path"] == str(json_path)
    assert calls["revision"] == "dev"
    assert calls["samples_per_shard"] == 17
    assert calls["token"] == "hf_test"
    assert callable(calls["progress_cb"])
    assert callable(calls["is_cancelled"])
    assert completed_payloads == [{"upload_kind": "parquet"}]


def test_download_worker_emits_cancelled_for_transfer_cancel(monkeypatch):
    def _raise_cancel(*args, **kwargs):
        raise hf_transfer.HfTransferCancelled("Transfer cancelled by user.")

    monkeypatch.setattr(hf_transfer_controller, "download_dataset_from_hf", _raise_cancel)

    worker = _HfDownloadWorker({"url": "u", "output_dir": "o"})
    cancelled_messages = []
    worker.cancelled.connect(lambda msg: cancelled_messages.append(msg))
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
