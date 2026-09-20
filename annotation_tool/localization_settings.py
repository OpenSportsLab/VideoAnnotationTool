"""Application-wide preferences for localization workflows."""

DEFAULT_LOCALIZATION_PREROLL_MS = 0
MAX_LOCALIZATION_PREROLL_MS = 60_000
LOCALIZATION_PREROLL_MS_KEY = "localization/navigation_preroll_ms"
LOCALIZATION_EVALUATION_SCOPE_KEY = "localization/evaluation_scope"


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


def load_localization_evaluation_scope(settings) -> str:
    if settings is None:
        return "project"
    value = str(settings.value(LOCALIZATION_EVALUATION_SCOPE_KEY, "project"))
    return value if value in {"project", "selected"} else "project"


def save_localization_evaluation_scope(settings, scope: str) -> None:
    if settings is None:
        return
    settings.setValue(
        LOCALIZATION_EVALUATION_SCOPE_KEY,
        scope if scope in {"project", "selected"} else "project",
    )
    settings.sync()
