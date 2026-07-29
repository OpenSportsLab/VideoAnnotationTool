"""Parsing and defaults for application-wide media-control preferences."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math


DEFAULT_PLAYBACK_FACTORS = "2,4"
DEFAULT_SEEK_INTERVALS = "1,5"
PLAYBACK_FACTORS_KEY = "media/playback_factors"
SEEK_INTERVALS_KEY = "media/seek_intervals_seconds"

_THREE_DECIMALS = Decimal("0.001")


@dataclass(frozen=True)
class ParsedMediaControls:
    normalized_text: str
    values: tuple[float, ...]


def format_control_value(value: float) -> str:
    """Format a positive control value with no more than three decimals."""
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _parse_positive_values(text: str, field_name: str) -> tuple[Decimal, ...]:
    raw_tokens = str(text).split(",")
    if not raw_tokens or any(not token.strip() for token in raw_tokens):
        raise ValueError(f"{field_name} must be a comma-separated list of positive numbers.")

    values = set()
    for token in raw_tokens:
        try:
            value = Decimal(token.strip())
        except InvalidOperation as exc:
            raise ValueError(f"{field_name} contains an invalid number: {token.strip()!r}.") from exc
        if not value.is_finite() or value <= 0:
            raise ValueError(f"{field_name} values must be finite and greater than zero.")
        try:
            rounded = value.quantize(_THREE_DECIMALS, rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise ValueError(f"{field_name} value is outside the supported numeric range.") from exc
        if rounded <= 0:
            raise ValueError(f"{field_name} values must remain positive at millisecond precision.")
        values.add(rounded)
    return tuple(sorted(values))


def parse_playback_factors(text: str) -> ParsedMediaControls:
    factors = _parse_positive_values(text, "Playback factors")
    rates = {Decimal("1")}
    for factor in factors:
        try:
            reciprocal = (Decimal("1") / factor).quantize(
                _THREE_DECIMALS, rounding=ROUND_HALF_UP
            )
        except InvalidOperation as exc:
            raise ValueError("A playback factor is outside the supported numeric range.") from exc
        if reciprocal <= 0:
            raise ValueError("A playback factor reciprocal rounds to zero at three decimal places.")
        rates.add(factor)
        rates.add(reciprocal)

    normalized = ",".join(format_control_value(float(value)) for value in factors)
    float_rates = tuple(float(value) for value in sorted(rates))
    if any(not math.isfinite(value) or value <= 0 for value in float_rates):
        raise ValueError("Playback factors produced an invalid playback rate.")
    return ParsedMediaControls(normalized, float_rates)


def parse_seek_intervals(text: str) -> ParsedMediaControls:
    intervals = _parse_positive_values(text, "Seek intervals")
    normalized = ",".join(format_control_value(float(value)) for value in intervals)
    return ParsedMediaControls(normalized, tuple(float(value) for value in intervals))


def load_media_control_settings(settings) -> tuple[ParsedMediaControls, ParsedMediaControls]:
    """Load preferences, falling back independently when stored values are invalid."""
    factor_text = settings.value(PLAYBACK_FACTORS_KEY, DEFAULT_PLAYBACK_FACTORS)
    seek_text = settings.value(SEEK_INTERVALS_KEY, DEFAULT_SEEK_INTERVALS)
    try:
        factors = parse_playback_factors(str(factor_text))
    except ValueError:
        factors = parse_playback_factors(DEFAULT_PLAYBACK_FACTORS)
    try:
        intervals = parse_seek_intervals(str(seek_text))
    except ValueError:
        intervals = parse_seek_intervals(DEFAULT_SEEK_INTERVALS)
    return factors, intervals
