#!/usr/bin/env python3
"""Merge multiple OSL JSON datasets covering the same samples into one.

Matches samples across N source datasets by a configurable id field (e.g.
``game_id``), concatenates their ``inputs`` lists, merges every other
(non-structural) sample field as annotation content under a selectable
strategy, and copies the referenced media files into a shared output media
root.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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


def _source_path_for_input(media_root: Path, input_path: str) -> Path:
    path = Path(input_path)
    if path.is_absolute():
        return path
    return media_root / path


@dataclass
class SourceData:
    json_path: Path
    media_root: Path
    payload: dict[str, Any]
    order: list[Any]
    samples_by_id: dict[Any, dict[str, Any]]


@dataclass
class MergeResult:
    payload: dict[str, Any]
    stats: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    files_to_copy: list[tuple[Path, Path]] = field(default_factory=list)


def load_source(json_path: Path, media_root: Path, id_field: str) -> SourceData:
    payload = _load_json(json_path)
    data = _require_data(payload, json_path)

    order: list[Any] = []
    samples_by_id: dict[Any, dict[str, Any]] = {}
    for index, sample in enumerate(data):
        sample_id = sample.get(id_field)
        if sample_id is None:
            raise ValueError(f"{json_path} data[{index}] is missing required field {id_field!r}.")
        if sample_id in samples_by_id:
            raise ValueError(f"{json_path} has duplicate {id_field!r} value {sample_id!r}.")
        samples_by_id[sample_id] = sample
        order.append(sample_id)

    return SourceData(json_path=json_path, media_root=media_root, payload=payload, order=order, samples_by_id=samples_by_id)


def _merge_field_values(
    values: list[tuple[int, Any]],
    mode: str,
    primary_input: int,
) -> tuple[Any, bool, int]:
    """Merge one annotation field's per-source values.

    Returns (merged_value, all_equal, chosen_source_index_if_first_mode).
    """
    all_equal = all(v == values[0][1] for _, v in values)

    def pick_primary() -> tuple[Any, int]:
        for source_index, value in values:
            if source_index == primary_input:
                return value, source_index
        return values[0][1], values[0][0]

    if all(isinstance(v, list) for _, v in values):
        if mode == "concat":
            merged: list[Any] = []
            for _, value in values:
                merged.extend(value)
            return merged, all_equal, -1
        if mode == "dedup":
            merged = []
            for _, value in values:
                for item in value:
                    if item not in merged:
                        merged.append(item)
            return merged, all_equal, -1
        chosen_value, chosen_index = pick_primary()
        return copy.deepcopy(chosen_value), all_equal, chosen_index

    chosen_value, chosen_index = pick_primary()
    return copy.deepcopy(chosen_value), all_equal, chosen_index


def merge_datasets(
    sources: list[SourceData],
    id_field: str,
    non_annotation_fields: set[str],
    annotation_mode: str,
    annotation_primary_input: int,
    on_id_mismatch: str,
    dataset_name_override: str | None,
) -> MergeResult:
    if len(sources) < 2:
        raise ValueError("At least two --input sources are required.")
    if not (0 <= annotation_primary_input < len(sources)):
        raise ValueError(f"--annotation-primary-input must be in [0, {len(sources) - 1}].")

    struct_fields = set(non_annotation_fields) | {id_field}
    struct_fields.discard("inputs")

    ids_per_source = [set(source.samples_by_id) for source in sources]
    all_ids = set().union(*ids_per_source)
    common_ids = set.intersection(*ids_per_source)
    mismatched_ids = all_ids - common_ids

    warnings: list[str] = []
    if mismatched_ids:
        if on_id_mismatch == "error":
            details = []
            for sample_id in sorted(mismatched_ids, key=str):
                missing_from = [str(s.json_path) for s, ids in zip(sources, ids_per_source) if sample_id not in ids]
                details.append(f"  {sample_id!r} missing from: {', '.join(missing_from)}")
            raise ValueError("Sample IDs differ across sources (use --on-id-mismatch intersect/union):\n" + "\n".join(details))
        if on_id_mismatch == "intersect":
            for sample_id in sorted(mismatched_ids, key=str):
                missing_from = [str(s.json_path) for s, ids in zip(sources, ids_per_source) if sample_id not in ids]
                warnings.append(f"Dropped id {sample_id!r} (missing from: {', '.join(missing_from)}).")
        else:  # union
            for sample_id in sorted(mismatched_ids, key=str):
                present_in = [str(s.json_path) for s, ids in zip(sources, ids_per_source) if sample_id in ids]
                warnings.append(f"Partially sourced id {sample_id!r} (present only in: {', '.join(present_in)}).")

    merge_ids = common_ids if on_id_mismatch == "intersect" else all_ids

    ordered_ids: list[Any] = []
    seen_ids: set[Any] = set()
    for source in sources:
        for sample_id in source.order:
            if sample_id in merge_ids and sample_id not in seen_ids:
                ordered_ids.append(sample_id)
                seen_ids.add(sample_id)

    files_to_copy: dict[str, Path] = {}
    files_to_copy_list: list[tuple[Path, Path]] = []
    merged_data: list[dict[str, Any]] = []
    field_all_equal_globally: dict[str, bool] = {}
    samples_with_mismatch: set[Any] = set()

    for sample_id in ordered_ids:
        present = [(i, s.samples_by_id[sample_id]) for i, s in enumerate(sources) if sample_id in s.samples_by_id]
        merged_sample: dict[str, Any] = {}

        for f in struct_fields:
            vals = [(i, smp[f]) for i, smp in present if f in smp]
            if not vals:
                continue
            first_value = vals[0][1]
            mismatched_vals = [v for _, v in vals if v != first_value]
            if mismatched_vals:
                raise ValueError(f"Sample {sample_id!r} field {f!r} differs across sources: {[v for _, v in vals]!r}")
            merged_sample[f] = copy.deepcopy(first_value)

        merged_inputs: list[Any] = []
        for source_index, smp in present:
            for input_entry in smp.get("inputs", []):
                merged_inputs.append(copy.deepcopy(input_entry))
                input_path = input_entry.get("path")
                if not input_path:
                    continue
                src_abs = _source_path_for_input(sources[source_index].media_root, input_path)
                dst_rel = str(Path(input_path))
                if dst_rel in files_to_copy and files_to_copy[dst_rel] != src_abs:
                    raise ValueError(
                        f"Output media path collision for {dst_rel!r}: "
                        f"{files_to_copy[dst_rel]} vs {src_abs}"
                    )
                if dst_rel not in files_to_copy:
                    files_to_copy[dst_rel] = src_abs
                    files_to_copy_list.append((src_abs, Path(dst_rel)))
        merged_sample["inputs"] = merged_inputs

        ann_field_names: list[str] = []
        for _, smp in present:
            for key in smp:
                if key in struct_fields or key == "inputs" or key in ann_field_names:
                    continue
                ann_field_names.append(key)

        for f in ann_field_names:
            vals = [(i, smp[f]) for i, smp in present if f in smp]
            merged_value, all_equal, chosen_index = _merge_field_values(vals, annotation_mode, annotation_primary_input)
            merged_sample[f] = merged_value

            field_all_equal_globally[f] = field_all_equal_globally.get(f, True) and all_equal
            if not all_equal:
                samples_with_mismatch.add(sample_id)
                if len(vals) > 1 and not isinstance(merged_value, list):
                    warnings.append(
                        f"Sample {sample_id!r} field {f!r} values differ across sources; "
                        f"used source {chosen_index} ({sources[chosen_index].json_path})."
                    )
            if annotation_mode == "first" and vals and vals[0][0] != annotation_primary_input:
                present_indices = {i for i, _ in vals}
                if annotation_primary_input not in present_indices:
                    warnings.append(
                        f"Sample {sample_id!r} field {f!r}: primary input {annotation_primary_input} "
                        f"missing this field; used source {chosen_index} instead."
                    )

        merged_data.append(merged_sample)

    base = sources[0].payload
    base_labels = base.get("labels")
    for source in sources[1:]:
        if source.payload.get("labels") != base_labels:
            raise ValueError(f"'labels' differ between {sources[0].json_path} and {source.json_path}.")

    merged_payload: dict[str, Any] = {
        key: copy.deepcopy(value)
        for key, value in base.items()
        if key not in {"data", "metadata", "dataset_name"}
    }
    merged_payload["labels"] = copy.deepcopy(base_labels)

    metadata = copy.deepcopy(base.get("metadata", {}))
    if "modality" in metadata:
        parts = [str(s.payload.get("metadata", {}).get("modality", "")) for s in sources]
        metadata["modality"] = "+".join(p for p in parts if p)
    for f, all_equal in field_all_equal_globally.items():
        key = f"{f}_identical_across_modalities"
        if key in metadata:
            metadata[key] = all_equal
    merged_payload["metadata"] = metadata

    merged_payload["dataset_name"] = dataset_name_override or "+".join(
        str(s.payload.get("dataset_name", s.json_path.stem)) for s in sources
    )
    merged_payload["data"] = merged_data

    stats = {
        "sources": [str(s.json_path) for s in sources],
        "samples_merged": len(merged_data),
        "ids_dropped": sorted((all_ids - merge_ids), key=str) if on_id_mismatch == "intersect" else [],
        "files_to_copy": len(files_to_copy_list),
        "samples_with_annotation_mismatch": len(samples_with_mismatch),
    }
    return MergeResult(payload=merged_payload, stats=stats, warnings=warnings, files_to_copy=files_to_copy_list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge multiple OSL JSON datasets covering the same samples into one, "
        "combining inputs and annotation fields and copying referenced media.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        nargs=2,
        action="append",
        metavar=("JSON_PATH", "MEDIA_ROOT"),
        required=True,
        help="Source dataset JSON path and its media root (repeat for each source, order preserved).",
    )
    parser.add_argument("--output-json", type=Path, required=True, help="Destination path for the merged JSON.")
    parser.add_argument("--output-media-root", type=Path, required=True, help="Destination root for copied media files.")
    parser.add_argument("--id-field", default="game_id", help="Sample field used to match samples across sources.")
    parser.add_argument("--dataset-name", default=None, help="Override for the merged dataset's 'dataset_name'.")
    parser.add_argument(
        "--on-id-mismatch",
        choices=["error", "intersect", "union"],
        default="error",
        help="How to handle sample ids that aren't present in every source.",
    )
    parser.add_argument(
        "--non-annotation-fields",
        default="game_id,split,inputs",
        help="Comma-separated sample fields treated as structural, not annotation content.",
    )
    parser.add_argument(
        "--annotation-mode",
        choices=["concat", "dedup", "first"],
        default="dedup",
        help="How to combine each annotation field across sources.",
    )
    parser.add_argument(
        "--annotation-primary-input",
        type=int,
        default=0,
        help="Index (0-based) into --input whose annotations are used when --annotation-mode first.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace existing output JSON/media files.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned merge/copy stats without writing anything.")
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation level for the output file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        if len(args.input) < 2:
            raise ValueError("At least two --input JSON_PATH MEDIA_ROOT pairs are required.")

        non_annotation_fields = {f.strip() for f in args.non_annotation_fields.split(",") if f.strip()}
        sources = [
            load_source(Path(json_path), Path(media_root), args.id_field)
            for json_path, media_root in args.input
        ]

        result = merge_datasets(
            sources=sources,
            id_field=args.id_field,
            non_annotation_fields=non_annotation_fields,
            annotation_mode=args.annotation_mode,
            annotation_primary_input=args.annotation_primary_input,
            on_id_mismatch=args.on_id_mismatch,
            dataset_name_override=args.dataset_name,
        )

        copied = 0
        skipped = 0
        missing: list[str] = []
        if not args.dry_run:
            for src_abs, dst_rel in result.files_to_copy:
                if not src_abs.exists():
                    missing.append(str(src_abs))
                    continue
                dst_abs = args.output_media_root / dst_rel
                if dst_abs.exists() and not args.overwrite:
                    skipped += 1
                    continue
                dst_abs.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_abs, dst_abs)
                copied += 1

            if missing:
                raise ValueError("Missing source media files:\n" + "\n".join(f"  {m}" for m in missing))

            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            if args.output_json.exists() and not args.overwrite:
                raise ValueError(f"{args.output_json} already exists (use --overwrite).")
            with args.output_json.open("w", encoding="utf-8") as handle:
                json.dump(result.payload, handle, indent=args.indent, ensure_ascii=False)
                handle.write("\n")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    print(f"Sources merged: {len(result.stats['sources'])}")
    print(f"Samples merged: {result.stats['samples_merged']}")
    if result.stats["ids_dropped"]:
        print(f"IDs dropped (intersect): {result.stats['ids_dropped']}")
    print(f"Files to copy: {result.stats['files_to_copy']}")
    if not args.dry_run:
        print(f"Files copied: {copied} (skipped existing: {skipped})")
        print(f"Output written to: {args.output_json}")
    else:
        print("Dry run: no files written.")
    if result.stats["samples_with_annotation_mismatch"]:
        print(f"Samples with annotation value mismatches: {result.stats['samples_with_annotation_mismatch']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
