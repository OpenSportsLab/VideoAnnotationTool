import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from opensportslib.tools.hf_transfer import download_dataset_split_from_hf


def main(
    repo_id: str,
    revision: str,
    split: str,
    output_dir: str = "downloaded_data",
    download_format: str = "parquet",
    dry_run: bool = False,
    token: str | None = None,
) -> None:
    result = download_dataset_split_from_hf(
        repo_id,
        revision,
        split,
        output_dir,
        download_format=download_format,
        dry_run=dry_run,
        token=token,
        progress_cb=lambda msg: print(f"[HF] {msg}"),
    )

    print(f"Repo: {result['repo_id']} @ {result['revision']}")
    print(f"JSON path: {result['json_path']}")
    print(f"Matched files: {result['referenced_file_count']}")

    if dry_run:
        print("Running in DRY-RUN mode (no files downloaded).")
        files = result.get("files", [])
        for file_info in files:
            print(f"[DRY RUN] Repo file : {file_info['repo_path']} ({file_info['size_human']})")
            print(f"[DRY RUN] Local path: {file_info['local_path']}")

        print("-" * 48)
        print(f"Total estimated storage needed: {result.get('estimated_total_size_human', '0.0 B')}")
        missing = result.get("missing_files", [])
        if missing:
            print(f"WARNING: {len(missing)} files not found in repo metadata.")
            for path in missing[:50]:
                print(f"  - {path}")
            if len(missing) > 50:
                print(f"  ... and {len(missing) - 50} more")
        return

    print(
        f"Done. Downloaded {result.get('downloaded_file_count', 0)} files to: "
        f"{os.path.abspath(result['output_dir'])}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download an OSL dataset split from a Hugging Face dataset repo."
    )
    parser.add_argument(
        "--repo-id",
        required=True,
        help="Dataset repo id, e.g. OpenSportsLab/OSL-XFoul.",
    )
    parser.add_argument(
        "--revision",
        required=True,
        help="Dataset branch/revision.",
    )
    parser.add_argument(
        "--split",
        required=True,
        help="Dataset split/artifact name. JSON mode downloads <split>.json; parquet mode downloads <split>/.",
    )
    parser.add_argument(
        "--output-dir",
        default="downloaded_data",
        help="Root directory for downloads. Files are stored under <output-dir>/<revision>/<split>.",
    )
    parser.add_argument("--format", choices=["json", "parquet"], default="parquet", help="Download format.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files without downloading them and estimate storage size.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional Hugging Face token override. If omitted, local HF login is used.",
    )

    args = parser.parse_args()
    main(
        repo_id=args.repo_id,
        revision=args.revision,
        split=args.split,
        output_dir=args.output_dir,
        download_format=args.format,
        dry_run=args.dry_run,
        token=args.token,
    )
