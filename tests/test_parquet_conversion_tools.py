import json

import pandas as pd

from tools.osl_json_to_parquet import convert_json_to_parquet
from tools.parquet_to_osl_json import convert_parquet_to_json


def test_json_to_parquet_and_back_supports_non_video_inputs(tmp_path):
    tracking_path = tmp_path / "test" / "clip_000000.parquet"
    video_path = tmp_path / "test" / "clip_000000.mp4"
    tracking_path.parent.mkdir(parents=True)
    tracking_path.write_bytes(b"tracking-bytes")
    video_path.write_bytes(b"video-bytes")

    payload = {
        "version": "2.0",
        "date": "2026-03-08",
        "task": "action_classification",
        "modalities": ["tracking_parquet", "video"],
        "dataset_name": "mixed_modalities_test",
        "metadata": {"split": "test"},
        "labels": {"action": {"type": "single_label", "labels": ["PASS"]}},
        "data": [
            {
                "id": "sample_000000",
                "inputs": [
                    {"type": "tracking_parquet", "path": "test/clip_000000.parquet"},
                    {"type": "video", "path": "test/clip_000000.mp4", "fps": 25.0},
                ],
                "labels": {"action": {"label": "PASS"}},
                "metadata": {"game_id": "3850"},
            }
        ],
    }
    json_path = tmp_path / "annotations_test.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    parquet_dataset_dir = tmp_path / "converted_dataset"
    forward_result = convert_json_to_parquet(
        json_path=json_path,
        media_root=tmp_path,
        output_dir=parquet_dataset_dir,
        overwrite=True,
    )

    assert forward_result["input_files_added"] == 2
    assert "video_files_added" not in forward_result

    metadata_df = pd.read_parquet(parquet_dataset_dir / "metadata.parquet")
    row = metadata_df.iloc[0]
    assert "header" in metadata_df.columns
    assert "task" not in metadata_df.columns
    assert "dataset_name" not in metadata_df.columns
    assert "json_version" not in metadata_df.columns
    assert "json_date" not in metadata_df.columns
    assert "top_level_metadata" not in metadata_df.columns
    assert "top_level_labels" not in metadata_df.columns
    assert "top_level_document" not in metadata_df.columns
    assert json.loads(row["header"]) == {k: v for k, v in payload.items() if k != "data"}
    assert "sample_inputs" not in metadata_df.columns
    assert "input_paths" not in metadata_df.columns
    assert "input_types" not in metadata_df.columns
    assert json.loads(row["sample_payload"]) == payload["data"][0]

    restored_json_path = tmp_path / "restored" / "annotations_test.json"
    restored_media_root = tmp_path / "restored"
    backward_result = convert_parquet_to_json(
        dataset_dir=parquet_dataset_dir,
        output_json_path=restored_json_path,
        extract_media=True,
        output_media_root=restored_media_root,
    )

    restored_payload = json.loads(restored_json_path.read_text(encoding="utf-8"))
    assert restored_payload["modalities"] == payload["modalities"]
    assert restored_payload["data"][0]["inputs"] == payload["data"][0]["inputs"]
    assert backward_result["extracted_input_files"] == 2
    assert (restored_media_root / "test" / "clip_000000.parquet").is_file()
    assert (restored_media_root / "test" / "clip_000000.mp4").is_file()
