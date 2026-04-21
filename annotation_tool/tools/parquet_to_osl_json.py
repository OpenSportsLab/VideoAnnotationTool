"""
Convert a dataset stored as:
  - metadata.parquet
  - WebDataset TAR shards (created by osl_json_to_parquet.py)

back into an OpenSportsLib-style JSON file.

Notes
-----
- Reconstruction relies on the per-sample sidecar JSON stored inside each TAR shard.
  The sidecar is the canonical full-fidelity annotation source.
- metadata.parquet is used only for routing (sample_index, shard_name) and lightweight
  filtering; it does not store a full copy of each sample.
- By default, reconstructed ``inputs[].path`` values remain the original relative paths.
  Pass ``extract_media=True`` to also extract the input files from the shards.

Public entry point:
    convert_parquet_to_json(...)
"""

from __future__ import annotations

import json
import shutil
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def _maybe_json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, float) and pd.isna(value):
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
        try:
            return json.loads(value)
        except Exception:
            return default
    return default


def _read_sidecar_json_from_tar(tar_path: Path, sample_index: int) -> Optional[Dict[str, Any]]:
    key = f"{sample_index:09d}.json"
    with tarfile.open(tar_path, "r") as tar:
        try:
            member = tar.getmember(key)
        except KeyError:
            return None
        f = tar.extractfile(member)
        if f is None:
            return None
        return json.loads(f.read().decode("utf-8"))


def _extract_sample_media_from_tar(
    tar_path: Path,
    sample_index: int,
    output_media_root: Path,
    original_paths: List[str],
    overwrite: bool = False,
) -> int:
    """
    Extract all input files for *sample_index* from the shard.

    Files are written to ``output_media_root / original_path``, preserving the
    original relative path structure so that ``inputs[].path`` values stay valid.

    Returns the number of files extracted.
    """
    key_prefix = f"{sample_index:09d}."
    extracted = 0

    with tarfile.open(tar_path, "r") as tar:
        members = [
            m for m in tar.getmembers()
            if m.isfile()
            and m.name.startswith(key_prefix)
            and not m.name.endswith(".json")
        ]

        def _input_idx(m: tarfile.TarInfo) -> int:
            part = m.name[len(key_prefix):].split(".", 1)[0]
            try:
                return int(part)
            except ValueError:
                return 0

        members.sort(key=_input_idx)

        for member in members:
            input_idx = _input_idx(member)
            if input_idx >= len(original_paths):
                continue
            out_path = output_media_root / original_paths[input_idx]
            if out_path.exists() and not overwrite:
                extracted += 1
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)
            f = tar.extractfile(member)
            if f is None:
                continue
            with open(out_path, "wb") as out_f:
                shutil.copyfileobj(f, out_f)
            extracted += 1

    return extracted


def _reconstruct_sample_from_row(
    row: pd.Series,
    sidecar: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a sample dict from a Parquet row, enriched by sidecar when available.

    This is the primary reconstruction path — the sidecar carries the full
    annotation payload, so the Parquet columns serve only as a fallback.
    """
    fallback_sample: Dict[str, Any] = {"id": row["sample_id"], "inputs": []}
    built_from_payload = False

    # Preferred generic column: full sample payload.
    sample_payload = _maybe_json_loads(row.get("sample_payload"), None)
    if isinstance(sample_payload, dict):
        fallback_sample = dict(sample_payload)
        fallback_sample.setdefault("id", row["sample_id"])
        built_from_payload = True
    # Legacy fallback for older exports.
    else:
        # Older generic column: full list of input dictionaries only.
        sample_inputs = _maybe_json_loads(row.get("sample_inputs"), None)
        if isinstance(sample_inputs, list):
            for inp in sample_inputs:
                if isinstance(inp, dict):
                    fallback_sample["inputs"].append(dict(inp))
            fallback_sample["metadata"] = _maybe_json_loads(row.get("sample_metadata"), {})
            fallback_sample["labels"] = _maybe_json_loads(row.get("sample_labels"), {})
            fallback_sample["events"] = _maybe_json_loads(row.get("sample_events"), [])
            fallback_sample["captions"] = _maybe_json_loads(row.get("sample_captions"), [])
            fallback_sample["dense_captions"] = _maybe_json_loads(row.get("sample_dense_captions"), [])
        else:
            # Oldest legacy fallback: split input/video columns.
            input_paths = _maybe_json_loads(row.get("input_paths"), None)
            if isinstance(input_paths, list):
                input_types = _maybe_json_loads(row.get("input_types"), [])
                input_names = _maybe_json_loads(row.get("input_names"), [])
                input_fps = _maybe_json_loads(row.get("input_fps"), [])
            else:
                input_paths = _maybe_json_loads(row.get("video_paths"), [])
                input_types = ["video"] * len(input_paths)
                input_names = _maybe_json_loads(row.get("video_names"), [])
                input_fps = _maybe_json_loads(row.get("video_fps"), [])

            for i, path in enumerate(input_paths):
                raw_type = input_types[i] if i < len(input_types) else None
                input_type = str(raw_type).strip() if raw_type is not None else ""
                if not input_type:
                    input_type = "video"
                inp: Dict[str, Any] = {"type": input_type, "path": path}
                if i < len(input_names):
                    inp["name"] = input_names[i]
                if i < len(input_fps):
                    inp["fps"] = input_fps[i]
                fallback_sample["inputs"].append(inp)

            fallback_sample["metadata"] = _maybe_json_loads(row.get("sample_metadata"), {})
            fallback_sample["labels"] = _maybe_json_loads(row.get("sample_labels"), {})
            fallback_sample["events"] = _maybe_json_loads(row.get("sample_events"), [])
            fallback_sample["captions"] = _maybe_json_loads(row.get("sample_captions"), [])
            fallback_sample["dense_captions"] = _maybe_json_loads(row.get("sample_dense_captions"), [])

    if isinstance(sidecar, dict):
        sample = dict(sidecar)
        sample.setdefault("id", row["sample_id"])
        sample.setdefault("inputs", fallback_sample["inputs"])
        return sample

    if built_from_payload:
        return fallback_sample

    # Drop empty optional fields for a cleaner output JSON
    sample = fallback_sample
    for field in ("metadata", "labels", "events", "captions", "dense_captions"):
        if field in sample and not sample[field]:
            sample.pop(field)

    return sample


def convert_parquet_to_json(
    dataset_dir: str | Path,
    output_json_path: str | Path,
    *,
    extract_media: bool = False,
    output_media_root: Optional[str | Path] = None,
    overwrite_media: bool = False,
    json_indent: int = 2,
) -> Dict[str, Any]:
    """
    Convert a Parquet + WebDataset directory back to an OSL-style JSON file.

    The input directory must have been created by
    :func:`annotation_tool.tools.osl_json_to_parquet.convert_json_to_parquet`
    and must contain ``metadata.parquet`` and a ``shards/`` sub-directory.

    Parameters
    ----------
    dataset_dir:
        Directory produced by the forward converter.
    output_json_path:
        Destination JSON file path.
    extract_media:
        If ``True``, extract media files from TAR shards into ``output_media_root``.
        ``inputs[].path`` values are preserved as-is (original relative paths).
    output_media_root:
        Root directory for extracted media. Required when ``extract_media=True``.
    overwrite_media:
        Whether to overwrite already-extracted media files.
    json_indent:
        Indentation level for the output JSON.

    Returns
    -------
    dict
        Summary with sample count and extraction statistics.
    """
    dataset_dir = Path(dataset_dir)
    output_json_path = Path(output_json_path)
    metadata_path = dataset_dir / "metadata.parquet"
    shards_dir = dataset_dir / "shards"

    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing metadata file: {metadata_path}")
    if not shards_dir.exists():
        raise FileNotFoundError(f"Missing shards directory: {shards_dir}")
    if extract_media and output_media_root is None:
        raise ValueError("output_media_root must be provided when extract_media=True")

    output_media_root_path = Path(output_media_root) if output_media_root is not None else None
    if output_media_root_path is not None:
        output_media_root_path.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(metadata_path).sort_values("sample_index").reset_index(drop=True)
    if len(df) == 0:
        raise ValueError("metadata.parquet is empty.")

    first = df.iloc[0]
    top_doc = _maybe_json_loads(first.get("header"), None)
    if not isinstance(top_doc, dict):
        top_doc = _maybe_json_loads(first.get("top_level_document"), None)
    if not isinstance(top_doc, dict):
        top_doc = {
            "version": first.get("json_version"),
            "date": first.get("json_date"),
            "task": first.get("task"),
            "dataset_name": first.get("dataset_name"),
            "metadata": _maybe_json_loads(first.get("top_level_metadata"), {}),
        }
        top_labels = _maybe_json_loads(first.get("top_level_labels"), {})
        if top_labels:
            top_doc["labels"] = top_labels
    top_doc.pop("data", None)

    data: List[Dict[str, Any]] = []
    extracted_media_count = 0

    for _, row in df.iterrows():
        sample_index = int(row["sample_index"])
        shard_name = row["shard_name"]
        tar_path = shards_dir / shard_name

        sidecar = _read_sidecar_json_from_tar(tar_path, sample_index)
        sample = _reconstruct_sample_from_row(row, sidecar=sidecar)

        if extract_media:
            inputs = sample.get("inputs", []) if isinstance(sample, dict) else []
            if "sample_payload" in row.index or "sample_inputs" in row.index or "input_paths" in row.index:
                original_input_paths = [
                    str(inp["path"])
                    for inp in inputs
                    if isinstance(inp, dict) and inp.get("path")
                ]
            else:
                # Legacy exports stored only video files with video-only indexing.
                original_input_paths = [
                    str(inp["path"])
                    for inp in inputs
                    if isinstance(inp, dict)
                    and inp.get("type") == "video"
                    and inp.get("path")
                ]
            extracted_media_count += _extract_sample_media_from_tar(
                tar_path=tar_path,
                sample_index=sample_index,
                output_media_root=output_media_root_path,
                original_paths=original_input_paths,
                overwrite=overwrite_media,
            )

        data.append(sample)

    top_doc["data"] = data

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(top_doc, f, ensure_ascii=False, indent=json_indent)

    return {
        "dataset_dir": str(dataset_dir),
        "output_json_path": str(output_json_path),
        "num_samples": len(data),
        "extract_media": extract_media,
        "output_media_root": str(output_media_root_path) if output_media_root_path else None,
        "extracted_input_files": extracted_media_count,
        "extracted_media_files": extracted_media_count,
    }
