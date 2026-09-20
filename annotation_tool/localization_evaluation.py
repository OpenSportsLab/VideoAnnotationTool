"""Read-only localization head evaluation using OpenSportsLib spotting AP."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt6.QtCore import QThread, pyqtSignal

from localization_confidence import numeric_localization_confidence


TIGHT_TOLERANCES_MS = (1000, 2000, 3000, 4000, 5000)
LOOSE_TOLERANCES_MS = tuple(range(5000, 60001, 5000))
DEFAULT_TOLERANCES_MS = TIGHT_TOLERANCES_MS


@dataclass(frozen=True)
class EvaluationSegment:
    key: str
    sample_id: str
    events: tuple[dict, ...]


def _position_ms(event: dict, sample_id: str) -> int:
    try:
        raw = float(event["position_ms"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"A localization event in sample {sample_id!r} has no valid position_ms.") from None
    if not math.isfinite(raw) or raw < 0:
        raise ValueError(f"A localization event in sample {sample_id!r} has no valid position_ms.")
    return int(round(raw))


def eligible_segments(
    samples: list[dict], scope: str, selected_sample_id: str, heads: tuple[str, str]
) -> tuple[list[EvaluationSegment], int]:
    """Return verified logical segments and number of skipped samples."""
    if scope not in {"project", "selected"}:
        raise ValueError("Choose a valid evaluation scope.")
    if scope == "selected" and not selected_sample_id:
        raise ValueError("Select a sample before evaluating the selected sample.")
    segments = []
    skipped = 0
    found_selected = False
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        sample_id = str(sample.get("id") or "")
        if scope == "selected" and sample_id != selected_sample_id:
            continue
        found_selected = True
        metadata = sample.get("metadata") if isinstance(sample.get("metadata"), dict) else {}
        status = metadata.get("annotation_status", sample.get("annotation_status", "verified"))
        if status not in {"verified", "unlabeled", "excluded"}:
            raise ValueError(f"Sample {sample_id!r} has unknown annotation_status {status!r}.")
        if status != "verified":
            skipped += 1
            continue
        events = tuple(
            event for event in (sample.get("events") or [])
            if isinstance(event, dict) and event.get("head") in heads
        )
        if any(not str(event.get("label") or "").strip() for event in events):
            raise ValueError(
                f"A localization event in sample {sample_id!r} has no label in a selected head."
            )
        intervals = metadata.get("intervals", sample.get("intervals"))
        if intervals is None:
            segments.append(EvaluationSegment(sample_id, sample_id, events))
            continue
        if not isinstance(intervals, list) or not intervals:
            raise ValueError(f"Sample {sample_id!r} has no valid evaluation intervals.")
        previous_end = -1
        assigned_events = 0
        for index, interval in enumerate(intervals):
            if not isinstance(interval, dict):
                raise ValueError(f"Sample {sample_id!r} has an invalid interval.")
            try:
                start = int(interval["start_time_ms"])
                end = int(interval["end_time_ms"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"Sample {sample_id!r} has an invalid interval.") from None
            if start < 0 or end <= start or start < previous_end:
                raise ValueError(f"Sample {sample_id!r} has overlapping or invalid intervals.")
            previous_end = end
            interval_events = tuple(
                event for event in events
                if start <= _position_ms(event, sample_id) < end
            )
            assigned_events += len(interval_events)
            segments.append(EvaluationSegment(
                f"{sample_id}::interval-{index + 1}", sample_id, interval_events
            ))
        if assigned_events != len(events):
            raise ValueError(
                f"{len(events) - assigned_events} localization event(s) in sample "
                f"{sample_id!r} fall outside its declared intervals."
            )
    if scope == "selected" and not found_selected:
        raise ValueError("The selected sample is no longer in this project.")
    return segments, skipped


def observed_labels(segments: list[EvaluationSegment], head: str) -> set[str]:
    return {
        str(event.get("label") or "").strip()
        for segment in segments
        for event in segment.events
        if event.get("head") == head and str(event.get("label") or "").strip()
    }


def _curve_average(values: list[float]) -> float:
    if len(values) == 1:
        return values[0]
    return sum((left + right) / 2.0 for left, right in zip(values, values[1:])) / (len(values) - 1)


def evaluate_localization_heads(
    samples: list[dict], *, scope: str, selected_sample_id: str,
    truth_head: str, prediction_head: str, mapping: dict[str, str],
    tolerances_ms: tuple[int, ...], truth_labels: tuple[str, ...],
    should_cancel=None,
) -> dict:
    """Score a snapshot; no project or model state is changed."""
    if not truth_head or not prediction_head or truth_head == prediction_head:
        raise ValueError("Choose two different localization heads.")
    custom = tuple(sorted(set(int(value) for value in tolerances_ms)))
    if not custom or custom[0] < 0 or custom[-1] > 60000 or any(value % 100 for value in custom):
        raise ValueError("Choose at least one tolerance between 0.0 and 60.0 seconds in 0.1-second steps.")
    segments, skipped_samples = eligible_segments(
        samples, scope, selected_sample_id, (truth_head, prediction_head)
    )
    if not segments:
        raise ValueError("No verified samples or intervals are available for evaluation.")
    observed_predictions = observed_labels(segments, prediction_head)
    if set(mapping) != observed_predictions or any(not target for target in mapping.values()):
        raise ValueError("Map every observed prediction label to a ground-truth label.")
    available_truth_labels = {
        str(label).strip() for label in truth_labels if str(label).strip()
    } | observed_labels(segments, truth_head)
    if any(target not in available_truth_labels for target in mapping.values()):
        raise ValueError("A prediction label is mapped outside the ground-truth head.")

    truth, pred = [], []
    truth_count = prediction_count = 0
    for segment in segments:
        if should_cancel is not None and should_cancel():
            raise InterruptedError("Evaluation cancelled.")
        truth_events, pred_events = [], []
        for event in segment.events:
            label = str(event.get("label") or "").strip()
            position = _position_ms(event, segment.key)
            if event.get("head") == truth_head:
                truth_events.append({"label": label, "frame": position})
                truth_count += 1
            elif event.get("head") == prediction_head:
                confidence = numeric_localization_confidence(event)
                pred_events.append({
                    "label": mapping[label], "frame": position,
                    "confidence": 1.0 if confidence is None else confidence,
                })
                prediction_count += 1
        truth.append({"path": segment.key, "events": truth_events})
        pred.append({"video": segment.key, "events": pred_events})
    if not truth_count:
        raise ValueError("No ground-truth events are available in the chosen scope and head.")

    # OSL's sparse AP metric compares frame positions by subtraction only, so
    # millisecond positions can be used directly with millisecond tolerances.
    from opensportslib.metrics.localization_metric import (
        compute_average_precision, get_predictions, parse_ground_truth,
    )

    truth_by_label = parse_ground_truth(truth)
    all_tolerances = sorted(set(TIGHT_TOLERANCES_MS) | set(LOOSE_TOLERANCES_MS) | set(custom))
    per_class = {}
    for label in sorted(available_truth_labels):
        if should_cancel is not None and should_cancel():
            raise InterruptedError("Evaluation cancelled.")
        if label not in truth_by_label:
            per_class[label] = None
            continue
        predictions = get_predictions(pred, label=label)
        per_class[label] = {}
        for tolerance in all_tolerances:
            if should_cancel is not None and should_cancel():
                raise InterruptedError("Evaluation cancelled.")
            per_class[label][tolerance] = float(compute_average_precision(
                predictions, truth_by_label[label], tolerance=tolerance
            ))
    defined = [values for values in per_class.values() if values is not None]
    mean_by_tolerance = {
        tolerance: sum(values[tolerance] for values in defined) / len(defined)
        for tolerance in all_tolerances
    }

    def display_metrics(values):
        return {
            "tight": _curve_average([values[t] for t in TIGHT_TOLERANCES_MS]),
            "loose": _curve_average([values[t] for t in LOOSE_TOLERANCES_MS]),
            "ap": {t: values[t] for t in custom},
        }
    return {
        "overall": display_metrics(mean_by_tolerance),
        "classes": {
            label: display_metrics(values) if values is not None else None
            for label, values in per_class.items()
        },
        "tolerances_ms": custom,
        "segment_count": len(segments),
        "sample_count": len({segment.sample_id for segment in segments}),
        "skipped_samples": skipped_samples,
        "truth_count": truth_count,
        "prediction_count": prediction_count,
    }


class LocalizationEvaluationWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, samples: list[dict], options: dict):
        super().__init__()
        self.samples = samples
        self.options = options

    def run(self):
        try:
            self.completed.emit(evaluate_localization_heads(
                self.samples, **self.options, should_cancel=self.isInterruptionRequested
            ))
        except Exception as exc:
            self.failed.emit(str(exc))
