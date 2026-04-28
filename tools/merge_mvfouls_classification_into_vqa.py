#!/usr/bin/env python3
"""Merge MVFouls classification labels into XFoul VQA annotations."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


DUPLICATE_SUFFIX_RE = re.compile(r"__\d+$")


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


def _normalize_classification_id(sample_id: str) -> str:
    return sample_id.removeprefix("test_").removeprefix("train_").removeprefix("valid_")


def _normalize_vqa_id(sample_id: str) -> str:
    return DUPLICATE_SUFFIX_RE.sub("", sample_id)


def _classification_labels_by_id(
    classification_samples: list[dict[str, Any]],
    classification_path: Path,
) -> dict[str, dict[str, Any]]:
    labels_by_id: dict[str, dict[str, Any]] = {}

    for index, sample in enumerate(classification_samples):
        raw_id = sample.get("id")
        if not isinstance(raw_id, str) or not raw_id:
            raise ValueError(f"{classification_path} data[{index}] is missing a non-empty string 'id'.")

        normalized_id = _normalize_classification_id(raw_id)
        if normalized_id in labels_by_id:
            raise ValueError(
                f"Duplicate normalized classification id {normalized_id!r} "
                f"from source id {raw_id!r}."
            )

        labels = sample.get("labels")
        if not isinstance(labels, dict):
            raise ValueError(f"{classification_path} sample {raw_id!r} is missing object field 'labels'.")

        labels_by_id[normalized_id] = labels

    return labels_by_id


def merge_classification_into_vqa(
    classification_payload: dict[str, Any],
    vqa_payload: dict[str, Any],
    classification_path: Path,
    vqa_path: Path,
) -> tuple[dict[str, Any], dict[str, int]]:
    classification_samples = _require_data(classification_payload, classification_path)
    vqa_samples = _require_data(vqa_payload, vqa_path)

    root_labels = classification_payload.get("labels")
    if not isinstance(root_labels, dict):
        raise ValueError(f"{classification_path} is missing required object field 'labels'.")

    labels_by_id = _classification_labels_by_id(classification_samples, classification_path)
    merged_payload = copy.deepcopy(vqa_payload)
    merged_payload["labels"] = copy.deepcopy(root_labels)

    duplicate_updates = 0
    updated_samples = 0

    for index, sample in enumerate(merged_payload["data"]):
        raw_id = sample.get("id")
        if not isinstance(raw_id, str) or not raw_id:
            raise ValueError(f"{vqa_path} data[{index}] is missing a non-empty string 'id'.")

        base_id = _normalize_vqa_id(raw_id)
        labels = labels_by_id.get(base_id)
        if labels is None:
            raise ValueError(f"No classification labels found for VQA sample id {raw_id!r} (base {base_id!r}).")

        sample["labels"] = copy.deepcopy(labels)
        updated_samples += 1
        if raw_id != base_id:
            duplicate_updates += 1

    stats = {
        "classification_samples_loaded": len(classification_samples),
        "vqa_samples_updated": updated_samples,
        "duplicate_derived_updates": duplicate_updates,
    }
    return merged_payload, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy MVFouls classification labels into XFoul VQA annotation samples.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--classification-json",
        type=Path,
        default=Path("test_data/MVFouls/test/annotations_test.json"),
        help="Path to the MVFouls classification annotation JSON.",
    )
    parser.add_argument(
        "--vqa-json",
        type=Path,
        default=Path("test_data/VQA/XFoul-test/test.json"),
        help="Path to the XFoul VQA annotation JSON.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("test_data/VQA/XFoul-test/test_with_classification.json"),
        help="Path where the merged JSON should be written.",
    )
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation level for the output file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        classification_payload = _load_json(args.classification_json)
        vqa_payload = _load_json(args.vqa_json)
        merged_payload, stats = merge_classification_into_vqa(
            classification_payload,
            vqa_payload,
            args.classification_json,
            args.vqa_json,
        )

        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        with args.output_json.open("w", encoding="utf-8") as handle:
            json.dump(merged_payload, handle, indent=args.indent, ensure_ascii=False)
            handle.write("\n")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Classification samples loaded: {stats['classification_samples_loaded']}")
    print(f"VQA samples updated: {stats['vqa_samples_updated']}")
    print(f"Duplicate-derived updates: {stats['duplicate_derived_updates']}")
    print(f"Output written to: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
