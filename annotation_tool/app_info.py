"""Application-level metadata and help text."""

from media_control_settings import format_control_value
from shortcut_settings import DEFAULT_SHORTCUTS

APP_DISPLAY_NAME = "Video Annotation Tool"
APP_VERSION = "v1.4.5"


def build_shortcuts_help_text(
    seek_intervals=(1.0, 5.0),
    shortcuts=None,
) -> str:
    def seconds_text(value) -> str:
        formatted = format_control_value(value)
        unit = "second" if float(value) == 1.0 else "seconds"
        return f"{formatted} {unit}"

    values = dict(DEFAULT_SHORTCUTS)
    values.update(dict(shortcuts or {}))
    lines = [
        "Project",
        f"{values['open_dataset']}: Load dataset JSON",
        f"{values['save_dataset']}: Save dataset",
        f"{values['save_dataset_as']}: Save dataset as",
        f"{values['hf_download']}: Open HF download dialog",
        f"{values['hf_upload']}: Open HF upload dialog",
        "Ctrl/Cmd+Q: Quit",
        "",
        "Undo/Redo",
        "Ctrl/Cmd+Z: Undo",
        "Ctrl/Cmd+Shift+Z or platform redo key: Redo",
        "",
        "Media",
        f"{values['play_pause']}: Play/Pause",
        f"{values['step_backward']}: Seek backward ~40 ms",
        f"{values['step_forward']}: Seek forward ~40 ms",
    ]
    intervals = tuple(seek_intervals)
    if intervals:
        primary = seconds_text(intervals[0])
        lines.extend(
            (
                f"{values['seek_backward_primary']}: Seek backward {primary}",
                f"{values['seek_forward_primary']}: Seek forward {primary}",
            )
        )
    if len(intervals) > 1:
        secondary = seconds_text(intervals[1])
        lines.extend(
            (
                f"{values['seek_backward_secondary']}: Seek backward {secondary}",
                f"{values['seek_forward_secondary']}: Seek forward {secondary}",
            )
        )
    lines.extend(
        (
            "",
            "Localization",
            f"{values['localization_set_time']}: Set selected event to current video time",
            f"{values['localization_accept']}: Accept selected inferred annotation",
            f"{values['localization_reject']}: Reject selected inferred annotation",
        )
    )
    return "\n".join(lines) + "\n"


SHORTCUTS_HELP_TEXT = build_shortcuts_help_text()
