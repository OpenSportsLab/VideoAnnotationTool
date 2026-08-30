"""Application-wide configurable keyboard-shortcut preferences."""

from dataclasses import dataclass

from PyQt6.QtGui import QKeySequence


DEFAULT_LOCALIZATION_ACCEPT_SHORTCUT = "Ctrl+Enter"
DEFAULT_LOCALIZATION_REJECT_SHORTCUT = "Ctrl+Backspace"
LOCALIZATION_ACCEPT_SHORTCUT_KEY = "shortcuts/localization_accept"
LOCALIZATION_REJECT_SHORTCUT_KEY = "shortcuts/localization_reject"


@dataclass(frozen=True)
class LocalizationReviewShortcuts:
    accept: str
    reject: str


def normalize_shortcut(value: object) -> str:
    sequence = QKeySequence(str(value or ""))
    return sequence.toString(QKeySequence.SequenceFormat.PortableText)


def _sequences_conflict(left: QKeySequence, right: QKeySequence) -> bool:
    no_match = QKeySequence.SequenceMatch.NoMatch
    return left.matches(right) != no_match or right.matches(left) != no_match


def _built_in_shortcuts() -> tuple[QKeySequence, ...]:
    explicit = (
        "Ctrl+O",
        "Ctrl+S",
        "Ctrl+Shift+S",
        "Ctrl+D",
        "Ctrl+U",
        "Space",
        "Left",
        "Right",
        "Ctrl+Left",
        "Ctrl+Right",
        "Ctrl+Shift+Left",
        "Ctrl+Shift+Right",
    )
    standard = (
        QKeySequence.StandardKey.Quit,
        QKeySequence.StandardKey.Undo,
        QKeySequence.StandardKey.Redo,
    )
    # A platform without a native binding for a StandardKey (e.g. no window
    # manager under the offscreen QPA platform used for headless tests)
    # resolves it to an empty QKeySequence. An empty sequence isn't a real
    # shortcut in use, but _sequences_conflict's prefix-match check treats it
    # as conflicting with everything, which would reject every candidate
    # shortcut. Drop anything that didn't actually resolve to keys.
    return tuple(QKeySequence(value) for value in explicit) + tuple(
        sequence for value in standard if not (sequence := QKeySequence(value)).isEmpty()
    )


def validate_localization_review_shortcuts(
    accept: object,
    reject: object,
) -> LocalizationReviewShortcuts:
    accept_text = normalize_shortcut(accept)
    reject_text = normalize_shortcut(reject)
    if not accept_text or not reject_text:
        raise ValueError("Localization accept and reject shortcuts are required.")

    accept_sequence = QKeySequence(accept_text)
    reject_sequence = QKeySequence(reject_text)
    if _sequences_conflict(accept_sequence, reject_sequence):
        raise ValueError("Localization accept and reject shortcuts must be different.")

    for sequence in _built_in_shortcuts():
        if _sequences_conflict(accept_sequence, sequence):
            raise ValueError(
                f"Localization accept shortcut {accept_text} conflicts with a built-in shortcut."
            )
        if _sequences_conflict(reject_sequence, sequence):
            raise ValueError(
                f"Localization reject shortcut {reject_text} conflicts with a built-in shortcut."
            )

    return LocalizationReviewShortcuts(accept_text, reject_text)


def load_localization_review_shortcuts(settings) -> LocalizationReviewShortcuts:
    if settings is None:
        return LocalizationReviewShortcuts(
            DEFAULT_LOCALIZATION_ACCEPT_SHORTCUT,
            DEFAULT_LOCALIZATION_REJECT_SHORTCUT,
        )
    accept = settings.value(
        LOCALIZATION_ACCEPT_SHORTCUT_KEY,
        DEFAULT_LOCALIZATION_ACCEPT_SHORTCUT,
    )
    reject = settings.value(
        LOCALIZATION_REJECT_SHORTCUT_KEY,
        DEFAULT_LOCALIZATION_REJECT_SHORTCUT,
    )
    try:
        return validate_localization_review_shortcuts(accept, reject)
    except ValueError:
        return LocalizationReviewShortcuts(
            DEFAULT_LOCALIZATION_ACCEPT_SHORTCUT,
            DEFAULT_LOCALIZATION_REJECT_SHORTCUT,
        )
