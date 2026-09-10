"""Application-wide configurable keyboard-shortcut preferences."""

from dataclasses import dataclass

from PyQt6.QtGui import QKeySequence


@dataclass(frozen=True)
class ShortcutDefinition:
    name: str
    label: str
    default: str
    group: str

    @property
    def settings_key(self) -> str:
        return f"shortcuts/{self.name}"


SHORTCUT_DEFINITIONS = (
    ShortcutDefinition("open_dataset", "Load dataset", "Ctrl+O", "Project"),
    ShortcutDefinition("save_dataset", "Save dataset", "Ctrl+S", "Project"),
    ShortcutDefinition("save_dataset_as", "Save dataset as", "Ctrl+Shift+S", "Project"),
    ShortcutDefinition("hf_download", "Download dataset from HF", "Ctrl+D", "Project"),
    ShortcutDefinition("hf_upload", "Upload dataset to HF", "Ctrl+U", "Project"),
    ShortcutDefinition("play_pause", "Play / Pause", "Space", "Media"),
    ShortcutDefinition("step_backward", "Step one frame backward", "Left", "Media"),
    ShortcutDefinition("step_forward", "Step one frame forward", "Right", "Media"),
    ShortcutDefinition(
        "seek_backward_primary",
        "Seek backward (primary interval)",
        "Ctrl+Left",
        "Media",
    ),
    ShortcutDefinition(
        "seek_forward_primary",
        "Seek forward (primary interval)",
        "Ctrl+Right",
        "Media",
    ),
    ShortcutDefinition(
        "seek_backward_secondary",
        "Seek backward (secondary interval)",
        "Ctrl+Shift+Left",
        "Media",
    ),
    ShortcutDefinition(
        "seek_forward_secondary",
        "Seek forward (secondary interval)",
        "Ctrl+Shift+Right",
        "Media",
    ),
    ShortcutDefinition(
        "localization_set_time",
        "Set selected event to current video time",
        "Ctrl+Return",
        "Localization",
    ),
    ShortcutDefinition(
        "localization_accept",
        "Accept selected prediction",
        "Ctrl+Enter",
        "Localization",
    ),
    ShortcutDefinition(
        "localization_reject",
        "Reject selected prediction",
        "Ctrl+Backspace",
        "Localization",
    ),
)

SHORTCUT_DEFINITION_BY_NAME = {
    definition.name: definition for definition in SHORTCUT_DEFINITIONS
}
DEFAULT_SHORTCUTS = {
    definition.name: definition.default for definition in SHORTCUT_DEFINITIONS
}


def normalize_shortcut(value: object) -> str:
    sequence = QKeySequence(str(value or ""))
    return sequence.toString(QKeySequence.SequenceFormat.PortableText)


def _sequences_conflict(left: QKeySequence, right: QKeySequence) -> bool:
    no_match = QKeySequence.SequenceMatch.NoMatch
    return left.matches(right) != no_match or right.matches(left) != no_match


def _standard_shortcuts() -> tuple[QKeySequence, ...]:
    standard = (
        QKeySequence.StandardKey.Quit,
        QKeySequence.StandardKey.Undo,
        QKeySequence.StandardKey.Redo,
    )
    # Headless platforms can resolve a StandardKey to an empty sequence.
    return tuple(
        sequence for value in standard if not (sequence := QKeySequence(value)).isEmpty()
    )


def validate_application_shortcuts(values: object) -> dict[str, str]:
    """Reject empty, duplicate, prefix, or standard-key conflicts."""
    candidates = dict(values or {})
    normalized: dict[str, str] = {}
    missing_names = []
    for definition in SHORTCUT_DEFINITIONS:
        text = normalize_shortcut(candidates.get(definition.name, definition.default))
        if not text:
            missing_names.append(definition.name)
        normalized[definition.name] = text
    if missing_names:
        if any(
            name in {"localization_accept", "localization_reject"}
            for name in missing_names
        ):
            raise ValueError("Localization accept and reject shortcuts are required.")
        definition = SHORTCUT_DEFINITION_BY_NAME[missing_names[0]]
        raise ValueError(f"{definition.label} shortcut is required.")

    if _sequences_conflict(
        QKeySequence(normalized["localization_accept"]),
        QKeySequence(normalized["localization_reject"]),
    ):
        raise ValueError("Localization accept and reject shortcuts must be different.")

    definitions = list(SHORTCUT_DEFINITIONS)
    for index, left_definition in enumerate(definitions):
        left_text = normalized[left_definition.name]
        left_sequence = QKeySequence(left_text)
        for right_definition in definitions[index + 1 :]:
            right_text = normalized[right_definition.name]
            if _sequences_conflict(left_sequence, QKeySequence(right_text)):
                raise ValueError(
                    f"{left_definition.label} shortcut {left_text} conflicts with "
                    "another configured shortcut or built-in shortcut "
                    f"({right_definition.label}: {right_text})."
                )
        for standard_sequence in _standard_shortcuts():
            if _sequences_conflict(left_sequence, standard_sequence):
                raise ValueError(
                    f"{left_definition.label} shortcut {left_text} conflicts with a "
                    "platform-standard shortcut."
                )
    return normalized


def load_application_shortcuts(settings) -> dict[str, str]:
    values = {
        definition.name: (
            settings.value(definition.settings_key, definition.default)
            if settings is not None
            else definition.default
        )
        for definition in SHORTCUT_DEFINITIONS
    }
    try:
        return validate_application_shortcuts(values)
    except ValueError:
        return dict(DEFAULT_SHORTCUTS)
