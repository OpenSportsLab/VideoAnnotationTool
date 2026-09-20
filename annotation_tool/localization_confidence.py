"""Shared confidence parsing for localization predictions."""

import math


def numeric_localization_confidence(event: dict) -> float | None:
    if not isinstance(event, dict):
        return None
    for key in ("confidence_score", "confidence", "score"):
        value = event.get(key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(confidence):
            return max(0.0, min(1.0, confidence))
    return None
