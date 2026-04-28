#!/usr/bin/env python3
"""Convert legacy OSL VQA JSON into grouped per-sample VQA answers."""

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


def _question_text_by_id(payload: dict[str, Any]) -> dict[str, str]:
    question_by_id: dict[str, str] = {}
    for entry in list(payload.get("questions") or []):
        if not isinstance(entry, dict):
            continue
        question_id = str(entry.get("id") or "").strip()
        question_text = str(entry.get("question") or "").strip()
        if question_id and question_text and question_id not in question_by_id:
            question_by_id[question_id] = question_text
    return question_by_id


def _base_sample_id(sample_id: str) -> str:
    return DUPLICATE_SUFFIX_RE.sub("", sample_id)


def _sample_without_answers(sample: dict[str, Any], sample_id: str) -> dict[str, Any]:
    copied = copy.deepcopy(sample)
    copied["id"] = sample_id
    copied.pop("answers", None)
    return copied


def _append_grouped_answer(
    groups: list[dict[str, Any]],
    index_by_question: dict[str, int],
    question: str,
    answer: str,
) -> None:
    question = str(question or "").strip()
    answer = str(answer or "").strip()
    if not question or not answer:
        return

    group_index = index_by_question.get(question)
    if group_index is None:
        index_by_question[question] = len(groups)
        groups.append({"question": question, "answers": [answer]})
    else:
        groups[group_index]["answers"].append(answer)


def convert_legacy_vqa_to_grouped(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(payload.get("data"), list):
        raise ValueError("Input JSON is missing required list field 'data'.")

    question_by_id = _question_text_by_id(payload)
    output = copy.deepcopy(payload)
    output.pop("questions", None)
    output["data"] = []

    samples_by_base_id: dict[str, dict[str, Any]] = {}
    groups_by_base_id: dict[str, list[dict[str, Any]]] = {}
    group_index_by_base_id: dict[str, dict[str, int]] = {}
    warnings: list[str] = []

    for index, sample in enumerate(payload["data"]):
        if not isinstance(sample, dict):
            warnings.append(f"Skipping non-object data[{index}].")
            continue

        raw_id = str(sample.get("id") or f"sample_{index + 1}").strip()
        base_id = _base_sample_id(raw_id)
        canonical_sample = _sample_without_answers(sample, base_id)

        if base_id not in samples_by_base_id:
            samples_by_base_id[base_id] = canonical_sample
            groups_by_base_id[base_id] = []
            group_index_by_base_id[base_id] = {}
        elif samples_by_base_id[base_id] != canonical_sample:
            warnings.append(
                f"Keeping first non-QA fields for duplicate sample {raw_id!r} "
                f"(base {base_id!r})."
            )

        groups = groups_by_base_id[base_id]
        index_by_question = group_index_by_base_id[base_id]
        for answer_entry in list(sample.get("answers") or []):
            if not isinstance(answer_entry, dict):
                continue

            if "question_id" in answer_entry:
                question_id = str(answer_entry.get("question_id") or "").strip()
                question = question_by_id.get(question_id)
                if not question:
                    warnings.append(
                        f"Skipping answer for sample {raw_id!r}: unknown question_id {question_id!r}."
                    )
                    continue
                _append_grouped_answer(
                    groups,
                    index_by_question,
                    question,
                    str(answer_entry.get("answer") or ""),
                )
                continue

            question = str(answer_entry.get("question") or "").strip()
            for answer in list(answer_entry.get("answers") or []):
                _append_grouped_answer(groups, index_by_question, question, str(answer or ""))

    for base_id, sample in samples_by_base_id.items():
        grouped_sample = copy.deepcopy(sample)
        groups = groups_by_base_id.get(base_id, [])
        if groups:
            grouped_sample["answers"] = copy.deepcopy(groups)
        output["data"].append(grouped_sample)

    return output, warnings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert legacy OSL VQA question_id files to grouped per-sample answers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--input-json", required=True, type=Path, help="Path to the legacy VQA JSON.")
    parser.add_argument("--output-json", required=True, type=Path, help="Path to write grouped VQA JSON.")
    parser.add_argument("--indent", default=2, type=int, help="JSON indentation level.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        payload = _load_json(args.input_json)
        converted, warnings = convert_legacy_vqa_to_grouped(payload)
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        with args.output_json.open("w", encoding="utf-8") as handle:
            json.dump(converted, handle, indent=args.indent, ensure_ascii=False)
            handle.write("\n")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"[WARN] {warning}", file=sys.stderr)
    print(f"[INFO] Wrote grouped VQA JSON: {args.output_json}")
    print(f"[INFO] Samples={len(converted.get('data', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
