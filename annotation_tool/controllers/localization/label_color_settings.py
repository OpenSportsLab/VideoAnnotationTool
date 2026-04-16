from PyQt6.QtCore import QSettings

from colors import normalize_hex_color


SETTINGS_LABEL_COLOR_PREFIX = "localization/label_colors"


def _normalize_token(value: str) -> str:
    return str(value or "").strip().lower()


def _setting_key(head: str, label: str) -> str:
    return f"{SETTINGS_LABEL_COLOR_PREFIX}/{_normalize_token(head)}/{_normalize_token(label)}"


def get_saved_label_color(settings: QSettings | None, head: str, label: str) -> str | None:
    if settings is None:
        return None
    raw = settings.value(_setting_key(head, label), "")
    normalized = normalize_hex_color(raw)
    return normalized or None


def set_saved_label_color(settings: QSettings | None, head: str, label: str, color_hex: str) -> str | None:
    if settings is None:
        return None
    normalized = normalize_hex_color(color_hex)
    if not normalized:
        return None
    settings.setValue(_setting_key(head, label), normalized)
    settings.sync()
    return normalized


def remove_saved_label_color(settings: QSettings | None, head: str, label: str) -> None:
    if settings is None:
        return
    settings.remove(_setting_key(head, label))
    settings.sync()


def rename_saved_label_color(
    settings: QSettings | None,
    old_head: str,
    old_label: str,
    new_head: str,
    new_label: str,
) -> None:
    if settings is None:
        return
    old_key = _setting_key(old_head, old_label)
    value = settings.value(old_key, "")
    normalized = normalize_hex_color(value)
    if normalized:
        settings.setValue(_setting_key(new_head, new_label), normalized)
    settings.remove(old_key)
    settings.sync()


def move_saved_head_colors(
    settings: QSettings | None,
    old_head: str,
    new_head: str,
    labels: list[str],
) -> None:
    if settings is None:
        return
    for label in list(labels or []):
        rename_saved_label_color(settings, old_head, label, new_head, label)


def remove_saved_head_colors(settings: QSettings | None, head: str, labels: list[str]) -> None:
    if settings is None:
        return
    for label in list(labels or []):
        settings.remove(_setting_key(head, label))
    settings.sync()
