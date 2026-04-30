from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "convert_dataset_videos_to_224p.py"
SPEC = importlib.util.spec_from_file_location("convert_dataset_videos_to_224p", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
tool_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool_module)
convert_dataset_videos_to_224p = tool_module.convert_dataset_videos_to_224p


def _payload() -> dict:
    return {
        "version": "2.0",
        "dataset_name": "example",
        "metadata": {"sport": "soccer"},
        "labels": {"action": {"type": "single_label", "labels": ["foul"]}},
        "data": [
            {
                "id": "sample_1",
                "inputs": [
                    {"type": "video", "path": "clips/a.mp4", "fps": 50},
                    {"type": "video", "path": "clips/b.mp4"},
                    {"type": "captions", "path": "captions/a.json"},
                ],
                "labels": {"action": {"label": "foul"}},
            }
        ],
    }


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")


def test_rewrites_video_paths_and_preserves_annotations(tmp_path, monkeypatch):
    media_root = tmp_path / "source"
    output_media_root = tmp_path / "224p"
    output_json_path = tmp_path / "out" / "annotations.json"
    _touch(media_root / "clips/a.mp4")
    _touch(media_root / "clips/b.mp4")
    calls = []

    def fake_run(command, check):
        calls.append(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    original = _payload()

    converted, stats = convert_dataset_videos_to_224p(
        copy.deepcopy(original),
        json_path=tmp_path / "annotations.json",
        media_root=media_root,
        output_json_path=output_json_path,
        output_media_root=output_media_root,
        ffmpeg_executable="/usr/bin/ffmpeg",
    )

    assert converted["metadata"] == original["metadata"]
    assert converted["labels"] == original["labels"]
    assert converted["data"][0]["labels"] == original["data"][0]["labels"]
    assert converted["data"][0]["inputs"] == [
        {"type": "video", "path": "clips/a.mp4", "fps": 50},
        {"type": "video", "path": "clips/b.mp4"},
        {"type": "captions", "path": "captions/a.json"},
    ]
    assert json.loads(output_json_path.read_text(encoding="utf-8")) == converted
    assert stats["video_inputs_found"] == 2
    assert stats["videos_converted"] == 2
    assert calls == [
        [
            "/usr/bin/ffmpeg",
            "-y",
            "-i",
            str(media_root / "clips/a.mp4"),
            "-r",
            "25",
            "-vf",
            "scale=-2:224",
            str(output_media_root / "clips/a.mp4"),
        ],
        [
            "/usr/bin/ffmpeg",
            "-y",
            "-i",
            str(media_root / "clips/b.mp4"),
            "-r",
            "25",
            "-vf",
            "scale=-2:224",
            str(output_media_root / "clips/b.mp4"),
        ],
    ]


def test_missing_source_video_raises_by_default(tmp_path):
    payload = _payload()
    media_root = tmp_path / "source"
    _touch(media_root / "clips/a.mp4")

    with pytest.raises(FileNotFoundError, match="Missing source video"):
        convert_dataset_videos_to_224p(
            payload,
            json_path=tmp_path / "annotations.json",
            media_root=media_root,
            output_json_path=tmp_path / "out.json",
            output_media_root=tmp_path / "224p",
            ffmpeg_executable="/usr/bin/ffmpeg",
        )


def test_missing_source_video_can_be_skipped(tmp_path, monkeypatch):
    media_root = tmp_path / "source"
    _touch(media_root / "clips/a.mp4")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda command, check: calls.append(command))

    converted, stats = convert_dataset_videos_to_224p(
        _payload(),
        json_path=tmp_path / "annotations.json",
        media_root=media_root,
        output_json_path=tmp_path / "out.json",
        output_media_root=tmp_path / "224p",
        missing_policy="skip",
        ffmpeg_executable="/usr/bin/ffmpeg",
    )

    assert converted["data"][0]["inputs"][1]["path"] == "clips/b.mp4"
    assert stats["video_inputs_found"] == 2
    assert stats["videos_skipped_missing"] == 1
    assert stats["videos_converted"] == 1
    assert len(calls) == 1


def test_existing_outputs_require_overwrite(tmp_path):
    media_root = tmp_path / "source"
    output_media_root = tmp_path / "224p"
    _touch(media_root / "clips/a.mp4")
    _touch(media_root / "clips/b.mp4")
    _touch(output_media_root / "clips/a.mp4")

    with pytest.raises(FileExistsError, match="Output video already exists"):
        convert_dataset_videos_to_224p(
            _payload(),
            json_path=tmp_path / "annotations.json",
            media_root=media_root,
            output_json_path=tmp_path / "out.json",
            output_media_root=output_media_root,
            ffmpeg_executable="/usr/bin/ffmpeg",
        )


def test_existing_json_requires_overwrite(tmp_path):
    media_root = tmp_path / "source"
    _touch(media_root / "clips/a.mp4")
    _touch(media_root / "clips/b.mp4")
    output_json_path = tmp_path / "out.json"
    output_json_path.write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Output JSON already exists"):
        convert_dataset_videos_to_224p(
            _payload(),
            json_path=tmp_path / "annotations.json",
            media_root=media_root,
            output_json_path=output_json_path,
            output_media_root=tmp_path / "224p",
            ffmpeg_executable="/usr/bin/ffmpeg",
        )


def test_dry_run_does_not_write_outputs(tmp_path, monkeypatch):
    media_root = tmp_path / "source"
    output_json_path = tmp_path / "out.json"
    output_media_root = tmp_path / "224p"
    _touch(media_root / "clips/a.mp4")
    _touch(media_root / "clips/b.mp4")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda command, check: pytest.fail("dry run must not call ffmpeg"),
    )

    _, stats = convert_dataset_videos_to_224p(
        _payload(),
        json_path=tmp_path / "annotations.json",
        media_root=media_root,
        output_json_path=output_json_path,
        output_media_root=output_media_root,
        dry_run=True,
        ffmpeg_executable="/usr/bin/ffmpeg",
    )

    assert stats["video_inputs_found"] == 2
    assert stats["videos_converted"] == 0
    assert len(stats["planned_outputs"]) == 2
    assert not output_json_path.exists()
    assert not output_media_root.exists()


def test_ffmpeg_failure_is_reported_and_remaining_videos_continue(tmp_path, monkeypatch):
    media_root = tmp_path / "source"
    output_media_root = tmp_path / "224p"
    output_json_path = tmp_path / "out.json"
    _touch(media_root / "clips/a.mp4")
    _touch(media_root / "clips/b.mp4")
    calls = []

    def fake_run(command, check):
        calls.append(command)
        if command[-1].endswith("a.mp4"):
            Path(command[-1]).write_bytes(b"partial")
            raise subprocess.CalledProcessError(234, command)

    monkeypatch.setattr(subprocess, "run", fake_run)

    converted, stats = convert_dataset_videos_to_224p(
        _payload(),
        json_path=tmp_path / "annotations.json",
        media_root=media_root,
        output_json_path=output_json_path,
        output_media_root=output_media_root,
        ffmpeg_executable="/usr/bin/ffmpeg",
    )

    assert stats["videos_converted"] == 1
    assert stats["videos_failed"] == 1
    assert stats["failed_conversions"] == [
        {
            "source": str(media_root / "clips/a.mp4"),
            "output": str(output_media_root / "clips/a.mp4"),
            "returncode": 234,
        }
    ]
    assert len(calls) == 2
    assert not (output_media_root / "clips/a.mp4").exists()
    assert json.loads(output_json_path.read_text(encoding="utf-8")) == converted
