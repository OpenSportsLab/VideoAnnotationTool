"""Application-wide preferences for localization navigation."""

DEFAULT_LOCALIZATION_PREROLL_MS = 0
MAX_LOCALIZATION_PREROLL_MS = 60_000
LOCALIZATION_PREROLL_MS_KEY = "localization/navigation_preroll_ms"


def normalize_localization_preroll_ms(value: object) -> int:
    """Return a bounded, non-negative localization seek lead time."""
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = DEFAULT_LOCALIZATION_PREROLL_MS
    return max(0, min(normalized, MAX_LOCALIZATION_PREROLL_MS))


def load_localization_preroll_ms(settings) -> int:
    if settings is None:
        return DEFAULT_LOCALIZATION_PREROLL_MS
    return normalize_localization_preroll_ms(
        settings.value(
            LOCALIZATION_PREROLL_MS_KEY,
            DEFAULT_LOCALIZATION_PREROLL_MS,
        )
    )
