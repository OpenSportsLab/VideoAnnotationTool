#!/usr/bin/env python3
"""Upload an OSL dataset to Hugging Face using opensportslib."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _parse_size(value: str) -> int:
    raw_value = value.strip()
    if not raw_value:
        raise argparse.ArgumentTypeError("size must not be empty")

    units = {
        "b": 1,
        "kb": 1_000,
        "mb": 1_000_000,
        "gb": 1_000_000_000,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
    }
    lower_value = raw_value.lower()
    for suffix, multiplier in sorted(units.items(), key=lambda item: len(item[0]), reverse=True):
        if lower_value.endswith(suffix):
            number = raw_value[: -len(suffix)].strip()
            break
    else:
        number = raw_value
        multiplier = 1

    try:
        parsed = float(number)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid size: {value!r}") from exc

    if parsed <= 0:
        raise argparse.ArgumentTypeError("size must be greater than 0")
    return int(parsed * multiplier)


def _progress(message: str) -> None:
    print(f"[HF] {message}", flush=True)


def _call_progress(progress_cb, message: str) -> None:
    if progress_cb:
        progress_cb(message)


def upload_dataset_to_hf(
    *,
    repo_id: str,
    json_path: Path,
    revision: str = "main",
    commit_message: str | None = None,
    token: str | None = None,
    upload_format: str = "json",
    shard_mode: str = "size",
    shard_size: int = 1_000_000_000,
    progress_cb=_progress,
) -> dict[str, Any]:
    if upload_format not in {"json", "parquet"}:
        raise ValueError("upload_format must be 'json' or 'parquet'.")
    if shard_mode not in {"size", "samples"}:
        raise ValueError("shard_mode must be 'size' or 'samples'.")
    if not repo_id:
        raise ValueError("repo_id is required.")
    if not json_path.is_file():
        raise FileNotFoundError(f"Dataset JSON does not exist: {json_path}")

    try:
        from opensportslib.tools.hf_transfer import (
            create_dataset_branch_on_hf,
            create_dataset_repo_on_hf,
            dataset_repo_exists_on_hf,
            is_hf_repo_not_found_error,
            is_hf_revision_not_found_error,
            upload_dataset_as_parquet_to_hf,
            upload_dataset_inputs_from_json_to_hf,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("opensportslib is required. Install the project requirements first.") from exc

    def _upload() -> dict[str, Any]:
        if upload_format == "json":
            return upload_dataset_inputs_from_json_to_hf(
                repo_id=repo_id,
                json_path=str(json_path),
                revision=revision,
                commit_message=commit_message,
                token=token,
                progress_cb=progress_cb,
            )

        return upload_dataset_as_parquet_to_hf(
            repo_id=repo_id,
            json_path=str(json_path),
            revision=revision,
            commit_message=commit_message,
            shard_mode=shard_mode,
            shard_size=shard_size,
            token=token,
            progress_cb=progress_cb,
        )

    try:
        return _upload()
    except Exception as exc:
        error_text = str(exc)
        error_lower = error_text.lower()
        repo_missing = is_hf_repo_not_found_error(error_text)
        revision_missing = is_hf_revision_not_found_error(error_text)

        is_ambiguous_branch_case = (
            not revision_missing
            and repo_missing
            and revision.lower() != "main"
            and f"/preupload/{revision.lower()}" in error_lower
        )
        if is_ambiguous_branch_case:
            try:
                revision_missing = dataset_repo_exists_on_hf(repo_id=repo_id, token=token)
                if revision_missing:
                    repo_missing = False
            except Exception:
                pass

        if revision_missing:
            _call_progress(progress_cb, f"Branch/revision {repo_id}@{revision} was not found. Creating it...")
            create_dataset_branch_on_hf(
                repo_id=repo_id,
                branch=revision,
                source_revision="main",
                token=token,
            )
            _call_progress(progress_cb, f"Created branch {repo_id}@{revision}. Retrying upload...")
            return _upload()

        if repo_missing:
            _call_progress(progress_cb, f"Dataset repo {repo_id} was not found. Creating it...")
            create_dataset_repo_on_hf(repo_id=repo_id, token=token)
            _call_progress(progress_cb, f"Created dataset repo {repo_id}. Retrying upload...")
            return _upload()

        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload an OSL dataset JSON and its referenced inputs to a Hugging Face dataset repo.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--repo-id", required=True, help="Target dataset repo id, e.g. OpenSportsLab/my-dataset.")
    parser.add_argument("--json-path", required=True, type=Path, help="Local OSL dataset JSON path.")
    parser.add_argument("--revision", default="main", help="Target branch/revision in the dataset repo.")
    parser.add_argument(
        "--commit-message",
        default="Upload dataset inputs from JSON",
        help="Commit message for the upload.",
    )
    parser.add_argument("--token", default=None, help="Optional Hugging Face token. If omitted, local HF login is used.")
    parser.add_argument(
        "--format",
        dest="upload_format",
        choices=["json", "parquet"],
        default="json",
        help="Upload mode. JSON uploads the dataset JSON and referenced inputs; parquet uploads Parquet + WebDataset.",
    )
    parser.add_argument(
        "--shard-mode",
        choices=["size", "samples"],
        default="size",
        help="Shard grouping mode for --format parquet.",
    )
    parser.add_argument(
        "--shard-size",
        type=_parse_size,
        default=1_000_000_000,
        help="Target TAR shard size for --format parquet. Supports values like 500MB, 1GB, 1024MiB, or bytes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        result = upload_dataset_to_hf(
            repo_id=args.repo_id,
            json_path=args.json_path,
            revision=args.revision,
            commit_message=args.commit_message,
            token=args.token,
            upload_format=args.upload_format,
            shard_mode=args.shard_mode,
            shard_size=args.shard_size,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Upload complete.")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
