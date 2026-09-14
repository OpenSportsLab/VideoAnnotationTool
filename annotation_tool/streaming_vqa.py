"""Streaming VQA validation and temporal persistence policy (no dataset mutations)."""

import copy
import re
from collections import Counter

from utils import (
    annotation_at_position,
    annotation_position_ms,
    format_annotation_utc_display,
    format_utc_datetime,
    normalize_temporal_annotations_for_write,
    parse_utc_datetime,
)


def entry_errors(entry, other_ids=()):
    if not isinstance(entry, dict):
        return ["Question must be an object."]
    errors = []
    question_id = entry.get("id")
    if not isinstance(question_id, str) or not question_id.strip():
        errors.append("Question needs an ID.")
    elif question_id in other_ids:
        errors.append("Question ID must be unique within the sample.")
    if not isinstance(entry.get("question"), str) or not entry["question"].strip():
        errors.append("Enter a question.")
    position = entry.get("position_ms")
    absolute = parse_utc_datetime(entry.get("timestamp_utc")) is not None
    if type(position) is not int or (position < 0 and not absolute):
        errors.append("Ask time must be integer milliseconds at or after the sample start.")
    if "timestamp_utc" in entry and not absolute:
        errors.append("Correct the invalid UTC ask time.")
    options = entry.get("options")
    if not isinstance(options, list) or len(options) < 2:
        errors.append("Provide at least two choices.")
        options = options if isinstance(options, list) else []
    ids, texts = [], []
    for option in options:
        if not isinstance(option, dict):
            errors.append("Each choice must be an object.")
            continue
        option_id, text = option.get("id"), option.get("text")
        if not isinstance(option_id, str) or not option_id.strip() or option_id in ids:
            errors.append("Choice IDs must be non-empty and unique.")
        ids.append(option_id)
        if not isinstance(text, str) or not text.strip():
            errors.append("Enter text for every choice.")
        elif text.strip() in texts:
            errors.append("Choice texts must be distinct.")
        else:
            texts.append(text.strip())
    correct = entry.get("correct_option_id")
    if not isinstance(correct, str) or ids.count(correct) != 1:
        errors.append("Select exactly one correct choice.")
    return errors


def entries_with_errors(entries):
    """Keep malformed imported rows visible, including an invalid list container."""
    rows = entries if isinstance(entries, list) else [entries]
    counts = Counter(entry["id"] for entry in rows if isinstance(entry, dict) and isinstance(entry.get("id"), str))
    duplicate_ids = {key for key, count in counts.items() if count > 1}
    return [
        (entry, entry_errors(entry, duplicate_ids))
        for entry in rows
    ]


def has_valid_entries(entries):
    return isinstance(entries, list) and any(not errors for _, errors in entries_with_errors(entries))


def normalize_for_write(entries, origin):
    """Normalize valid rows only; never discard or silently repair imported bad data."""
    if not isinstance(entries, list):
        return copy.deepcopy(entries)
    return [
        copy.deepcopy(entry) if errors else normalize_temporal_annotations_for_write([entry], origin)[0]
        for entry, errors in entries_with_errors(entries)
    ]


def format_ask_time(entry, origin):
    if not isinstance(entry, dict):
        return "Invalid time"
    utc = format_annotation_utc_display(entry, origin)
    if utc:
        return utc
    if type(entry.get("position_ms")) is not int:
        return "Invalid time"
    position = annotation_position_ms(entry, origin)
    minutes, remainder = divmod(abs(position), 60000)
    seconds, millis = divmod(remainder, 1000)
    return f"{'-' if position < 0 else ''}{minutes:02d}:{seconds:02d}.{millis:03d}"


def with_ask_time(entry, text, origin):
    """Parse an explicit editor time; reject malformed text instead of guessing zero."""
    text = text.strip()
    match = re.fullmatch(r"(\d+):([0-5]\d)(?:\.(\d{1,3}))?", text)
    if match:
        minutes, seconds, millis = match.groups()
        position = int(minutes) * 60000 + int(seconds) * 1000 + int((millis or "0").ljust(3, "0"))
        updated = copy.deepcopy(entry)
        updated.pop("timestamp_utc", None)
        return annotation_at_position(updated, position, origin)
    timestamp = parse_utc_datetime(text)
    if timestamp is None:
        raise ValueError("Use MM:SS.mmm or an ISO UTC timestamp for the ask time.")
    updated = copy.deepcopy(entry)
    updated["timestamp_utc"] = format_utc_datetime(timestamp)
    updated["position_ms"] = annotation_position_ms(updated, origin)
    return updated
