"""Read-only localization head evaluation using OpenSportsLib spotting AP."""

from __future__ import annotations

import math
import os
import time
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass

from PyQt6.QtCore import QThread, pyqtSignal

from localization_confidence import numeric_localization_confidence
from utils import annotation_position_ms, earliest_h5_timestamp_utc, parse_utc_datetime


TIGHT_TOLERANCES_MS = (1000, 2000, 3000, 4000, 5000)
LOOSE_TOLERANCES_MS = tuple(range(5000, 60001, 5000))
DEFAULT_TOLERANCES_MS = TIGHT_TOLERANCES_MS
FAST_AP_COMPARISON_THRESHOLD = 2_000_000


def _fast_average_precision(predictions, truth, tolerance, should_cancel=None, on_progress=None):
    """Match OpenSportsLib's greedy spotting AP with indexed truth positions."""
    total = sum(len(frames) for frames in truth.values())
    available = {}
    for video, truth_frames in truth.items():
        first_order = {}
        for order, frame in enumerate(truth_frames):
            first_order.setdefault(frame, order)
        frames = sorted(first_order)
        size = len(frames)
        available[video] = (
            frames, [first_order[frame] for frame in frames],
            list(range(size + 2)), list(range(size + 2)),
        )

    def find(parent, position):
        root = position
        while parent[root] != root:
            root = parent[root]
        while parent[position] != position:
            next_position = parent[position]
            parent[position] = root
            position = next_position
        return root

    precision = []
    matched = 0
    previous_score = 1
    count = len(predictions)
    for index, (video, frame, score) in enumerate(predictions, 1):
        assert score <= previous_score
        previous_score = score
        if index % 256 == 1:
            if should_cancel is not None and should_cancel():
                raise InterruptedError("Evaluation cancelled.")
            if on_progress is not None:
                on_progress(index - 1, count)
        video_data = available.get(video)
        if video_data is None:
            continue
        frames, orders, next_available, previous_available = video_data
        insertion = bisect_left(frames, frame) + 1
        right = find(next_available, insertion)
        left = find(previous_available, insertion - 1)
        chosen = None
        if left:
            chosen = left
        if right <= len(frames) and (
            chosen is None
            or abs(frame - frames[right - 1]) < abs(frame - frames[chosen - 1])
            or (
                abs(frame - frames[right - 1]) == abs(frame - frames[chosen - 1])
                and orders[right - 1] < orders[chosen - 1]
            )
        ):
            chosen = right
        if chosen is not None and abs(frame - frames[chosen - 1]) <= tolerance:
            matched += 1
            precision.append(matched / index)
            next_available[chosen] = find(next_available, chosen + 1)
            previous_available[chosen] = find(previous_available, chosen - 1)
    if on_progress is not None:
        on_progress(count, count)
    best = area = 0.0
    for value in reversed(precision):
        best = max(best, value)
        area += best
    return area / total


def _osl_comparison_count(predictions, truth):
    counts = Counter(video for video, _frame, _score in predictions)
    return sum(count * len(truth.get(video, ())) for video, count in counts.items())


@dataclass(frozen=True)
class EvaluationSegment:
    key: str
    sample_id: str
    events: tuple[dict, ...]


def project_utc_events_for_evaluation(
    samples: list[dict], project_root: str, *, scope: str = "project",
    selected_sample_id: str = "", heads: tuple[str, str] = (), should_cancel=None,
    on_progress=None, h5_origin_records=None,
) -> None:
    """Project snapshot events in the worker; H5 timeline reads may be slow."""
    h5_origins = {}
    candidates = [
        sample for sample in samples
        if isinstance(sample, dict)
        and (scope != "selected" or str(sample.get("id") or "") == selected_sample_id)
    ]
    total_samples = max(1, len(candidates))
    for sample_index, sample in enumerate(candidates):
        if should_cancel is not None and should_cancel():
            raise InterruptedError("Evaluation cancelled.")
        if on_progress is not None:
            on_progress(
                int(20 * sample_index / total_samples),
                f"Preparing timelines: sample {sample_index + 1}/{len(candidates)}",
            )
        metadata = sample.get("metadata") if isinstance(sample.get("metadata"), dict) else {}
        status = metadata.get("annotation_status", sample.get("annotation_status", "verified"))
        if status in {"unlabeled", "excluded"}:
            continue
        timed_events = [
            event for event in (sample.get("events") or [])
            if isinstance(event, dict)
            and (not heads or event.get("head") in heads)
            and parse_utc_datetime(event.get("timestamp_utc")) is not None
        ]
        if not timed_events:
            continue
        origins = []
        inputs = sample.get("inputs") or []
        for input_index, input_item in enumerate(inputs):
            if not isinstance(input_item, dict):
                continue
            if "UTC_time_start" in input_item:
                origin = parse_utc_datetime(input_item.get("UTC_time_start"))
            else:
                raw_path = str(input_item.get("path") or "")
                input_type = str(input_item.get("type") or "").strip().lower()
                if not input_type and os.path.splitext(raw_path)[1].lower() in {".h5", ".hdf5"}:
                    input_type = "player_joints_h5"
                if input_type not in {"player_joints_h5", "player_centroids_h5"} or not raw_path:
                    continue
                source_path = os.path.normpath(
                    raw_path if os.path.isabs(raw_path) else os.path.join(project_root, raw_path)
                )
                if source_path not in h5_origins:
                    try:
                        if on_progress is not None:
                            on_progress(
                                int(20 * sample_index / total_samples),
                                f"Opening H5 timeline: {os.path.basename(source_path)}",
                            )

                        def file_progress(rows_done, row_count):
                            if on_progress is not None:
                                fraction = (input_index + rows_done / row_count) / max(1, len(inputs))
                                on_progress(
                                    int(20 * (sample_index + fraction) / total_samples),
                                    f"Reading H5 timestamps: {os.path.basename(source_path)} "
                                    f"({rows_done:,}/{row_count:,} rows)",
                                )

                        if os.path.isfile(source_path):
                            stat = os.stat(source_path)
                            origin_value = earliest_h5_timestamp_utc(
                                source_path, should_cancel, file_progress
                            )
                            h5_origins[source_path] = origin_value
                            if h5_origin_records is not None:
                                h5_origin_records[source_path] = (
                                    (stat.st_mtime_ns, stat.st_size), origin_value
                                )
                        else:
                            h5_origins[source_path] = None
                    except InterruptedError:
                        raise
                    except Exception:
                        h5_origins[source_path] = None
                origin = h5_origins[source_path]
            if origin is not None:
                origins.append(origin)
        if origins:
            origin = min(origins)
            for event in timed_events:
                event["position_ms"] = annotation_position_ms(event, origin)
    if on_progress is not None:
        on_progress(20, "Preparing evaluation events")


def evaluation_scope_summary(
    samples: list[dict], scope: str, selected_sample_id: str
) -> tuple[dict[str, set[str]], int, int]:
    """Collect dialog labels and counts without reading timeline files."""
    if scope not in {"project", "selected"}:
        raise ValueError("Choose a valid evaluation scope.")
    if scope == "selected" and not selected_sample_id:
        raise ValueError("Select a sample before evaluating the selected sample.")
    labels_by_head = {}
    segment_count = skipped = 0
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
        intervals = metadata.get("intervals", sample.get("intervals"))
        if intervals is not None and (not isinstance(intervals, list) or not intervals):
            raise ValueError(f"Sample {sample_id!r} has no valid evaluation intervals.")
        segment_count += len(intervals) if intervals is not None else 1
        for event in sample.get("events") or []:
            if not isinstance(event, dict):
                continue
            head = str(event.get("head") or "").strip()
            label = str(event.get("label") or "").strip()
            if head and label:
                labels_by_head.setdefault(head, set()).add(label)
    if scope == "selected" and not found_selected:
        raise ValueError("The selected sample is no longer in this project.")
    return labels_by_head, segment_count, skipped


def _position_ms(event: dict, sample_id: str) -> int:
    try:
        raw = float(event["position_ms"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"A localization event in sample {sample_id!r} has no valid position_ms.") from None
    if not math.isfinite(raw) or raw < 0:
        raise ValueError(f"A localization event in sample {sample_id!r} has no valid position_ms.")
    return int(round(raw))


def eligible_segments(
    samples: list[dict], scope: str, selected_sample_id: str, heads: tuple[str, str],
    should_cancel=None, on_progress=None,
) -> tuple[list[EvaluationSegment], int]:
    """Return verified logical segments and number of skipped samples."""
    if scope not in {"project", "selected"}:
        raise ValueError("Choose a valid evaluation scope.")
    if scope == "selected" and not selected_sample_id:
        raise ValueError("Select a sample before evaluating the selected sample.")
    segments = []
    skipped = 0
    found_selected = False
    total_samples = max(1, len(samples))
    for sample_index, sample in enumerate(samples):
        if should_cancel is not None and should_cancel():
            raise InterruptedError("Evaluation cancelled.")
        if on_progress is not None:
            on_progress(
                20 + int(3 * sample_index / total_samples),
                f"Checking intervals: sample {sample_index + 1}/{len(samples)}",
            )
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
        starts = []
        ends = []
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
            starts.append(start)
            ends.append(end)
        buckets = [[] for _interval in intervals]
        outside_count = 0
        for event_index, event in enumerate(events):
            if event_index % 512 == 0 and should_cancel is not None and should_cancel():
                raise InterruptedError("Evaluation cancelled.")
            position = _position_ms(event, sample_id)
            interval_index = bisect_right(starts, position) - 1
            if interval_index >= 0 and position < ends[interval_index]:
                buckets[interval_index].append(event)
            else:
                outside_count += 1
        for index, interval_events in enumerate(buckets):
            segments.append(EvaluationSegment(
                f"{sample_id}::interval-{index + 1}", sample_id, tuple(interval_events)
            ))
        if outside_count:
            raise ValueError(
                f"{outside_count} localization event(s) in sample "
                f"{sample_id!r} fall outside its declared intervals."
            )
    if scope == "selected" and not found_selected:
        raise ValueError("The selected sample is no longer in this project.")
    if on_progress is not None:
        on_progress(23, "Preparing evaluation events")
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
    should_cancel=None, on_progress=None,
) -> dict:
    """Score a snapshot; no project or model state is changed."""
    if not truth_head or not prediction_head or truth_head == prediction_head:
        raise ValueError("Choose two different localization heads.")
    custom = tuple(sorted(set(int(value) for value in tolerances_ms)))
    if not custom or custom[0] < 0 or custom[-1] > 60000 or any(value % 100 for value in custom):
        raise ValueError("Choose at least one tolerance between 0.0 and 60.0 seconds in 0.1-second steps.")
    if on_progress is not None:
        on_progress(20, "Checking samples and intervals")
    segments, skipped_samples = eligible_segments(
        samples, scope, selected_sample_id, (truth_head, prediction_head),
        should_cancel=should_cancel, on_progress=on_progress,
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
    if on_progress is not None:
        on_progress(23, "Loading OpenSportsLib spotting metrics")
    from opensportslib.metrics.localization_metric import (
        compute_average_precision, get_predictions, parse_ground_truth,
    )

    truth_by_label = parse_ground_truth(truth)
    all_tolerances = sorted(set(TIGHT_TOLERANCES_MS) | set(LOOSE_TOLERANCES_MS) | set(custom))
    total_scores = len(truth_by_label) * len(all_tolerances)
    scored = 0
    per_class = {}
    for label in sorted(available_truth_labels):
        if should_cancel is not None and should_cancel():
            raise InterruptedError("Evaluation cancelled.")
        if label not in truth_by_label:
            per_class[label] = None
            continue
        predictions = get_predictions(pred, label=label)
        use_fast_ap = (
            _osl_comparison_count(predictions, truth_by_label[label])
            > FAST_AP_COMPARISON_THRESHOLD
        )
        per_class[label] = {}
        for tolerance in all_tolerances:
            if should_cancel is not None and should_cancel():
                raise InterruptedError("Evaluation cancelled.")
            detail = (
                f"Scoring {label}: AP@{tolerance / 1000:g} s "
                f"({scored + 1}/{total_scores})"
            )
            if on_progress is not None:
                on_progress(25 + int(74 * scored / total_scores), detail)
            if use_fast_ap:
                def score_progress(done, total):
                    if on_progress is not None and total:
                        on_progress(
                            25 + int(74 * (scored + done / total) / total_scores),
                            detail,
                        )

                ap = _fast_average_precision(
                    predictions, truth_by_label[label], tolerance,
                    should_cancel=should_cancel, on_progress=score_progress,
                )
            else:
                ap = compute_average_precision(
                    predictions, truth_by_label[label], tolerance=tolerance
                )
            per_class[label][tolerance] = float(ap)
            scored += 1
            if on_progress is not None:
                on_progress(25 + int(74 * scored / total_scores), detail)
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
    if on_progress is not None:
        on_progress(100, "Evaluation complete")
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
    progress = pyqtSignal(int, str)

    def __init__(self, samples: list[dict], options: dict, project_root: str = ""):
        super().__init__()
        self.samples = samples
        self.options = options
        self.project_root = project_root
        self.h5_origin_records = {}
        self._last_progress_value = -1
        self._last_progress_text = ""
        self._last_progress_time = 0.0

    def _report_progress(self, value, description):
        now = time.monotonic()
        stage_boundary = description.startswith((
            "Opening H5 timeline", "Loading OpenSportsLib"
        ))
        if (
            value != self._last_progress_value
            or (
                description != self._last_progress_text
                and (stage_boundary or now - self._last_progress_time >= 0.2)
            )
        ):
            self._last_progress_value = value
            self._last_progress_text = description
            self._last_progress_time = now
            self.progress.emit(value, description)

    def run(self):
        try:
            project_utc_events_for_evaluation(
                self.samples, self.project_root,
                scope=self.options["scope"],
                selected_sample_id=self.options["selected_sample_id"],
                heads=(self.options["truth_head"], self.options["prediction_head"]),
                should_cancel=self.isInterruptionRequested,
                on_progress=self._report_progress,
                h5_origin_records=self.h5_origin_records,
            )
            self.completed.emit(evaluate_localization_heads(
                self.samples, **self.options,
                should_cancel=self.isInterruptionRequested,
                on_progress=self._report_progress,
            ))
        except Exception as exc:
            self.failed.emit(str(exc))
