"""
Convert an OpenSportsLib-style JSON annotation file into:
  1) a Parquet table with flattened metadata
  2) WebDataset TAR shards containing the referenced video files + sample metadata

Each sample typically contains:
  - id
  - inputs: [{"type": "video", "path": "...", ...}, ...]
  - optional task-specific fields: events / captions / dense_captions / labels / metadata

Public entry point:
    convert_json_to_parquet(...)
"""

from __future__ import annotations

import io
import json
import math
import shutil
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _load_json(json_path: str | Path) -> Dict[str, Any]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_video_inputs(sample: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [inp for inp in sample.get("inputs", []) if inp.get("type") == "video" and inp.get("path")]


def _flatten_sample_for_parquet(
    sample: Dict[str, Any],
    sample_index: int,
    shard_pattern: str = "shard-%06d.tar",
) -> Dict[str, Any]:
    sample_id = sample.get("id", f"sample_{sample_index:06d}")
    video_inputs = _extract_video_inputs(sample)

    row: Dict[str, Any] = {
        "sample_id": sample_id,
        "num_video_inputs": len(video_inputs),
        "video_paths": _json_dumps([v.get("path") for v in video_inputs]),
        "video_names": _json_dumps([v.get("name") for v in video_inputs]),
        "video_fps": _json_dumps([v.get("fps") for v in video_inputs]),
        "sample_metadata": _json_dumps(sample.get("metadata", {})),
        "sample_labels": _json_dumps(sample.get("labels", {})),
        "sample_events": _json_dumps(sample.get("events", [])),
        "sample_captions": _json_dumps(sample.get("captions", [])),
        "sample_dense_captions": _json_dumps(sample.get("dense_captions", [])),
        "suggested_shard_pattern": shard_pattern,
    }

    # Promote scalar metadata fields for easy filtering
    for k, v in sample.get("metadata", {}).items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            row[f"meta__{k}"] = v

    # Promote single-label annotations for easy filtering
    for head, value in sample.get("labels", {}).items():
        if isinstance(value, dict) and "label" in value and isinstance(value["label"], (str, int, float, bool)):
            row[f"label__{head}"] = value["label"]

    return row


def _build_sidecar_metadata(sample: Dict[str, Any]) -> bytes:
    """Canonical per-sample annotation payload stored as JSON inside each TAR shard."""
    payload = {
        "id": sample.get("id"),
        "metadata": sample.get("metadata", {}),
        "labels": sample.get("labels", {}),
        "events": sample.get("events", []),
        "captions": sample.get("captions", []),
        "dense_captions": sample.get("dense_captions", []),
        "inputs": sample.get("inputs", []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _resolve_media_path(
    media_root: str | Path,
    relative_path: str,
    missing_policy: str = "raise",
) -> Optional[Path]:
    path = Path(media_root) / relative_path
    if path.exists():
        return path
    if missing_policy == "skip":
        return None
    raise FileNotFoundError(f"Missing media file: {path}")


def _add_bytes_to_tar(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _add_file_to_tar(tar: tarfile.TarFile, src_path: Path, arcname: str) -> None:
    tar.add(str(src_path), arcname=arcname, recursive=False)


def convert_json_to_parquet(
    json_path: str | Path,
    media_root: str | Path,
    output_dir: str | Path,
    *,
    samples_per_shard: int = 100,
    compression: Optional[str] = "zstd",
    shard_prefix: str = "shard",
    missing_policy: str = "raise",
    keep_relative_paths_in_parquet: bool = True,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """
    Convert an OSL-style JSON file to:
      - metadata.parquet  (flattened, queryable per-sample table)
      - shards/*.tar      (WebDataset TAR shards with video files + sidecar JSON)
      - shard_manifest.parquet

    Parameters
    ----------
    json_path:
        Path to the JSON annotation file.
    media_root:
        Root directory where the video files referenced in ``inputs[].path`` live.
    output_dir:
        Destination directory.
    samples_per_shard:
        Number of samples grouped in one TAR shard.
    compression:
        Parquet compression codec (``"zstd"``, ``"snappy"``, ``"gzip"``, or ``None``).
    shard_prefix:
        Prefix for TAR shard file names.
    missing_policy:
        ``"raise"`` — abort if a referenced video is missing.
        ``"skip"``  — keep sample in Parquet but omit missing file from shard.
    keep_relative_paths_in_parquet:
        If ``True`` (default), Parquet stores original relative paths from JSON.
        If ``False``, Parquet stores resolved absolute paths.
    overwrite:
        Whether to remove and recreate ``output_dir`` if it already exists.

    Returns
    -------
    dict
        Summary with counts of samples, shards, and video files processed.
    """
    json_path = Path(json_path)
    media_root = Path(media_root)
    output_dir = Path(output_dir)
    shards_dir = output_dir / "shards"
    parquet_path = output_dir / "metadata.parquet"

    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"{output_dir} already exists. Use overwrite=True.")
        shutil.rmtree(output_dir)

    shards_dir.mkdir(parents=True, exist_ok=True)

    doc = _load_json(json_path)
    samples = doc.get("data", [])
    if not isinstance(samples, list):
        raise ValueError("JSON format error: top-level 'data' must be a list.")

    parquet_rows: List[Dict[str, Any]] = []
    shard_manifest: List[Dict[str, Any]] = []
    total_video_files_added = 0
    total_missing_video_files = 0

    num_shards = max(1, math.ceil(len(samples) / max(1, samples_per_shard)))

    for shard_idx in range(num_shards):
        start = shard_idx * samples_per_shard
        end = min(len(samples), (shard_idx + 1) * samples_per_shard)
        shard_samples = samples[start:end]

        shard_name = f"{shard_prefix}-{shard_idx:06d}.tar"
        shard_path = shards_dir / shard_name

        with tarfile.open(shard_path, mode="w") as tar:
            for local_idx, sample in enumerate(shard_samples):
                global_idx = start + local_idx
                sample_id = sample.get("id", f"sample_{global_idx:06d}")
                key = f"{global_idx:09d}"

                row = _flatten_sample_for_parquet(sample, global_idx, shard_pattern=f"{shard_prefix}-%06d.tar")
                row["shard_name"] = shard_name
                row["sample_index"] = global_idx
                row["task"] = doc.get("task")
                row["dataset_name"] = doc.get("dataset_name")
                row["json_version"] = doc.get("version")
                row["json_date"] = doc.get("date")
                row["top_level_metadata"] = _json_dumps(doc.get("metadata", {}))
                row["top_level_labels"] = _json_dumps(doc.get("labels", {}))
                parquet_rows.append(row)

                _add_bytes_to_tar(tar, f"{key}.json", _build_sidecar_metadata(sample))

                for vid_idx, video_inp in enumerate(_extract_video_inputs(sample)):
                    rel_path = video_inp["path"]
                    resolved = _resolve_media_path(media_root, rel_path, missing_policy=missing_policy)

                    if resolved is None:
                        total_missing_video_files += 1
                        shard_manifest.append({
                            "sample_id": sample_id,
                            "shard_name": shard_name,
                            "video_index": vid_idx,
                            "relative_path": rel_path,
                            "resolved_path": None,
                            "status": "missing",
                        })
                        continue

                    ext = resolved.suffix.lstrip(".").lower() or "bin"
                    arcname = f"{key}.{vid_idx}.{ext}"
                    _add_file_to_tar(tar, resolved, arcname)
                    shard_manifest.append({
                        "sample_id": sample_id,
                        "shard_name": shard_name,
                        "video_index": vid_idx,
                        "relative_path": rel_path,
                        "resolved_path": str(resolved if not keep_relative_paths_in_parquet else rel_path),
                        "status": "ok",
                        "wds_member": arcname,
                    })
                    total_video_files_added += 1

    df = pd.DataFrame(parquet_rows)

    if not keep_relative_paths_in_parquet:
        manifest_df = pd.DataFrame(shard_manifest)
        ok_manifest = manifest_df[manifest_df["status"] == "ok"][["sample_id", "relative_path", "resolved_path"]]
        by_sample: Dict[str, List[str]] = {}
        for _, rec in ok_manifest.iterrows():
            by_sample.setdefault(rec["sample_id"], []).append(rec["resolved_path"])
        df["video_paths"] = df["sample_id"].map(lambda sid: _json_dumps(by_sample.get(sid, [])))

    df.to_parquet(parquet_path, index=False, compression=compression)

    manifest_path = output_dir / "shard_manifest.parquet"
    pd.DataFrame(shard_manifest).to_parquet(manifest_path, index=False, compression=compression)

    return {
        "json_path": str(json_path),
        "media_root": str(media_root),
        "output_dir": str(output_dir),
        "parquet_path": str(parquet_path),
        "manifest_path": str(manifest_path),
        "shards_dir": str(shards_dir),
        "num_samples": len(samples),
        "num_shards": num_shards,
        "video_files_added": total_video_files_added,
        "missing_video_files": total_missing_video_files,
    }
