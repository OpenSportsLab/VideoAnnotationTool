#!/usr/bin/env python3
"""Convert video inputs in an OSL JSON dataset to 224p copies."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


VIDEO_TYPE = "video"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _require_data(payload: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError(f"{path} is missing required list field 'data'.")

    for index, sample in enumerate(data):
        if not isinstance(sample, dict):
            raise ValueError(f"{path} data[{index}] must be a JSON object.")
    return data


def resolve_ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            return ffmpeg_path

    raise RuntimeError("Could not find FFmpeg. Install imageio-ffmpeg or make ffmpeg available on PATH.")


def _source_path_for_input(media_root: Path, input_path: str) -> Path:
    path = Path(input_path)
    if path.is_absolute():
        return path
    return media_root / path


def _relative_output_path(media_root: Path, input_path: str) -> Path:
    path = Path(input_path)
    if not path.is_absolute():
        return path

    try:
        return path.resolve().relative_to(media_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Absolute input path {input_path!r} is not under media root {media_root}.") from exc


def _ffmpeg_command(ffmpeg_executable: str, source_path: Path, output_path: Path, height: int, fps: float) -> list[str]:
    return [
        ffmpeg_executable,
        "-y",
        "-i",
        str(source_path),
        "-r",
        str(fps),
        "-vf",
        f"scale=-2:{height}",
        str(output_path),
    ]


def convert_dataset_videos_to_224p(
    payload: dict[str, Any],
    *,
    json_path: Path,
    media_root: Path,
    output_json_path: Path,
    output_media_root: Path,
    height: int = 224,
    fps: float = 25,
    overwrite: bool = False,
    missing_policy: str = "raise",
    dry_run: bool = False,
    ffmpeg_executable: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if height <= 0:
        raise ValueError("--height must be greater than 0.")
    if fps <= 0:
        raise ValueError("--fps must be greater than 0.")
    if missing_policy not in {"raise", "skip"}:
        raise ValueError("--missing-policy must be 'raise' or 'skip'.")
    if output_json_path.exists() and not overwrite and not dry_run:
        raise FileExistsError(f"Output JSON already exists: {output_json_path}")

    data = _require_data(payload, json_path)
    converted_payload = copy.deepcopy(payload)
    converted_data = converted_payload["data"]

    stats: dict[str, Any] = {
        "video_inputs_found": 0,
        "videos_converted": 0,
        "videos_skipped_missing": 0,
        "videos_failed": 0,
        "failed_conversions": [],
        "planned_outputs": [],
    }
    conversion_jobs: list[tuple[Path, Path]] = []

    for sample_index, sample in enumerate(data):
        inputs = sample.get("inputs")
        if not isinstance(inputs, list):
            continue

        converted_inputs = converted_data[sample_index].get("inputs")
        if not isinstance(converted_inputs, list):
            continue

        for input_index, input_item in enumerate(inputs):
            if not isinstance(input_item, dict):
                continue
            if input_item.get("type") != VIDEO_TYPE:
                continue

            input_path = input_item.get("path")
            if not isinstance(input_path, str) or not input_path:
                continue

            stats["video_inputs_found"] += 1
            source_path = _source_path_for_input(media_root, input_path)
            if not source_path.exists():
                if missing_policy == "skip":
                    stats["videos_skipped_missing"] += 1
                    continue
                raise FileNotFoundError(f"Missing source video: {source_path}")

            relative_output_path = _relative_output_path(media_root, input_path)
            output_path = output_media_root / relative_output_path
            if output_path.exists() and not overwrite and not dry_run:
                raise FileExistsError(f"Output video already exists: {output_path}")

            converted_inputs[input_index]["path"] = relative_output_path.as_posix()
            stats["planned_outputs"].append(str(output_path))
            conversion_jobs.append((source_path, output_path))

    if dry_run:
        return converted_payload, stats

    if conversion_jobs:
        ffmpeg = ffmpeg_executable or resolve_ffmpeg_executable()
        for source_path, output_path in conversion_jobs:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            command = _ffmpeg_command(ffmpeg, source_path, output_path, height, fps)
            try:
                subprocess.run(command, check=True)
            except subprocess.CalledProcessError as exc:
                stats["videos_failed"] += 1
                stats["failed_conversions"].append(
                    {
                        "source": str(source_path),
                        "output": str(output_path),
                        "returncode": exc.returncode,
                    }
                )
                if output_path.exists():
                    output_path.unlink()
                continue
            else:
                stats["videos_converted"] += 1

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    with output_json_path.open("w", encoding="utf-8") as handle:
        json.dump(converted_payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    return converted_payload, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert every video input in an OSL JSON dataset to 224p while preserving aspect ratio.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("json_path", type=Path, help="Path to the source OSL JSON annotation file.")
    parser.add_argument("media_root", type=Path, help="Root directory containing files referenced in inputs[].path.")
    parser.add_argument("output_json_path", type=Path, help="Path where the converted dataset JSON should be written.")
    parser.add_argument("output_media_root", type=Path, help="Root directory for converted video files.")
    parser.add_argument("--height", type=int, default=224, help="Target output video height.")
    parser.add_argument("--fps", type=float, default=25, help="Forced output frame rate.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output JSON and video files.")
    parser.add_argument(
        "--missing-policy",
        choices=["raise", "skip"],
        default="raise",
        help="Action when a referenced source video is missing.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned conversions without writing outputs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        payload = _load_json(args.json_path)
        _, stats = convert_dataset_videos_to_224p(
            payload,
            json_path=args.json_path,
            media_root=args.media_root,
            output_json_path=args.output_json_path,
            output_media_root=args.output_media_root,
            height=args.height,
            fps=args.fps,
            overwrite=args.overwrite,
            missing_policy=args.missing_policy,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Video inputs found: {stats['video_inputs_found']}")
    print(f"Videos converted: {stats['videos_converted']}")
    print(f"Missing videos skipped: {stats['videos_skipped_missing']}")
    print(f"Videos failed: {stats['videos_failed']}")
    if args.dry_run:
        print("Planned outputs:")
        for output_path in stats["planned_outputs"]:
            print(f"  {output_path}")
    else:
        print(f"Output JSON written to: {args.output_json_path}")
        print(f"Output media root: {args.output_media_root}")
    if stats["failed_conversions"]:
        print("Failed conversions:")
        for failed in stats["failed_conversions"]:
            print(
                f"  source={failed['source']} output={failed['output']} "
                f"returncode={failed['returncode']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
