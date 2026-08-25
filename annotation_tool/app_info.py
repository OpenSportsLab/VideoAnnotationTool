"""Application-level metadata and help text."""

from media_control_settings import format_control_value

APP_DISPLAY_NAME = "Video Annotation Tool"
APP_VERSION = "v1.4.3"

_SHORTCUTS_HELP_PREFIX = """Project
Ctrl+O: Load dataset JSON
Ctrl+S: Save dataset
Ctrl+Shift+S: Save dataset as
Ctrl+D: Open HF download dialog
Ctrl+U: Open HF upload dialog
Ctrl/Cmd+Q: Quit

Undo/Redo
Ctrl/Cmd+Z: Undo
Ctrl/Cmd+Shift+Z or platform redo key: Redo

Media
Space: Play/Pause
Left: Seek backward ~40 ms
Right: Seek forward ~40 ms
"""


def build_shortcuts_help_text(
    seek_intervals=(1.0, 5.0),
    localization_accept="Ctrl+Enter",
    localization_reject="Ctrl+Backspace",
) -> str:
    def seconds_text(value) -> str:
        formatted = format_control_value(value)
        unit = "second" if float(value) == 1.0 else "seconds"
        return f"{formatted} {unit}"

    lines = [_SHORTCUTS_HELP_PREFIX.rstrip()]
    intervals = tuple(seek_intervals)
    if intervals:
        primary = seconds_text(intervals[0])
        lines.extend(
            (
                f"Ctrl+Left: Seek backward {primary}",
                f"Ctrl+Right: Seek forward {primary}",
            )
        )
    if len(intervals) > 1:
        secondary = seconds_text(intervals[1])
        lines.extend(
            (
                f"Ctrl+Shift+Left: Seek backward {secondary}",
                f"Ctrl+Shift+Right: Seek forward {secondary}",
            )
        )
    lines.extend(
        (
            "",
            "Localization review",
            f"{localization_accept}: Accept selected inferred annotation",
            f"{localization_reject}: Reject selected inferred annotation",
        )
    )
    return "\n".join(lines) + "\n"


SHORTCUTS_HELP_TEXT = build_shortcuts_help_text()
