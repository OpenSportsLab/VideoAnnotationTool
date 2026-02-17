import os
import json
import argparse
from urllib.parse import urlparse
from huggingface_hub import hf_hub_download, snapshot_download, HfApi


def human_size(num: int) -> str:
    """Convert a file size in bytes to a human-readable string (B, KB, MB, GB, TB)."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def fix_hf_url(hf_url: str) -> str:
    """Convert a HuggingFace 'blob' URL to a 'resolve' URL for direct download."""
    return hf_url.replace("/blob/", "/resolve/")


def parse_hf_url(hf_url: str):
    """
    Parse a Hugging Face dataset file URL (supports 'blob' or 'resolve' forms).
    Returns (repo_id, revision, path_in_repo).
    Example:
      https://huggingface.co/datasets/ORG/REPO/blob/main/annotations_test.json
      -> repo_id="ORG/REPO", revision="main", path_in_repo="annotations_test.json"
    """
    url = fix_hf_url(hf_url)
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")

    # Remove leading "datasets" if present
    if "datasets" in parts:
        datasets_idx = parts.index("datasets")
        parts = parts[datasets_idx + 1 :]

    # Expected: ORG / REPO / resolve / REVISION / <path...>
    if len(parts) < 5 or parts[2] != "resolve":
        raise ValueError(f"URL does not look like a valid HuggingFace dataset file URL: {url}")

    repo_id = f"{parts[0]}/{parts[1]}"
    revision = parts[3]
    path_in_repo = "/".join(parts[4:])

    return repo_id, revision, path_in_repo


def get_json_repo_folder(path_in_repo: str) -> str:
    """Return the folder containing the JSON inside the repo, or '' if at root."""
    folder = os.path.dirname(path_in_repo)
    return folder if folder and folder != "." else ""


def parse_types_arg(types_arg: str):
    """
    Parse --types argument.
    - "all" means include any input that has a "path".
    - Otherwise it's a comma-separated list of input types (e.g. "video,captions,features").
    """
    types_arg = (types_arg or "video").strip().lower()
    if types_arg in ("all", "*"):
        return "all"
    return {t.strip() for t in types_arg.split(",") if t.strip()}


def extract_repo_paths_from_json(osl_json: dict, want_types):
    """
    Extract file paths from different OSL / SoccerNetPro JSON schemas.

    Supported formats:
    - videos[].path (legacy/simple)
    - data[].inputs[].path (OSL v2)
      where input has fields: {type, path, ...}

    want_types:
      - "all" -> any input with a "path"
      - set(...) -> only inputs whose inp["type"] is in the set
    """
    repo_paths = []

    # Legacy/simple format
    if "videos" in osl_json and isinstance(osl_json.get("videos"), list):
        # Only include if caller wants videos
        if want_types == "all" or ("video" in want_types):
            for v in osl_json.get("videos", []):
                if isinstance(v, dict) and "path" in v:
                    repo_paths.append(str(v["path"]).lstrip("/"))

    # OSL v2 format
    if "data" in osl_json and isinstance(osl_json.get("data"), list):
        for item in osl_json.get("data", []):
            for inp in item.get("inputs", []):
                if not isinstance(inp, dict):
                    continue
                p = inp.get("path")
                if not p:
                    continue
                inp_type = str(inp.get("type", "")).strip().lower()

                if want_types == "all":
                    repo_paths.append(str(p).lstrip("/"))
                else:
                    if inp_type in want_types:
                        repo_paths.append(str(p).lstrip("/"))

    if not repo_paths:
        if want_types == "all":
            raise ValueError("No file paths found in the provided JSON (no inputs with 'path').")
        else:
            raise ValueError(
                f"No matching file paths found for requested types={sorted(list(want_types))}. "
                "Check your JSON schema and --types."
            )

    return repo_paths


def main(osl_json_url: str, output_dir: str = "downloaded_data", dry_run: bool = False, types_arg: str = "video"):
    api = HfApi()
    want_types = parse_types_arg(types_arg)

    # Parse HuggingFace URL
    repo_id, revision, path_in_repo = parse_hf_url(osl_json_url)
    repo_json_folder = get_json_repo_folder(path_in_repo)

    print(f"⬇️  Downloading JSON from {repo_id}@{revision}: {path_in_repo}")
    os.makedirs(output_dir, exist_ok=True)

    # Download JSON itself
    hf_json_path = hf_hub_download(
        repo_id=repo_id,
        repo_type="dataset",
        filename=path_in_repo,
        revision=revision,
        local_dir=output_dir,
        local_dir_use_symlinks=False,
    )
    print(f"  → Saved as: {hf_json_path}")

    # Load JSON
    with open(hf_json_path, "r", encoding="utf-8") as f:
        osl = json.load(f)

    # Extract repo paths (schema-aware)
    repo_paths = extract_repo_paths_from_json(osl, want_types)
    print(f"Found {len(repo_paths)} referenced files for types={types_arg}.")

    # If JSON file lives in a repo subfolder, some inputs may be relative to that folder.
    # We keep your original behavior: if path doesn't start with repo_json_folder, prefix it.
    def repo_full_path(rel_path: str) -> str:
        rel_path = rel_path.lstrip("/")
        if repo_json_folder:
            prefix = repo_json_folder.rstrip("/") + "/"
            if not rel_path.startswith(prefix):
                return prefix + rel_path
        return rel_path

    allow_patterns = sorted(set(repo_full_path(p) for p in repo_paths))

    if dry_run:
        print("Running in DRY-RUN mode (no files will be downloaded).")

        # Fetch file sizes via repo metadata (best effort)
        try:
            info_obj = api.repo_info(
                repo_id=repo_id,
                revision=revision,
                repo_type="dataset",
                files_metadata=True,
            )
            size_lookup = {f.rfilename: f.size for f in info_obj.siblings}
        except Exception as e:
            print(f"[ERROR] Could not fetch repo file metadata: {e}")
            size_lookup = {}

        total_size = 0
        missing_files = []

        for full_repo_path in allow_patterns:
            local_path = os.path.join(output_dir, full_repo_path)
            size = size_lookup.get(full_repo_path)

            if size is not None:
                size_str = human_size(size)
                total_size += size
            else:
                size_str = "Not found"
                missing_files.append(full_repo_path)

            print(f"[DRY RUN] Repo file : {full_repo_path} ({size_str})")
            print(f"[DRY RUN] Local path: {local_path}")

        print("-" * 48)
        print(f"Total estimated storage needed: {human_size(total_size)}")

        if missing_files:
            print(f"WARNING: {len(missing_files)} files not found in repo metadata:")
            for f in missing_files[:50]:
                print(f"  - {f}")
            if len(missing_files) > 50:
                print(f"  ... and {len(missing_files) - 50} more")

    else:
        print(f"Downloading {len(allow_patterns)} files using snapshot_download...")
        snapshot_download(
            repo_id=repo_id,
            repo_type="dataset",
            revision=revision,
            local_dir=output_dir,
            allow_patterns=allow_patterns,
            max_workers=8,
        )
        print(f"✅ Done. All requested files downloaded to: {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download files referenced in an OSL JSON from Hugging Face (dataset repo)."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="URL of the OSL JSON file on Hugging Face (blob/resolve both supported)",
    )
    parser.add_argument(
        "--output-dir",
        default="downloaded_data",
        help="Directory to store downloaded files",
    )
    parser.add_argument(
        "--types",
        default="video",
        help=(
            "Comma-separated input types to download from item.inputs (e.g. 'video', 'video,captions', "
            "'video,captions,features'), or 'all' to download all inputs with a path. Default: video"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files to download without downloading them (estimates total size if possible).",
    )

    args = parser.parse_args()
    main(args.url, args.output_dir, dry_run=args.dry_run, types_arg=args.types)
