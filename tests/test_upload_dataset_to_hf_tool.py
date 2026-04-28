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
