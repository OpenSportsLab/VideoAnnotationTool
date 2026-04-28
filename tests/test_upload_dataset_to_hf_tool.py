from __future__ import annotations

import importlib.util
from pathlib import Path

import opensportslib.tools.hf_transfer as hf_transfer
import pytest


TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "upload_dataset_to_hf.py"
SPEC = importlib.util.spec_from_file_location("upload_dataset_to_hf", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
tool_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool_module)


def test_upload_json_routes_to_opensportslib_json_api(monkeypatch, tmp_path):
    calls = {}

    def fake_upload_dataset_inputs_from_json_to_hf(**kwargs):
        calls.update(kwargs)
        return {"kind": "json", "repo_id": kwargs["repo_id"]}

    monkeypatch.setattr(
        hf_transfer,
        "upload_dataset_inputs_from_json_to_hf",
        fake_upload_dataset_inputs_from_json_to_hf,
    )
    json_path = tmp_path / "annotations.json"
    json_path.write_text('{"data": []}', encoding="utf-8")
    progress_messages = []

    result = tool_module.upload_dataset_to_hf(
        repo_id="OpenSportsLab/example",
        json_path=json_path,
        revision="dev",
        commit_message="Upload JSON",
        token="hf_test",
        upload_format="json",
        progress_cb=progress_messages.append,
    )

    assert result == {"kind": "json", "repo_id": "OpenSportsLab/example"}
    assert calls == {
        "repo_id": "OpenSportsLab/example",
        "json_path": str(json_path),
        "revision": "dev",
        "commit_message": "Upload JSON",
        "token": "hf_test",
        "progress_cb": progress_messages.append,
    }


def test_upload_parquet_routes_to_opensportslib_parquet_api(monkeypatch, tmp_path):
    calls = {}

    def fake_upload_dataset_as_parquet_to_hf(**kwargs):
        calls.update(kwargs)
        return {"kind": "parquet", "shard_size": kwargs["shard_size"]}

    monkeypatch.setattr(
        hf_transfer,
        "upload_dataset_as_parquet_to_hf",
        fake_upload_dataset_as_parquet_to_hf,
    )
    json_path = tmp_path / "annotations.json"
    json_path.write_text('{"data": []}', encoding="utf-8")

    result = tool_module.upload_dataset_to_hf(
        repo_id="OpenSportsLab/example",
        json_path=json_path,
        revision="main",
        commit_message="Upload Parquet",
        token=None,
        upload_format="parquet",
        shard_mode="size",
        shard_size=500_000_000,
        progress_cb=None,
    )

    assert result == {"kind": "parquet", "shard_size": 500_000_000}
    assert calls == {
        "repo_id": "OpenSportsLab/example",
        "json_path": str(json_path),
        "revision": "main",
        "commit_message": "Upload Parquet",
        "shard_mode": "size",
        "shard_size": 500_000_000,
        "token": None,
        "progress_cb": None,
    }


@pytest.mark.parametrize(
    ("raw_size", "expected"),
    [
        ("500MB", 500_000_000),
        ("1GB", 1_000_000_000),
        ("1024MiB", 1_073_741_824),
        ("42", 42),
    ],
)
def test_parse_size(raw_size, expected):
    assert tool_module._parse_size(raw_size) == expected


def test_missing_json_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="Dataset JSON does not exist"):
        tool_module.upload_dataset_to_hf(
            repo_id="OpenSportsLab/example",
            json_path=tmp_path / "missing.json",
        )


def test_missing_repo_is_created_and_upload_retried(monkeypatch, tmp_path):
    calls = []

    def fake_upload_dataset_inputs_from_json_to_hf(**kwargs):
        calls.append(("upload", kwargs["repo_id"], kwargs["revision"]))
        if len([call for call in calls if call[0] == "upload"]) == 1:
            raise RuntimeError("Repository Not Found for url")
        return {"kind": "json", "attempts": 2}

    def fake_create_dataset_repo_on_hf(**kwargs):
        calls.append(("create_repo", kwargs["repo_id"], kwargs["token"]))

    monkeypatch.setattr(
        hf_transfer,
        "upload_dataset_inputs_from_json_to_hf",
        fake_upload_dataset_inputs_from_json_to_hf,
    )
    monkeypatch.setattr(hf_transfer, "create_dataset_repo_on_hf", fake_create_dataset_repo_on_hf)
    json_path = tmp_path / "annotations.json"
    json_path.write_text('{"data": []}', encoding="utf-8")
    progress_messages = []

    result = tool_module.upload_dataset_to_hf(
        repo_id="OpenSportsLab/missing",
        json_path=json_path,
        revision="main",
        token="hf_test",
        progress_cb=progress_messages.append,
    )

    assert result == {"kind": "json", "attempts": 2}
    assert calls == [
        ("upload", "OpenSportsLab/missing", "main"),
        ("create_repo", "OpenSportsLab/missing", "hf_test"),
        ("upload", "OpenSportsLab/missing", "main"),
    ]
    assert any("Creating it" in message for message in progress_messages)


def test_missing_revision_is_created_and_upload_retried(monkeypatch, tmp_path):
    calls = []

    def fake_upload_dataset_inputs_from_json_to_hf(**kwargs):
        calls.append(("upload", kwargs["repo_id"], kwargs["revision"]))
        if len([call for call in calls if call[0] == "upload"]) == 1:
            raise RuntimeError("Revision Not Found")
        return {"kind": "json", "attempts": 2}

    def fake_create_dataset_branch_on_hf(**kwargs):
        calls.append(
            (
                "create_branch",
                kwargs["repo_id"],
                kwargs["branch"],
                kwargs["source_revision"],
                kwargs["token"],
            )
        )

    monkeypatch.setattr(
        hf_transfer,
        "upload_dataset_inputs_from_json_to_hf",
        fake_upload_dataset_inputs_from_json_to_hf,
    )
    monkeypatch.setattr(hf_transfer, "create_dataset_branch_on_hf", fake_create_dataset_branch_on_hf)
    json_path = tmp_path / "annotations.json"
    json_path.write_text('{"data": []}', encoding="utf-8")

    result = tool_module.upload_dataset_to_hf(
        repo_id="OpenSportsLab/example",
        json_path=json_path,
        revision="dev",
        token="hf_test",
        progress_cb=None,
    )

    assert result == {"kind": "json", "attempts": 2}
    assert calls == [
        ("upload", "OpenSportsLab/example", "dev"),
        ("create_branch", "OpenSportsLab/example", "dev", "main", "hf_test"),
        ("upload", "OpenSportsLab/example", "dev"),
    ]


def test_ambiguous_missing_branch_error_creates_branch_when_repo_exists(monkeypatch, tmp_path):
    calls = []

    def fake_upload_dataset_inputs_from_json_to_hf(**kwargs):
        calls.append(("upload", kwargs["repo_id"], kwargs["revision"]))
        if len([call for call in calls if call[0] == "upload"]) == 1:
            raise RuntimeError("Repository Not Found for url /preupload/dev")
        return {"kind": "json", "attempts": 2}

    monkeypatch.setattr(
        hf_transfer,
        "upload_dataset_inputs_from_json_to_hf",
        fake_upload_dataset_inputs_from_json_to_hf,
    )
    monkeypatch.setattr(
        hf_transfer,
        "dataset_repo_exists_on_hf",
        lambda **kwargs: calls.append(("repo_exists", kwargs["repo_id"])) or True,
    )
    monkeypatch.setattr(
        hf_transfer,
        "create_dataset_branch_on_hf",
        lambda **kwargs: calls.append(("create_branch", kwargs["repo_id"], kwargs["branch"])),
    )
    json_path = tmp_path / "annotations.json"
    json_path.write_text('{"data": []}', encoding="utf-8")

    result = tool_module.upload_dataset_to_hf(
        repo_id="OpenSportsLab/example",
        json_path=json_path,
        revision="dev",
    )

    assert result == {"kind": "json", "attempts": 2}
    assert calls == [
        ("upload", "OpenSportsLab/example", "dev"),
        ("repo_exists", "OpenSportsLab/example"),
        ("create_branch", "OpenSportsLab/example", "dev"),
        ("upload", "OpenSportsLab/example", "dev"),
    ]
